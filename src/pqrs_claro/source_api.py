"""API de biblioteca y mapa de fuentes por solicitud."""

import json
from pathlib import Path

import pymupdf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .config import ROOT
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


def source_router(library, service, cases):
    router = APIRouter()

    @router.get("/api/sources")
    def sources(case_id: str | None = None):
        if case_id:
            cases.get(case_id)
        return dict(
            sources=library.list(case_id),
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
    def detail(source_id: str, case_id: str | None = None):
        return library.get(source_id, case_id)

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
            ".txt": "text/plain; charset=utf-8",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        return FileResponse(
            library.original(source_id, case_id),
            media_type=media[extension],
            filename=source["filename"],
            content_disposition_type="inline" if extension == ".pdf" else "attachment",
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
            scale = min(1.5, 1800 / max(page.rect.width, page.rect.height))
            return Response(
                page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png"),
                media_type="image/png",
            )

    @router.put("/api/sources/{source_id}/review")
    def review(source_id: str, body: SourceReview, case_id: str | None = None):
        values = body.model_dump(exclude={"case_id"})
        return library.review(source_id, case_id=case_id or body.case_id, **values)

    @router.get("/api/cases/{case_id}/sources")
    def mapping(case_id: str):
        return service.get(case_id)

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
