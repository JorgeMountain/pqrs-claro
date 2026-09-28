"""Entrada web local: carga, consulta, corrección y confirmación de solicitudes."""

import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .case_lifecycle import case_busy, lifecycle_router
from .config import ROOT, Settings
from .document_view import document_view_router
from .draft_api import draft_router
from .draft_service import DraftService
from .evidence_api import evidence_router
from .extraction import OpenAIOCR, PDFExtractor
from .gmail_api import gmail_router
from .gmail_service import GmailService
from .intake_service import IntakeService, intake_router
from .management import ManagementStore, management_router
from .models import Identification
from .office_api import office_router
from .office_service import OfficeService
from .preparation import PreparationService, preparation_router
from .response_proposals import ResponseProposalService, response_proposal_router
from .review_api import review_router
from .review_service import ReviewService
from .service import CaseService
from .source_api import source_router
from .source_library import SourceLibrary
from .source_service import SourceService
from .source_verification_api import source_verification_router
from .source_verifications import SourceVerificationStore
from .storage import CaseStore, Conflict
from .windows_ocr import WindowsOCR


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
    source_extractor=None,
    draft_engine=None,
    review_engine=None,
    office_renderer=None,
    proposal_engine=None,
    gmail_auth=None,
    intake_engine=None,
    interface="workspace",
):
    if interface not in {"workspace", "recorrido"}:
        raise ValueError("Interfaz no reconocida.")
    settings = settings or Settings.load()
    store = CaseStore(settings.data_dir)
    service = CaseService(settings, store, extractor=extractor, identifier=identifier)
    management = ManagementStore(store)
    service.management = management if settings.management_enabled else None
    store.management = service.management
    source_ocr = None
    if source_extractor is None:
        source_ocr = WindowsOCR() if os.name == "nt" else (
            OpenAIOCR(settings.api_key, settings.model) if settings.api_key else None
        )
        source_extractor = PDFExtractor(source_ocr)
    library = SourceLibrary(settings.data_dir, source_extractor)
    verifications = SourceVerificationStore(settings.data_dir, library, store)
    sources_service = SourceService(settings, store, library, assessor=source_assessor,
                                    verifications=verifications)
    drafts_service = DraftService(settings, store, library, sources_service, engine=draft_engine)
    reviews_service = ReviewService(
        settings,
        store,
        library,
        sources_service,
        drafts_service,
        engine=review_engine,
    )
    drafts_service.reviews = reviews_service
    offices_service = OfficeService(
        settings, store, library, reviews_service, renderer=office_renderer
    )
    preparation = PreparationService(
        store, service, sources_service, drafts_service, reviews_service
    )
    reviews_service.preparation = preparation

    proposals = ResponseProposalService(settings, reviews_service, engine=proposal_engine)
    gmail = GmailService(settings, store, library, check_pdf, auth=gmail_auth)
    initial_review = IntakeService(settings, store, library, sources_service, engine=intake_engine)
    service.initial_review = initial_review
    initial_review.identification = service
    initial_review.downstream = (
        preparation, drafts_service, reviews_service, offices_service, proposals
    )
    preparation.initial_review = initial_review
    drafts_service.initial_review = initial_review
    reviews_service.initial_review = initial_review
    sources_service.initial_review = initial_review

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted()
        library.recover()
        drafts_service.recover()
        reviews_service.recover()
        offices_service.recover()
        preparation.recover()
        proposals.recover()
        initial_review.recover()
        yield
        service.close()
        initial_review.close()
        gmail.close()
        proposals.close()
        preparation.close()
        sources_service.close()
        drafts_service.close()
        reviews_service.close()
        offices_service.close()
        if source_ocr is not None and hasattr(source_ocr, "close"):
            source_ocr.close()

    app = FastAPI(title="PQRS Claro", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.service = store, service
    app.state.management = management
    app.state.library, app.state.sources = library, sources_service
    app.state.verifications = verifications
    app.state.drafts = drafts_service
    app.state.reviews = reviews_service
    app.state.offices = offices_service
    app.state.proposals = proposals
    app.include_router(response_proposal_router(proposals))
    app.state.preparation = preparation
    app.state.gmail = gmail
    app.state.initial_review = initial_review
    app.include_router(intake_router(initial_review))
    lifecycle_services = (preparation, service, sources_service, drafts_service,
                          proposals, offices_service, reviews_service, gmail, library,
                          verifications, initial_review)
    app.include_router(management_router(management, service, lifecycle_services))
    app.include_router(lifecycle_router(store, lifecycle_services))
    app.include_router(gmail_router(gmail))
    app.include_router(preparation_router(preparation))
    app.include_router(source_router(library, sources_service, store))
    app.include_router(document_view_router(store))
    app.include_router(evidence_router(library, sources_service, store))
    app.include_router(source_verification_router(verifications, sources_service))
    app.include_router(draft_router(drafts_service))
    app.include_router(review_router(reviews_service))
    app.include_router(office_router(offices_service))
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
            management_enabled=settings.management_enabled,
            validation_mode=settings.data_dir.resolve().is_relative_to(ROOT / "output" / "qa"),
            model=settings.model,
            max_upload_mb=settings.max_upload_mb,
            max_pages=settings.max_pages,
            initial_review_enabled=settings.initial_review_enabled,
            automatic_initial_review=settings.initial_review_enabled,
            initial_classification_provider=settings.initial_classification_provider,
            environment_label=settings.environment_label,
        )

    @app.get("/api/cases")
    def list_cases(deleted: bool = False):
        return [{**case, "processing": case_busy(case["id"], lifecycle_services)}
                for case in management.enrich(store.list(deleted=deleted))]

    def create_case(filename, data, receipt=None):
        case = store.create(filename, data, receipt=receipt)
        library.link_collections(case["id"], [item["id"] for item in library.collections()])
        return case

    @app.post("/api/cases", status_code=201)
    async def upload(
        file: UploadFile = File(...), subject: str = Form('', max_length=240),
        reference: str = Form('', max_length=100), received_date: date | None = Form(None),
        due_date: date | None = Form(None),
    ):
        try:
            data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
            check_pdf(data, settings)
            received = received_date or date.today()
            if due_date and due_date < received:
                raise ValueError('La fecha límite no puede ser anterior a la recepción.')
            filename = Path((file.filename or "peticion.pdf").replace("\\", "/")).name[:180]
            receipt = dict(subject=subject.strip(), reference=reference.strip(),
                           received_date=received.isoformat(),
                           due_date=due_date.isoformat() if due_date else None)
            return create_case(filename, data, receipt)
        finally:
            await file.close()

    @app.get("/api/demo.pdf")
    def demo_pdf():
        return FileResponse(
            ROOT / "examples" / "peticion_ejemplo.pdf", media_type="application/pdf"
        )

    @app.post("/api/cases/demo", status_code=201)
    def demo():
        if service.management:
            raise Conflict("Usa la demostración del recorrido o recibe el PDF desde la bandeja.")
        data = (ROOT / "examples" / "peticion_ejemplo.pdf").read_bytes()
        check_pdf(data, settings)
        case = create_case("Ejemplo ficticio · tres solicitudes.pdf", data)
        return service.start(case["id"])

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        return {**store.get(case_id), "analysis_running": case_id in service.active,
                **({"management": management.get(case_id)} if settings.management_enabled else {})}

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

    @app.get("/anterior")
    def previous_interface():
        return FileResponse(static / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    if interface == "recorrido":
        from .recorrido_ui import mount_recorrido_ui

        mount_recorrido_ui(app)
    else:
        @app.get("/")
        def home():
            return FileResponse(static / "workspace" / "index.html")

    return app


if __name__ == "__main__":
    import uvicorn

    settings = Settings.load()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, access_log=False)
