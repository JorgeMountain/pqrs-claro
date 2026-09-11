"""Reextracción local en dos pasos: propuesta auditable y aplicación con copia previa."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing
from pathlib import Path

import pymupdf

from .image_ocr import IMAGE_FORMATS, normalized_image_png, validate_image
from .models import DomainError
from .storage import now

PLAN_VERSION = 1
EXTRACTION_FIELDS = {
    "extraction_status",
    "extraction_note",
    "extraction_revision",
    "extracted_at",
    "extraction_engine",
    "extraction_report",
}


def state_digest(source, pages):
    value = json.dumps([source, pages], sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def read_rows(data_dir, collections, source_ids=(), *, file_kind="pdf"):
    if file_kind not in {"pdf", "images"}:
        raise DomainError("El tipo de fuentes solicitado no está admitido.")
    suffixes = {".pdf"} if file_kind == "pdf" else set(IMAGE_FORMATS)
    database = Path(data_dir).resolve() / "biblioteca.sqlite"
    if not database.is_file():
        raise DomainError("No se encontró la biblioteca que se quiere reextraer.")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        records = conn.execute("SELECT body,pages FROM sources ORDER BY id").fetchall()
    rows = [(json.loads(body), json.loads(pages)) for body, pages in records]
    latest = {}
    for source, _ in rows:
        key = source["document_id"]
        latest[key] = max(latest.get(key, 0), source["version"])
    chosen = [
        (source, pages)
        for source, pages in rows
        if source.get("collection_id") in collections
        and source.get("case_id") is None
        and source["version"] == latest[source["document_id"]]
        and Path(source["filename"]).suffix.lower() in suffixes
        and source.get("extraction_status") in {"pending", "partial"}
        and (not source_ids or source["id"] in source_ids)
    ]
    if source_ids and set(source_ids) != {s["id"] for s, _ in chosen}:
        raise DomainError("Alguna fuente solicitada no es del tipo pendiente del alcance elegido.")
    return chosen


def is_candidate(page):
    return bool(page.get("needs_review") or not page.get("text", "").strip())


def original_path(data_dir, source):
    sid = source["id"]
    if not re.fullmatch(r"[a-f0-9]{32}", sid):
        raise DomainError("El identificador de fuente no tiene el formato esperado.")
    root = Path(data_dir).resolve() / "library"
    suffix = Path(source["filename"]).suffix.lower()
    if suffix not in {".pdf", *IMAGE_FORMATS}:
        raise DomainError("El formato original no admite esta reextracción.")
    path = (root / sid / ("original" + suffix)).resolve()
    if root not in path.parents or not path.is_file():
        raise DomainError("Falta el original dentro de la biblioteca.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise DomainError("El original cambió; se detuvo la reextracción de esta fuente.")
    return path


def extraction_baseline(source, old_pages, path):
    """Only a verified single-frame image can introduce its missing first section."""
    if path.suffix.lower() not in IMAGE_FORMATS:
        with pymupdf.open(path) as document:
            if not document.is_pdf or document.needs_pass:
                raise DomainError("El original debe ser un PDF sin contraseña.")
            if len(document) != len(old_pages) or [p["number"] for p in old_pages] != list(
                range(1, len(document) + 1)
            ):
                raise DomainError(
                    "El número de páginas cambió respecto de la extracción registrada."
                )
        return old_pages
    validate_image(path.read_bytes(), path.suffix)
    if (
        source.get("location_kind") != "section"
        or type(source.get("page_count")) is not int
        or source["page_count"] != len(old_pages)
        or len(old_pages) > 1
        or (old_pages and old_pages[0].get("number") != 1)
    ):
        raise DomainError("La imagen debe conservar una sola sección numerada como 1.")
    return old_pages or [dict(number=1, text="", method="ocr", needs_review=True)]


def extraction_status(pages, pending_pages=()):
    if not any(page["text"].strip() for page in pages):
        return "pending"
    if pending_pages:
        return "partial"
    return "ready"


def add_ocr_text(native, recognized):
    """Keep native text literally; append OCR lines that are not already represented."""
    if not native.strip():
        return recognized.strip(), "ocr"
    native_normalized = " ".join(native.split()).casefold()
    additions = []
    for line in recognized.splitlines():
        normalized = " ".join(line.split()).casefold()
        if normalized and normalized not in native_normalized:
            additions.append(line)
    if not additions:
        return native, "preserved_native"
    return native + "\n\n" + "\n".join(additions), "ocr_augmented"


def prepare_source(data_dir, source, old_pages, ocr, *, progress=None):
    path = original_path(data_dir, source)
    started = time.monotonic()
    baseline = extraction_baseline(source, old_pages, path)
    if path.suffix.lower() in IMAGE_FORMATS:
        return prepare_image_source(data_dir, source, old_pages, baseline, path, ocr, progress)
    pages = copy.deepcopy(baseline)
    events = []
    with pymupdf.open(path) as document:
        if not document.is_pdf or document.needs_pass:
            raise DomainError("El original debe ser un PDF sin contraseña.")
        if len(document) != len(pages) or [p["number"] for p in pages] != list(
            range(1, len(document) + 1)
        ):
            raise DomainError("El número de páginas cambió respecto de la extracción registrada.")
        for index, old in enumerate(old_pages):
            if not is_candidate(old):
                continue
            pdf_page = document[index]
            event = {"page": index + 1, "previous_characters": len(old["text"])}
            try:
                # Keep native blank pages blank; do not infer a blank scan from failed OCR.
                if (
                    not pdf_page.get_text().strip()
                    and not pdf_page.get_image_info()
                    and not (pdf_page.get_drawings())
                ):
                    event["action"] = "blank_native_page"
                    pages[index] = dict(
                        number=index + 1, text="", method="native", needs_review=False
                    )
                else:
                    dimension = min(3200, ocr.probe().get("max_dimension", 3200))
                    zoom = min(3.0, dimension / max(pdf_page.rect.width, pdf_page.rect.height))
                    png = pdf_page.get_pixmap(
                        matrix=pymupdf.Matrix(zoom, zoom), alpha=False
                    ).tobytes("png")
                    recognized = ocr(png)
                    if not isinstance(recognized, str) or len("".join(recognized.split())) < 8:
                        raise DomainError("OCR sin texto suficiente; la página requiere cotejo.")
                    text, action = add_ocr_text(old["text"], recognized)
                    event.update(action=action, ocr_characters=len(recognized))
                    if action != "preserved_native":
                        pages[index] = dict(
                            number=index + 1, text=text, method="ocr", needs_review=True
                        )
            except (DomainError, RuntimeError, ValueError, OSError) as exc:
                event.update(action="pending", error=str(exc))
            events.append(event)
            if progress:
                progress(source["id"], event)
    return prepared_entry(data_dir, source, old_pages, pages, events, ocr, started)


def prepare_image_source(data_dir, source, old_pages, baseline, path, ocr, progress):
    started = time.monotonic()
    pages = copy.deepcopy(baseline)
    events = []
    old = baseline[0]
    if is_candidate(old):
        event = {"page": 1, "previous_characters": len(old["text"])}
        try:
            png, rendering = normalized_image_png(
                path.read_bytes(),
                path.suffix,
                max_dimension=min(3200, ocr.probe().get("max_dimension", 3200)),
            )
            event["image_rendering"] = rendering
            recognized = ocr(png)
            if not isinstance(recognized, str) or len("".join(recognized.split())) < 8:
                raise DomainError("OCR sin texto suficiente; la imagen requiere cotejo.")
            text, action = add_ocr_text(old["text"], recognized)
            event.update(action=action, ocr_characters=len(recognized))
            if action != "preserved_native":
                pages[0] = dict(number=1, text=text, method="ocr", needs_review=True)
        except (DomainError, RuntimeError, ValueError, OSError) as exc:
            event.update(action="pending", error=str(exc))
        events.append(event)
        if progress:
            progress(source["id"], event)
    return prepared_entry(data_dir, source, old_pages, pages, events, ocr, started)


def prepared_entry(data_dir, source, old_pages, pages, events, ocr, started):
    original_path(data_dir, source)
    counts = Counter(event["action"] for event in events)
    pending_pages = [e["page"] for e in events if e["action"] == "pending"]
    new_status = extraction_status(pages, pending_pages)
    changed = bool(events) or new_status != source.get("extraction_status")
    updates = {
        "extraction_status": new_status,
        "extraction_revision": source.get("extraction_revision", 0) + 1,
        "extracted_at": now(),
        "extraction_engine": dict(ocr.probe()),
        "extraction_note": (
            "Reextracción local con Windows OCR. Texto nativo conservado; "
            "las líneas OCR adicionales permanecen en su página y requieren cotejo. "
            "No se modificó el original ni su revisión documental."
        ),
        "extraction_report": {
            "attempted_pages": len(events),
            "actions": dict(counts),
            "pending_pages": pending_pages,
        },
    }
    return {
        "source_id": source["id"],
        "title": source["title"],
        "collection_id": source.get("collection_id"),
        "original_sha256": source["sha256"],
        "expected_state_sha256": state_digest(source, old_pages),
        "changed": changed,
        "updates": updates,
        "pages": pages,
        "result_page_count": len(pages),
        "page_events": events,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def save_plan(path, plan):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".writing")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def validate_page_events(entry, source, old_pages, path):
    """A plan cannot relabel added OCR as native or silently clear a failed scan."""
    revision = entry["updates"]["extraction_revision"]
    if type(revision) is not int or revision != source.get("extraction_revision", 0) + 1:
        raise DomainError("La revisión de extracción debe incrementar exactamente una unidad.")
    expected_numbers = [page["number"] for page in old_pages if is_candidate(page)]
    events = entry["page_events"]
    if [event.get("page") for event in events] != expected_numbers:
        raise DomainError("La propuesta no registra una acción para cada página pendiente.")
    for event in events:
        number = event["page"]
        old, page = old_pages[number - 1], entry["pages"][number - 1]
        action = event.get("action")
        if action in {"ocr", "ocr_augmented"}:
            if (
                page.get("method") != "ocr"
                or page.get("needs_review") is not True
                or len("".join(page.get("text", "").split())) < 8
            ):
                raise DomainError("El texto obtenido por OCR debe conservar su revisión pendiente.")
        elif action == "preserved_native":
            if page != old or not page["text"].strip():
                raise DomainError(
                    "La acción de conservar texto no puede alterarlo ni omitir un vacío."
                )
        elif action == "pending":
            if page != old:
                raise DomainError("Una lectura fallida no puede reemplazar la página anterior.")
        elif action == "blank_native_page":
            if path.suffix.lower() in IMAGE_FORMATS:
                raise DomainError("Una imagen sin transcribir no es una página nativa vacía.")
            if page != dict(number=number, text="", method="native", needs_review=False):
                raise DomainError("Una página vacía no puede contener texto agregado.")
            with pymupdf.open(path) as document:
                original = document[number - 1]
                if (
                    original.get_text().strip()
                    or original.get_image_info()
                    or original.get_drawings()
                ):
                    raise DomainError("Una imagen sin transcribir no es una página nativa vacía.")
        else:
            raise DomainError("La propuesta contiene una acción de extracción desconocida.")
    counts = Counter(event["action"] for event in events)
    pending = [event["page"] for event in events if event["action"] == "pending"]
    expected_report = dict(attempted_pages=len(events), actions=dict(counts), pending_pages=pending)
    if entry["updates"]["extraction_report"] != expected_report:
        raise DomainError("El informe de extracción no coincide con sus acciones por página.")
    return pending


def apply_plan(data_dir, plan, backup_path):
    """All-or-nothing writes with optimistic checks; never modifies review/approval records."""
    if plan.get("plan_version") != PLAN_VERSION or plan.get("status") != "prepared":
        raise DomainError("La propuesta no está completa o tiene un formato desconocido.")
    if Path(plan["data_dir"]).resolve() != Path(data_dir).resolve():
        raise DomainError("La propuesta pertenece a otra biblioteca.")
    backup = Path(backup_path).resolve()
    if backup.exists():
        raise DomainError("La copia de seguridad ya existe; elige un nombre nuevo.")
    entries = [item for item in plan["sources"] if item["changed"]]
    if len({item["source_id"] for item in entries}) != len(entries):
        raise DomainError("La propuesta contiene fuentes repetidas.")
    database = Path(data_dir).resolve() / "biblioteca.sqlite"
    with closing(sqlite3.connect(database, timeout=30)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        # Block competing writers before snapshotting; the backup is the immediate prior state.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as reader:
            backup.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(backup)) as dest:
                reader.backup(dest)
        for entry in entries:
            row = conn.execute(
                "SELECT body,pages FROM sources WHERE id=?", (entry["source_id"],)
            ).fetchone()
            if not row:
                raise DomainError("Una fuente de la propuesta ya no está disponible.")
            source, old_pages = map(json.loads, row)
            if state_digest(source, old_pages) != entry["expected_state_sha256"]:
                raise DomainError(
                    "La fuente cambió desde la propuesta; prepara una nueva extracción."
                )
            if source["sha256"] != entry["original_sha256"]:
                raise DomainError("La propuesta no corresponde al original registrado.")
            path = original_path(data_dir, source)
            baseline = extraction_baseline(source, old_pages, path)
            if source.get("collection_id") not in plan["collections"]:
                raise DomainError("La propuesta contiene una fuente fuera del alcance.")
            if set(entry["updates"]) != EXTRACTION_FIELDS:
                raise DomainError("La propuesta intenta modificar campos ajenos a la extracción.")
            pages = entry["pages"]
            if len(pages) != len(baseline):
                raise DomainError("La propuesta cambia la cantidad de páginas.")
            pending_pages = validate_page_events(entry, source, baseline, path)
            for old, page in zip(baseline, pages, strict=True):
                if page.get("number") != old["number"] or not isinstance(page.get("text"), str):
                    raise DomainError("La propuesta no conserva páginas y texto válidos.")
                if not is_candidate(old) and page != old:
                    raise DomainError("La propuesta intenta reemplazar texto nativo completo.")
                if old["text"].strip() and not page["text"].startswith(old["text"]):
                    raise DomainError("La propuesta perdería texto ya extraído.")
                if page.get("method") not in {"native", "ocr"}:
                    raise DomainError("La propuesta usa un método de lectura desconocido.")
                if page["method"] == "ocr" and page.get("needs_review") is not True:
                    raise DomainError("El OCR debe conservar la marca de revisión pendiente.")
            if entry["updates"]["extraction_status"] != extraction_status(pages, pending_pages):
                raise DomainError("El estado de extracción no corresponde a sus páginas.")
            source.update(entry["updates"])
            if path.suffix.lower() in IMAGE_FORMATS:
                # Determined from verified original, never from arbitrary plan metadata.
                source["page_count"] = 1
            conn.execute(
                "UPDATE sources SET body=?,pages=? WHERE id=?",
                (json.dumps(source), json.dumps(pages), source["id"]),
            )
    return {"updated_sources": len(entries), "backup": str(backup)}
