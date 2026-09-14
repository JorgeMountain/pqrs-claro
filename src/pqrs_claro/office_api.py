"""Vista previa y descargas locales de oficios, sin enviar documentos."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from .office_models import OfficeGenerate, OfficeInput
from .office_workspace import WorkingInput, get_workspace, save_workspace


def office_router(service):
    router = APIRouter(prefix="/api/cases/{case_id}/office")

    @router.get("")
    def get(case_id: str):
        return service.get(case_id)

    @router.post("/preview")
    def preview(case_id: str, body: OfficeInput):
        return service.preview(case_id, body)

    @router.get("/workspace")
    def workspace(case_id: str):
        return get_workspace(service, case_id)

    @router.put("/workspace")
    def save_working(case_id: str, body: WorkingInput):
        return save_workspace(service, case_id, body)

    @router.post("/generate", status_code=202)
    def generate(case_id: str, body: OfficeGenerate):
        return service.generate(case_id, body)

    @router.get("/runs/{run_id}")
    def run(case_id: str, run_id: str):
        return service.get_run(case_id, run_id)

    @router.get("/runs/{run_id}/files/{kind}")
    def file(case_id: str, run_id: str, kind: str):
        path, mime, name = service.file(case_id, run_id, kind)
        return FileResponse(
            path, media_type=mime, filename=name, content_disposition_type="attachment"
        )

    @router.get("/runs/{run_id}/pages/{number}")
    def page(case_id: str, run_id: str, number: int):
        return Response(service.page(case_id, run_id, number), media_type="image/png")

    return router
