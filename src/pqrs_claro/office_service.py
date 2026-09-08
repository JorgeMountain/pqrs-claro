"""Genera y entrega archivos fieles a una aprobación vigente, sin llamadas a IA."""

import hashlib
import json
import re
import threading
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pymupdf

from .models import DomainError
from .office_renderer import OFFICE_VERSION, build_document, pdf_capabilities, render_office
from .office_store import OfficeStore
from .office_templates import load_letterhead
from .source_library import digest
from .storage import Conflict, now, write_original

MAX_ATTACHMENTS_BYTES = 200 * 1024 * 1024
LETTERHEAD_INSTITUTION = "Universidad de Antioquia"
LETTERHEAD_DEPARTMENT = "Facultad de Ingeniería"
_UNSPECIFIED = object()
FILES = {"docx": "oficio.docx", "pdf": "oficio.pdf", "zip": "entrega.zip"}
MIMES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "zip": "application/zip",
}


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def public_run(run):
    result = {key: deepcopy(value) for key, value in run.items() if not key.startswith("_")}
    result.setdefault("letterhead", None)
    result.setdefault("office_version", 1)
    return result


def attachment_name(number, filename):
    """Nombre interno ZIP sin rutas, colisiones ni caracteres de control."""
    name = Path(filename.replace("\\", "/")).name
    name = "".join(
        c for c in unicodedata.normalize("NFC", name) if not unicodedata.category(c).startswith("C")
    )
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .") or "anexo"
    suffix = Path(name).suffix[:12]
    stem = name[: -len(suffix)] if suffix else name
    return f"anexos/{number:02d}_{stem[:150]}{suffix}"


