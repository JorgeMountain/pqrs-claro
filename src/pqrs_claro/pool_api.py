"""API del borrador administrativo y de la bolsa secuencial de trámites."""

from urllib.parse import quote

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import Field

from .models import StrictModel
from .pool_service import _admin
from .storage import Conflict


class PoolActor(StrictModel):
    actor_id: str = Field(min_length=1, max_length=40)


class PoolDecision(PoolActor):
    revision: int = Field(ge=1)


class ImportReview(PoolDecision):
    workspace_revision: int | None = Field(default=None, ge=0)
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class TaskSpec(StrictModel):
    request_id: str = Field(min_length=1, max_length=40)
    department: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=8000)
    manager_id: str | None = Field(default=None, max_length=40)


class PoolRoute(PoolDecision):
    tasks: list[TaskSpec] = Field(max_length=400)


class RequestReview(PoolDecision):
    answer: str = Field(max_length=64000)
    gaps: list[str] = Field(max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


class SuggestTask(StrictModel):
    request_id: str = Field(min_length=1, max_length=40)
    instruction: str = Field(default="", max_length=8000)


class SuggestResponsibles(PoolDecision):
    tasks: list[SuggestTask] = Field(min_length=1, max_length=60)


def pool_router(service, admin_review=None, routing=None):
    router = APIRouter()
    base = "/api/cases/{case_id}/pool"

    @router.get("/api/pool")
    def inbox():
        return {"items": service.list()}

    @router.get(base)
    def detail(case_id: str):
        return service.get(case_id)

    @router.post(base + "/start")
    def start(case_id: str, body: PoolActor):
        return service.start(case_id, body.actor_id)

    @router.post(base + "/publish")
    def publish(case_id: str, body: PoolRoute):
        return service.publish(case_id, body.actor_id, body.revision,
                               [task.model_dump() for task in body.tasks])

    if admin_review is not None:
        @router.post(base + "/open-review")
        def open_review(case_id: str, body: PoolDecision):
            return admin_review.open(case_id, body.actor_id, body.revision)

        @router.post(base + "/import-review")
        def import_review(case_id: str, body: ImportReview):
            return admin_review.submit(case_id, body)

    if routing is not None:
        @router.post(base + "/suggest-responsibles")
        def suggest_responsibles(case_id: str, body: SuggestResponsibles):
            _admin(body.actor_id)
            detail = service.get(case_id)
            if (
                detail["stage"] not in {"initial_review", "final_review"}
                or detail["revision"] != body.revision
            ):
                raise Conflict(
                    "El expediente cambió. Actualiza la pantalla antes de sugerir responsables."
                )
            return {
                "suggestions": routing(
                    detail, [task.model_dump() for task in body.tasks]
                )
            }

    @router.post(base + "/return")
    def return_tasks(case_id: str, body: PoolRoute):
        return service.publish(case_id, body.actor_id, body.revision,
                               [task.model_dump() for task in body.tasks], returned=True)

    @router.post(base + "/requests/{request_id}/review")
    def review_request(case_id: str, request_id: str, body: RequestReview):
        return service.review_request(case_id, request_id, body.actor_id, body.revision,
                                      body.answer, body.gaps, body.reason)

    @router.post(base + "/tasks/{task_id}/claim")
    def claim(case_id: str, task_id: str, body: PoolDecision):
        return service.claim(case_id, task_id, body.actor_id, body.revision)

    @router.post(base + "/tasks/{task_id}/complete")
    def complete(case_id: str, task_id: str, actor_id: str = Form(..., max_length=40),
                 revision: int = Form(..., ge=1), note: str = Form("", max_length=16000),
                 files: list[UploadFile] = File(default=[])):
        try:
            return service.complete(case_id, task_id, actor_id, revision, note,
                                    [(f.filename or "", f.file) for f in files])
        finally:
            for f in files:
                f.file.close()

    @router.get(base + "/files/{file_id}")
    def download(case_id: str, file_id: str):
        name, data = service.attachment(case_id, file_id)
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(name, safe='')}"
        })

    @router.post(base + "/approve")
    def approve(case_id: str, body: PoolDecision):
        return service.approve(case_id, body.actor_id, body.revision)

    return router
