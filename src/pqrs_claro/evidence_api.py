"""Carga contextual: originales, recibos y reevaluación real, sin aprobar respuestas."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from .image_ocr import IMAGE_FORMATS
from .source_library import CATEGORIES, MAX_SOURCE_BYTES, digest
from .storage import Conflict, now


class RetryEvidence(BaseModel):
    version: int = Field(ge=1)


def evidence_router(library, sources, cases):
    router = APIRouter()
    with library.connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS evidence_receipts "
            "(id TEXT PRIMARY KEY, case_id TEXT, body TEXT)"
        )

    def save(receipt):
        with library.connect() as conn:
            conn.execute(
                "INSERT INTO evidence_receipts VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (receipt["id"], receipt["case_id"], json.dumps(receipt)),
            )

    def current_case(case_id, version, request_id=None):
        case = cases.get(case_id)
        if case["version"] != version or case["status"] != "confirmed":
            raise Conflict("El expediente cambió o no está confirmado. Recarga antes de aportar.")
        if request_id and request_id not in {r["id"] for r in case["identification"]["requests"]}:
            raise ValueError("La solicitud seleccionada no pertenece a este expediente.")
        return case

    def search(receipt):
        receipt.update(search_status="not_requested", search_error=None)
        if not receipt["case_id"] or receipt["extraction_status"] == "error":
            save(receipt)
            return receipt
        try:
            current_case(receipt["case_id"], receipt["case_version"], receipt["request_id"])
            run = sources.start(receipt["case_id"], receipt["case_version"])
            receipt.update(search_status=run["status"], search_run_id=run.get("id"))
        except (Conflict, ValueError) as exc:
            # El archivo ya está guardado. Reintentar la búsqueda no vuelve a cargarlo.
            receipt.update(search_status="needs_retry", search_error=str(exc))
        save(receipt)
        return receipt

    @router.post("/api/evidence", status_code=201)
    def upload(
        file: UploadFile = File(...),
        title: str = Form(..., max_length=300),
        origin: str = Form(..., max_length=2000),
        category: str = Form(...),
        case_id: str | None = Form(None),
        version: int | None = Form(None),
        request_id: str | None = Form(None),
        shared: bool = Form(False),
        document_id: str | None = Form(None),
    ):
        try:
            if not title.strip() or not origin.strip():
                raise ValueError("Indica el título y de dónde viene el archivo.")
            if category not in CATEGORIES | {"historical_response", "historical_attachment"}:
                raise ValueError("Selecciona un tipo de fuente válido.")
            if Path(file.filename or "").suffix.lower() not in {
                ".pdf",
                ".docx",
                ".txt",
                *IMAGE_FORMATS,
            }:
                raise ValueError("Selecciona un archivo PDF, DOCX, TXT, PNG o JPG.")
            if request_id and not case_id:
                raise ValueError("Selecciona el expediente de la solicitud.")
            case = current_case(case_id, version, request_id) if case_id else None
            scope = None if shared else case_id
            if category == "case_evidence" and scope is None:
                raise ValueError("El soporte debe conservar su alcance privado.")
            if not shared and not case_id:
                raise ValueError("Selecciona un expediente o la biblioteca compartida.")
            data = file.file.read(MAX_SOURCE_BYTES + 1)
            if not data or len(data) > MAX_SOURCE_BYTES:
                raise ValueError("Selecciona un archivo de hasta 20 MB.")
            sha = hashlib.sha256(data).hexdigest()
            with library.lock:
                # El cotejo por alcance no convierte archivos privados en compartidos.
                visible = [s for s in library.list(scope) if s["case_id"] == scope]
                duplicate = next(
                    (
                        s
                        for s in visible
                        if s["sha256"] == sha
                        and s.get("is_latest")
                        and s["category"] == category
                        and s.get("validity") != "superseded"
                        and (not document_id or s["document_id"] == document_id)
                    ),
                    None,
                )
                collection_id = None
                if document_id:
                    previous = next(
                        (s for s in visible if s["document_id"] == document_id), None
                    )
                    if not previous:
                        raise KeyError("Documento no encontrado.")
                    collection_id = previous.get("collection_id")
                if category in {"historical_response", "historical_attachment"}:
                    if not document_id:
                        collection_id = (duplicate or {}).get("collection_id") or (
                            "manual-" + (scope or "shared")
                        )
                    if collection_id not in {c["id"] for c in library.collections()}:
                        library.save_collection(
                            dict(
                                id=collection_id,
                                name="Fuentes aportadas · "
                                + ("biblioteca" if shared else "expediente"),
                                created_at=now(),
                                origin="Carga manual con procedencia individual",
                            )
                        )
                source = duplicate or library.add(
                    file.filename or "fuente.pdf",
                    data,
                    title=title,
                    category=category,
                    origin=origin,
                    case_id=scope,
                    document_id=document_id,
                    collection_id=collection_id,
                    retain_unreadable=True,
                )
                linked_before = library.linked_collections(case_id) if case_id else []
                if case_id and source.get("collection_id"):
                    library.link_collections(
                        case_id,
                        sorted(
                            set(library.linked_collections(case_id) + [source["collection_id"]])
                        ),
                    )
                receipt = dict(
                    id=uuid4().hex,
                    case_id=case_id,
                    case_version=version,
                    request_id=request_id,
                    source_id=source["id"],
                    title=source["title"],
                    source_version=source["version"],
                    sha256=sha,
                    shared=shared,
                    uploaded_filename=file.filename,
                    origin=origin.strip(),
                    created_at=now(),
                    duplicate=bool(duplicate),
                    sources_changed=not duplicate
                    or bool(
                        case_id
                        and source.get("collection_id")
                        and source["collection_id"] not in linked_before
                    ),
                    extraction_status=source.get("extraction_status", "ready"),
                    extraction_error=source.get("extraction_error"),
                    search_run_id=None,
                    case_fingerprint=digest(case["identification"]) if case_id else None,
                )
                save(receipt)
            return search(receipt)
        finally:
            file.file.close()

    @router.get("/api/cases/{case_id}/evidence")
    def receipts(case_id: str):
        case = cases.get(case_id)
        with library.connect() as conn:
            items = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM evidence_receipts WHERE case_id=? ORDER BY rowid DESC",
                    (case_id,),
                )
            ]
        return dict(receipts=items, mapping=sources.get(case_id), version=case["version"])

    @router.post("/api/cases/{case_id}/evidence/{receipt_id}/search", status_code=202)
    def retry(case_id: str, receipt_id: str, body: RetryEvidence):
        current_case(case_id, body.version)
        with library.connect() as conn:
            row = conn.execute(
                "SELECT body FROM evidence_receipts WHERE id=? AND case_id=?", (receipt_id, case_id)
            ).fetchone()
        if not row:
            raise KeyError("Aporte no encontrado.")
        receipt = json.loads(row[0])
        if receipt["case_version"] != body.version:
            raise Conflict("La solicitud cambió. Revisa el documento en el expediente actual.")
        source = library.get(receipt["source_id"], case_id)["source"]
        if not source["is_latest"]:
            raise Conflict(
                "Este aporte corresponde a una versión anterior. Usa la versión más reciente."
            )
        receipt["extraction_status"] = source.get("extraction_status", "ready")
        return search(receipt)

    return router