class OfficeService:
    def __init__(self, settings, cases, library, reviews_service, renderer=None):
        self.settings, self.cases, self.library = settings, cases, library
        self.reviews_service = reviews_service
        self.renderer = renderer or render_office
        self.store = OfficeStore(settings.data_dir)
        self.root = (settings.data_dir / "oficios").resolve()
        self.lock = threading.RLock()
        self.active = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="offices")

    def _folder(self, run):
        folder = (self.root / run["case_id"] / run["id"]).resolve()
        if not folder.is_relative_to(self.root) or folder == self.root:
            raise DomainError("La ruta de esta versión de oficio no es válida.")
        return folder

    def _approved(self, case_id, expected=None):
        approved = self.reviews_service.approved(case_id)
        if expected is not None and approved["snapshot_hash"] != expected:
            raise Conflict(
                "Las respuestas aprobadas cambiaron. Prepara de nuevo la vista del oficio."
            )
        return approved

    def _letterhead(self, expected=_UNSPECIFIED):
        letterhead = load_letterhead(self.settings.data_dir)
        public = letterhead.public() if letterhead else None
        if expected is not _UNSPECIFIED and public != expected:
            raise Conflict("El membrete activo cambió. Prepara de nuevo la vista del oficio.")
        return letterhead

    def _letterhead_metadata(self, metadata, letterhead):
        if letterhead and (
            metadata.get("institution") != LETTERHEAD_INSTITUTION
            or metadata.get("department") != LETTERHEAD_DEPARTMENT
        ):
            raise DomainError(
                "El membrete activo corresponde a la Universidad de Antioquia, "
                "Facultad de Ingeniería. Conserva esos datos de institución y dependencia."
            )

    def _sources(self, case_id, approved):
        sources = {}
        for snapshot in approved["requests"]:
            review = snapshot["review"]
            by_chunk = {source["chunk_id"]: source for source in review["available_supports"]}
            for paragraph in review["paragraphs"]:
                for chunk_id in paragraph["cited_chunk_ids"]:
                    source = by_chunk.get(chunk_id)
                    if source is None:
                        raise Conflict("La aprobación contiene una cita que ya no está disponible.")
                    source_id = source["source_id"]
                    path = self.library.original(source_id, case_id)
                    if file_hash(path) != source["sha256"]:
                        raise Conflict("Un original citado no corresponde a la versión aprobada.")
                    canonical = self.library.get(source_id, case_id)["source"]
                    if any(
                        canonical.get(key) != source.get(key)
                        for key in ("document_id", "version", "sha256", "filename", "title")
                    ):
                        raise Conflict("La fuente citada cambió respecto de la aprobación.")
                    sources.setdefault(source_id, {**source, "size": path.stat().st_size})
        return list(sources.values())

    def _attachment_options(self, sources):
        return [
            {key: source[key] for key in ("source_id", "title", "filename", "sha256", "size")}
            for source in sources
        ]

    def _preview(self, case_id, body):
        approved = self._approved(case_id, body["approval_snapshot_hash"])
        letterhead = self._letterhead()
        public_letterhead = letterhead.public() if letterhead else None
        self._letterhead_metadata(body["metadata"], letterhead)
        sources = self._sources(case_id, approved)
        available = {option["source_id"]: option for option in self._attachment_options(sources)}
        identifiers = body["attachment_source_ids"]
        if len(identifiers) > 20 or len(identifiers) != len(set(identifiers)):
            raise ValueError("Selecciona hasta 20 anexos diferentes.")
        if not set(identifiers) <= set(available):
            raise ValueError("Solo puedes anexar documentos citados en las respuestas aprobadas.")
        attachments = [available[identifier] for identifier in identifiers]
        if sum(item["size"] for item in attachments) > MAX_ATTACHMENTS_BYTES:
            raise ValueError("Los anexos seleccionados superan el límite total de 200 MiB.")
        document = build_document(
            approved,
            body["metadata"],
            attachments,
            body["prepared_by"],
            letterhead=public_letterhead,
        )
        if sum(len(p["text"]) for r in document["requests"] for p in r["paragraphs"]) > 600_000:
            raise ValueError("El texto del oficio supera el límite de 600.000 caracteres.")
        self._approved(case_id, approved["snapshot_hash"])
        self._letterhead(public_letterhead)
        return approved, sources, document

    def preview(self, case_id, input_value):
        body = (
            input_value.model_dump(mode="json")
            if hasattr(input_value, "model_dump")
            else input_value
        )
        approved, _, document = self._preview(case_id, body)
        return dict(
            case_id=case_id,
            approval_snapshot_hash=approved["snapshot_hash"],
            preview_hash=digest(document),
            document=document,
        )

    def _files_intact(self, run):
        try:
            if {item["kind"] for item in run["files"]} != set(FILES) or len(run["files"]) != 3:
                return False
            folder = self._folder(run)
            for item in run["files"]:
                if item["name"] != FILES[item["kind"]]:
                    return False
                path = folder / FILES[item["kind"]]
                if (
                    not path.is_file()
                    or path.stat().st_size != item["size"]
                    or file_hash(path) != item["sha256"]
                ):
                    return False
            manifest = folder / "manifest.json"
            return manifest.is_file() and file_hash(manifest) == run.get("_manifest_sha256")
        except (OSError, ValueError, KeyError):
            return False

    def _project(self, run, current_hash, current_letterhead):
        stale = (
            run["stale"]
            or run["approval_snapshot_hash"] != current_hash
            or run.get("letterhead") != current_letterhead
            or run.get("office_version", 1) != OFFICE_VERSION
        )
        if run["status"] == "ready" and not self._files_intact(run):
            stale = True
        if stale and not run["stale"]:
            run = self.store.update(
                run["case_id"],
                run["id"],
                stale=True,
                status="stale",
                error="Esta versión quedó obsoleta, cambió el membrete o sus archivos cambiaron. "
                "Prepara un nuevo oficio.",
            )
        return public_run(run)

    def get(self, case_id):
        with self.lock, self.reviews_service.lock, self.library.lock:
            return self._get_locked(case_id)

    def _get_locked(self, case_id):
        case = self.cases.get(case_id)
        letterhead = self._letterhead()
        public_letterhead = letterhead.public() if letterhead else None
        review = self.reviews_service.get(case_id)
        approved, sources, error = None, [], None
        if review["status"] == "approved":
            try:
                approved = self._approved(case_id)
                sources = self._sources(case_id, approved)
            except (ValueError, KeyError):
                error = (
                    "La aprobación o sus originales requieren revisión antes de preparar el oficio."
                )
                approved = None
        ids = {row["request_id"]: row for row in review["requests"]}
        blockers = []
        for request in (case.get("identification") or {}).get("requests", []):
            row = ids.get(request["id"])
            if not row or row["status"] != "approved":
                blockers.append(
                    dict(
                        request_id=request["id"],
                        label=request["label"],
                        title=request["title"],
                        status=(row or {}).get("status", "not_started"),
                    )
                )
        current_hash = approved["snapshot_hash"] if approved else None
        with self.lock:
            runs = [
                self._project(run, current_hash, public_letterhead)
                for run in self.store.list(case_id)
            ]
        return dict(
            case_id=case_id,
            eligible=approved is not None,
            approval_snapshot_hash=current_hash,
            approved_count=review["approved_count"],
            total_count=review["total_count"],
            blockers=blockers,
            letterhead=public_letterhead,
            defaults={
                "recipient": (case.get("identification") or {}).get("requester") or "",
                "subject": (case.get("identification") or {}).get("subject") or "",
                **(
                    {"institution": LETTERHEAD_INSTITUTION, "department": LETTERHEAD_DEPARTMENT}
                    if letterhead
                    else {}
                ),
            },
            capabilities=pdf_capabilities(),
            attachment_options=self._attachment_options(sources),
            latest=runs[0] if runs else None,
            history=[
                {
                    key: run[key]
                    for key in (
                        "id",
                        "case_id",
                        "status",
                        "stale",
                        "created_at",
                        "completed_at",
                        "prepared_by",
                        "metadata",
                        "approval_snapshot_hash",
                        "preview_hash",
                        "letterhead",
                        "office_version",
                        "attachment_count",
                        "error",
                    )
                }
                for run in runs
            ],
            error=error,
        )

    def get_run(self, case_id, run_id):
        self.cases.get(case_id)
        with self.lock, self.reviews_service.lock, self.library.lock:
            run = self.store.get(case_id, run_id)
            try:
                current_hash = self._approved(case_id)["snapshot_hash"]
            except (ValueError, KeyError):
                current_hash = None
            letterhead = self._letterhead()
            return self._project(run, current_hash, letterhead.public() if letterhead else None)

    def generate(self, case_id, input_value):
        body = (
            input_value.model_dump(mode="json")
            if hasattr(input_value, "model_dump")
            else input_value
        )
        approved, sources, document = self._preview(case_id, body)
        preview_hash = digest(document)
        if body["preview_hash"] != preview_hash:
            raise Conflict(
                "Los datos cambiaron después de la vista previa. Revisa el oficio de nuevo."
            )
        fingerprint = digest(
            {
                "approval_snapshot_hash": approved["snapshot_hash"],
                "preview_hash": preview_hash,
                "office_version": OFFICE_VERSION,
            }
        )
        with self.lock, self.reviews_service.lock, self.library.lock:
            self._approved(case_id, approved["snapshot_hash"])
            self._letterhead(document.get("letterhead"))
            for previous in self.store.matching_input(case_id, fingerprint):
                if previous["input_hash"] == fingerprint and not previous["stale"]:
                    if previous["status"] == "ready" and self._files_intact(previous):
                        return public_run(previous)
                    if (
                        previous["status"] == "generating"
                        and self.active.get(case_id) == previous["id"]
                    ):
                        return public_run(previous)
            if case_id in self.active:
                raise Conflict("Espera a que termine la generación en curso de este expediente.")
            capability = pdf_capabilities()
            if not capability["pdf_available"]:
                raise ValueError(capability.get("error") or "No hay un conversor a PDF disponible.")
            run = dict(
                id=uuid4().hex,
                case_id=case_id,
                status="generating",
                stale=False,
                created_at=now(),
                completed_at=None,
                prepared_by=body["prepared_by"],
                metadata=body["metadata"],
                approval_snapshot_hash=approved["snapshot_hash"],
                preview_hash=preview_hash,
                input_hash=fingerprint,
                office_version=OFFICE_VERSION,
                letterhead=deepcopy(document.get("letterhead")),
                error=None,
                files=[],
                page_count=None,
                verification=None,
                attachment_count=len(document["attachments"]),
                converter=None,
                _manifest_sha256=None,
            )
            self.store.create(run)
            self.active[case_id] = run["id"]
            self.pool.submit(self.run, deepcopy(run), approved, sources, document)
            return public_run(run)

    def _ensure_current(self, run, sources):
        self._approved(run["case_id"], run["approval_snapshot_hash"])
        letterhead = self._letterhead(run.get("letterhead"))
        for source in sources:
            path = self.library.original(source["source_id"], run["case_id"])
            if file_hash(path) != source["sha256"]:
                raise Conflict("Un original cambió durante la generación del oficio.")
        return letterhead

    def run(self, run, approved, sources, document):
        try:
            letterhead = self._ensure_current(run, sources)
            folder = self._folder(run)
            folder.mkdir(parents=True, exist_ok=False)
            render_options = {"template_path": letterhead.path} if letterhead else {}
            rendered = self.renderer(document, folder, **render_options)
            if digest(document) != run["preview_hash"]:
                raise DomainError(
                    "El documento cambió durante la generación. "
                    "No se habilitaron archivos distintos de la vista previa."
                )
            verification = rendered["verification"]
            if (
                verification.get("docx_exact") is not True
                or verification.get("pdf_text_match") is not True
                or verification.get("request_count") != len(document["requests"])
                or verification.get("paragraph_count")
                != sum(len(r["paragraphs"]) for r in document["requests"])
                or not 1 <= rendered["page_count"] <= 200
            ):
                raise DomainError(
                    "La comprobación de fidelidad del oficio no pasó. No se habilitaron descargas."
                )
            with pymupdf.open(folder / FILES["pdf"]) as pdf:
                if not pdf.is_pdf or pdf.needs_pass or len(pdf) != rendered["page_count"]:
                    raise DomainError("El PDF generado no coincide con la versión comprobada.")
            self._ensure_current(run, sources)
            attachments = []
            with zipfile.ZipFile(
                folder / FILES["zip"], "x", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for kind in ("docx", "pdf"):
                    archive.write(folder / FILES[kind], FILES[kind])
                for number, attachment in enumerate(document["attachments"], 1):
                    path = self.library.original(attachment["source_id"], run["case_id"])
                    data = path.read_bytes()
                    if (
                        len(data) != attachment["size"]
                        or hashlib.sha256(data).hexdigest() != attachment["sha256"]
                    ):
                        raise Conflict("Un anexo cambió durante la preparación del paquete.")
                    archive_name = attachment_name(number, attachment["filename"])
                    archive.writestr(archive_name, data)
                    attachments.append({**attachment, "archive_name": archive_name})
            files = [
                dict(
                    kind=kind,
                    name=name,
                    size=(folder / name).stat().st_size,
                    sha256=file_hash(folder / name),
                )
                for kind, name in FILES.items()
            ]
            manifest = dict(
                case_id=run["case_id"],
                run_id=run["id"],
                created_at=now(),
                approval_snapshot_hash=approved["snapshot_hash"],
                preview_hash=run["preview_hash"],
                input_hash=run["input_hash"],
                office_version=OFFICE_VERSION,
                letterhead=run.get("letterhead"),
                document=document,
                approved=approved,
                cited_sources=sources,
                attachments=attachments,
                files=files,
                verification=verification,
                converter=rendered["converter"],
            )
            write_original(
                folder / "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            with self.lock, self.reviews_service.lock, self.library.lock:
                self._ensure_current(run, sources)
                manifest_sha256 = file_hash(folder / "manifest.json")
                if not self._files_intact(
                    {**run, "files": files, "_manifest_sha256": manifest_sha256}
                ):
                    raise DomainError("Los archivos cambiaron antes de publicar el oficio.")
                self.store.update(
                    run["case_id"],
                    run["id"],
                    expected_status="generating",
                    status="ready",
                    files=files,
                    completed_at=now(),
                    page_count=rendered["page_count"],
                    verification=verification,
                    converter=rendered["converter"],
                    _manifest_sha256=manifest_sha256,
                )
        except Exception as exc:
            with self.lock:
                latest = self.store.get(run["case_id"], run["id"])
                if latest["status"] == "generating":
                    stale = isinstance(exc, Conflict)
                    error = (
                        str(exc)
                        if isinstance(exc, DomainError)
                        else (
                            "Las respuestas o sus originales cambiaron. "
                            "Revisa y prepara de nuevo el oficio."
                            if stale
                            else "No se pudo generar el oficio completo. "
                            "Tus respuestas siguen guardadas; puedes reintentar."
                        )
                    )
                    self.store.update(
                        run["case_id"],
                        run["id"],
                        expected_status="generating",
                        status="stale" if stale else "failed",
                        stale=stale,
                        completed_at=now(),
                        error=error,
                    )
        finally:
            with self.lock:
                if self.active.get(run["case_id"]) == run["id"]:
                    self.active.pop(run["case_id"])

    def file(self, case_id, run_id, kind):
        if kind not in FILES:
            raise KeyError("No existe ese tipo de archivo del oficio.")
        run = self.get_run(case_id, run_id)
        if run["status"] != "ready" or run["stale"]:
            raise Conflict("El oficio debe estar completo y vigente para abrir sus archivos.")
        return self._folder(run) / FILES[kind], MIMES[kind], FILES[kind]

    def page(self, case_id, run_id, number):
        path, _, _ = self.file(case_id, run_id, "pdf")
        with pymupdf.open(path) as pdf:
            if not 1 <= number <= len(pdf):
                raise KeyError("No existe esa página del oficio.")
            page = pdf[number - 1]
            scale = min(1.5, 1800 / max(page.rect.width, page.rect.height))
            return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")

    def recover(self):
        self.store.recover()

    def close(self):
        self.pool.shutdown(wait=True)
