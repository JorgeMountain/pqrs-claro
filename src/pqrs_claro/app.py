"""Entrada web local: carga, consulta, corrección y confirmación de solicitudes."""

from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, Settings
from .draft_api import draft_router
from .draft_service import DraftService
from .extraction import OpenAIOCR, PDFExtractor
from .models import Identification
from .review_api import review_router
from .review_service import ReviewService
from .service import CaseService
from .source_api import source_router
from .source_library import SourceLibrary
from .source_service import SourceService
from .storage import CaseStore, Conflict


class SaveIdentification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    identification: Identification


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


def check_pdf(data, settings):
    if not data or len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError("Seleccione un PDF de hasta 20 MB.")
    if not data.startswith(b"%PDF-"):
        raise ValueError("El archivo seleccionado no es un PDF válido.")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ValueError("El PDF tiene contraseña. Cargue una copia que pueda leerse.")
            if not 1 <= len(doc) <= settings.max_pages:
                raise ValueError("Esta entrega admite PDF de 1 a 40 páginas.")
    except pymupdf.FileDataError:
        raise ValueError("El PDF está dañado o no puede abrirse.") from None


def create_app(
    settings=None,
    *,
    extractor=None,
    identifier=None,
    source_assessor=None,
    draft_engine=None,
    review_engine=None,
):
    settings = settings or Settings.load()
    store = CaseStore(settings.data_dir)
    service = CaseService(settings, store, extractor=extractor, identifier=identifier)
    source_extractor = PDFExtractor(
        OpenAIOCR(settings.api_key, settings.model) if settings.api_key else None
    )
    library = SourceLibrary(settings.data_dir, source_extractor)
    sources_service = SourceService(settings, store, library, assessor=source_assessor)
    drafts_service = DraftService(settings, store, library, sources_service, engine=draft_engine)
    reviews_service = ReviewService(
        settings,
        store,
        library,
        sources_service,
        drafts_service,
        engine=review_engine,
    )

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted()
        library.recover()
        drafts_service.recover()
        reviews_service.recover()
        yield
        service.close()
        sources_service.close()
        drafts_service.close()
        reviews_service.close()

    app = FastAPI(title="PQRS Claro", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.service = store, service
    app.state.library, app.state.sources = library, sources_service
    app.state.drafts = drafts_service
    app.state.reviews = reviews_service
    app.include_router(source_router(library, sources_service, store))
    app.include_router(draft_router(drafts_service))
    app.include_router(review_router(reviews_service))
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if (origin and origin != expected) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return JSONResponse(
                    {"detail": "Abra la aplicación local para realizar esta acción."}, 403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(KeyError)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": "No se encontró el expediente o la fuente solicitada."}, 404)

    @app.exception_handler(ValueError)
    async def value_handler(request, exc):
        message = (
            "Revise los campos de la identificación."
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        return JSONResponse({"detail": message}, 422)

    @app.get("/api/config")
    def config():
        return dict(
            ready=bool(settings.api_key),
            model=settings.model,
            max_upload_mb=settings.max_upload_mb,
            max_pages=settings.max_pages,
        )

    @app.get("/api/cases")
    def list_cases():
        return store.list()

    @app.post("/api/cases", status_code=201)
    async def upload(file: UploadFile = File(...)):
        try:
            data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
            check_pdf(data, settings)
            filename = Path((file.filename or "peticion.pdf").replace("\\", "/")).name[:180]
            return store.create(filename, data)
        finally:
            await file.close()

    @app.get("/api/demo.pdf")
    def demo_pdf():
        return FileResponse(
            ROOT / "examples" / "peticion_ejemplo.pdf", media_type="application/pdf"
        )

    @app.post("/api/cases/demo", status_code=201)
    def demo():
        data = (ROOT / "examples" / "peticion_ejemplo.pdf").read_bytes()
        check_pdf(data, settings)
        case = store.create("Ejemplo ficticio · tres solicitudes.pdf", data)
        return service.start(case["id"])

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        return store.get(case_id)

    @app.post("/api/cases/{case_id}/analyze", status_code=202)
    def analyze(case_id: str):
        return service.start(case_id)

    @app.put("/api/cases/{case_id}/identification")
    def save(case_id: str, body: SaveIdentification):
        return service.save(case_id, body.version, body.identification.model_dump(mode="json"))

    @app.post("/api/cases/{case_id}/confirm")
    def confirm(case_id: str, body: Confirm):
        return service.confirm(case_id, body.version)

    @app.get("/api/cases/{case_id}/original")
    def original(case_id: str):
        case = store.get(case_id)
        return FileResponse(
            store.original(case_id),
            media_type="application/pdf",
            filename=case["filename"],
            content_disposition_type="inline",
        )

    @app.get("/api/cases/{case_id}/pages/{number}.png")
    def page_image(case_id: str, number: int):
        with pymupdf.open(store.original(case_id)) as doc:
            if not 1 <= number <= len(doc):
                raise HTTPException(404, "No existe esa página.")
            page = doc[number - 1]
            scale = min(1.5, 1800 / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return Response(pix.tobytes("png"), media_type="image/png")

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def home():
        return FileResponse(static / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    return app


if __name__ == "__main__":
    import uvicorn

    settings = Settings.load()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, access_log=False)
