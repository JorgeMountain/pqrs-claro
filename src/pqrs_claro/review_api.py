"""API de revisión humana local. Las decisiones no se reciben desde el modelo."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .review_models import FactInput, ReviewApprove, ReviewEdit


class StartReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class AssessReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class RemoveFact(AssessReview):
    edited_by: str = Field(min_length=1, max_length=240)

    @field_validator("edited_by")
    @classmethod
    def name_required(cls, value):
        if not value.strip():
            raise ValueError("Escribe el nombre de quien retira la declaración.")
        return value.strip()


def review_router(service):
    router = APIRouter(prefix="/api/cases/{case_id}/review")

    @router.get("")
    def get_review(case_id: str):
        return service.get(case_id)

    @router.post("/start")
    def start(case_id: str, body: StartReview):
        return service.start(case_id, body.version)

    @router.put("/requests/{request_id}")
    def edit(case_id: str, request_id: str, body: ReviewEdit):
        return service.edit(case_id, request_id, body)

    @router.post("/requests/{request_id}/facts", status_code=201)
    def add_fact(case_id: str, request_id: str, body: FactInput):
        return service.add_fact(case_id, request_id, body)

    @router.delete("/requests/{request_id}/facts/{fact_id}")
    def remove_fact(case_id: str, request_id: str, fact_id: str, body: RemoveFact):
        return service.remove_fact(case_id, request_id, fact_id, body.revision, body.edited_by)

    @router.post("/requests/{request_id}/assess", status_code=202)
    def assess(case_id: str, request_id: str, body: AssessReview):
        return service.assess(case_id, request_id, body.revision)

    @router.post("/requests/{request_id}/approve")
    def approve(case_id: str, request_id: str, body: ReviewApprove):
        return service.approve(case_id, request_id, body)

    @router.get("/requests/{request_id}/history")
    def history(case_id: str, request_id: str):
        return service.history(case_id, request_id)

    @router.get("/approved")
    def approved(case_id: str):
        return service.approved(case_id)

    return router
