"""API de biblioteca y mapa de fuentes por solicitud."""

import json
from pathlib import Path

import pymupdf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .catalog_labels import MAX_TOPICS
from .config import ROOT
from .redaction_notice import redaction_notice
from .source_library import MAX_SOURCE_BYTES


class SourceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed_by: str = Field(min_length=1, max_length=200)
    review_note: str = Field(min_length=1, max_length=3000)
    validity: str
    case_id: str | None = None


class SearchSources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class LinkCollections(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_ids: list[str] = Field(max_length=100)


class SectorLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[str] = Field(max_length=MAX_TOPICS)
    issuer: str | None = Field(max_length=120)
    period: str | None = Field(max_length=120)
    expected_revision: int = Field(ge=0)


def source_router(library, service, cases):
    router = APIRouter()

    @router.get("/api/source-collections")
    def collections(case_id: str | None = None):
        if case_id:
            cases.get(case_id)
        return {
            "collections": library.collections(),
            "linked_collection_ids": library.linked_collections(case_id) if case_id else [],
        }

    @router.get("/api/cases/{case_id}/source-collections")
    def selected_collections(case_id: str, response: Response, watch_redaction: bool = False):
        cases.assert_visible(case_id)
        if watch_redaction:
            response.headers["Cache-Control"] = "no-store"
            return redaction_notice(library, cases, case_id)
        return {"collection_ids": library.linked_collections(case_id)}

    @router.put("/api/cases/{case_id}/source-collections")
    def link_collections(case_id: str, body: LinkCollections):
        cases.get(case_id)
        with library.lock:
            previous = library.linked_collections(case_id)
            selected = library.link_collections(case_id, body.collection_ids)
            return {
                "collection_ids": selected,
                "scope_reduced": bool(set(previous) - set(selected)),
            }

    @router.get("/api/sources")
    def sources(case_id: str | None = None, with_labels: bool = False,
                topic: str | None = None, issuer: str | None = None, period: str | None = None):
        if case_id:
            cases.get(case_id)
        return dict(
            sources=(library.catalog_sources(case_id, topic=topic, issuer=issuer, period=period)
                     if with_labels or any(v is not None for v in (topic, issuer, period))
                     else library.list(case_id)),
            storage=dict(
                mode="local",
                description="Originales y versiones conservados en este equipo",
                cloud_connected=False,
            ),
        )

    @router.post("/api/sources", status_code=201)
    def upload(
        file: UploadFile = File(...),
        title: str = Form(...),
        category: str = Form(...),
        origin: str = Form(...),
        case_id: str | None = Form(None),
        document_id: str | None = Form(None),
    ):
        try:
            if case_id:
                cases.get(case_id)
            data = file.file.read(MAX_SOURCE_BYTES + 1)
            return library.add(
                file.filename or "fuente.pdf",
                data,
                title=title,
                category=category,
                origin=origin,
                case_id=case_id,
                document_id=document_id,
            )
        finally:
            file.file.close()

    @router.get("/api/sources/{source_id}")
    def detail(source_id: str, case_id: str | None = None, with_labels: bool = False):
        result = library.get(source_id, case_id)
        if with_labels:
            result["sector"] = library.sector_record(source_id, case_id)
        return result

    @router.put("/api/sources/{source_id}/sector")
    def update_shared_labels(source_id: str, body: SectorLabels):
        return library.update_sector_labels(source_id, **body.model_dump())

    @router.get("/api/sources/{source_id}/versions")
    def versions(source_id: str, case_id: str | None = None):
        source = library.get(source_id, case_id)["source"]
        return {
            "versions": [
                s for s in library.list(case_id) if s["document_id"] == source["document_id"]
            ]
        }

    @router.get("/api/sources/{source_id}/original")
    def original(source_id: str, case_id: str | None = None):
        source = library.get(source_id, case_id)["source"]
        extension = Path(source["filename"]).suffix.lower()
        media = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".txt": "text/plain; charset=utf-8",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        unreadable = source.get("extraction_status") == "error"
        inline = not unreadable and extension in {".pdf", ".png", ".jpg", ".jpeg"}
        headers = {"Content-Security-Policy": "default-src 'none'; sandbox"} if inline else None
        return FileResponse(
            library.original(source_id, case_id),
            media_type=(
                "application/octet-stream"
                if unreadable
                else media.get(extension, "application/octet-stream")
            ),
            filename=source["filename"],
            content_disposition_type="inline" if inline else "attachment",
            headers=headers,
        )

    @router.get("/api/sources/{source_id}/pages/{number}.png")
    def preview(source_id: str, number: int, case_id: str | None = None):
        path = library.original(source_id, case_id)
        if path.suffix != ".pdf":
            raise HTTPException(
                404, "Esta fuente tiene secciones de texto; abre su original para ver el formato."
            )
        with pymupdf.open(path) as doc:
            if not 1 <= number <= len(doc):
                raise HTTPException(404, "La página no existe.")
            page = doc[number - 1]
            scale = min(1.5, 1800 / max(page.rect.width, page.rect.height, 1.0))
            return Response(
                page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png"),
                media_type="image/png",
            )

    @router.get("/api/cases/{case_id}/source-versions/{source_id}/pages/{number}/view")
    def citation_page(case_id: str, source_id: str, number: int, response: Response):
        cases.assert_visible(case_id)
        detail = library.get(source_id, case_id)
        source = detail["source"]
        page = next((p for p in detail["pages"] if p["number"] == number), None)
        if page is None:
            raise HTTPException(404, detail={
                "code": "page_not_found",
                "message": "La página o sección citada no está disponible.",
            })
        response.headers["Cache-Control"] = "no-store"
        result = dict(text=page["text"], method=page["method"], version=source["version"],
                      filename=source["filename"], page=number, words=[])
        if Path(source["filename"]).suffix.lower() == ".pdf":
            with pymupdf.open(library.original(source_id, case_id)) as document:
                pdf_page = document[number - 1]
                bounds = pdf_page.rect
                result.update(width=bounds.width, height=bounds.height)
                if page["method"] == "native":
                    # PDF word boxes are unrotated; use the coordinate system of the PNG.
                    rotation = pdf_page.rotation_matrix
                    result["words"] = [
                        [word[4], *list((pymupdf.Rect(word[:4]) * rotation) & bounds)]
                        for word in pdf_page.get_text("words", sort=True)
                    ]
        return result

    @router.put("/api/sources/{source_id}/review")
    def review(source_id: str, body: SourceReview, case_id: str | None = None):
        values = body.model_dump(exclude={"case_id"})
        return library.review(source_id, case_id=case_id or body.case_id, **values)

    @router.get("/api/cases/{case_id}/sources")
    def mapping(case_id: str, compact: bool = False):
        return service.progress(case_id) if compact else service.get(case_id)

    @router.post("/api/cases/{case_id}/sources/search", status_code=202)
    def search(case_id: str, body: SearchSources):
        return service.start(case_id, body.version)

    @router.post("/api/cases/{case_id}/sources/example", status_code=201)
    def example(case_id: str):
        case = cases.get(case_id)
        if "ejemplo ficticio" not in case["filename"].casefold():
            raise ValueError(
                "Estas fuentes ficticias solo se pueden preparar en el expediente de ejemplo."
            )
        folder = ROOT / "examples" / "sources"
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig"))
        if isinstance(manifest, dict):
            manifest = manifest["sources"]
        added = []
        for entry in manifest:
            if entry["usage"] != "default":
                continue
            existing = [
                s
                for s in library.list(case_id)
                if s["case_id"] == case_id and s["filename"] == entry["filename"]
            ]
            if existing:
                added.append(existing[0])
                continue
            source = library.add(
                entry["filename"],
                (folder / entry["filename"]).read_bytes(),
                title=entry["title"],
                category=entry["category"],
                origin=entry["origin"],
                case_id=case_id,
            )
            added.append(
                library.review(
                    source["id"],
                    case_id=case_id,
                    reviewed_by=entry["reviewed_by"],
                    review_note=entry["review_note"],
                    validity=entry["validity"],
                )
            )
        return {
            "sources": added,
            "message": "Fuentes ficticias preparadas únicamente para este ejemplo.",
        }

    return router
