"""API de preparación de borradores internos; no aprueba ni envía respuestas."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field


class GenerateDrafts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


def draft_router(service):
    router = APIRouter()

    @router.get("/api/cases/{case_id}/drafts")
    def get_drafts(case_id: str):
        return service.get(case_id)

    @router.post("/api/cases/{case_id}/drafts/generate", status_code=202)
    def generate_drafts(case_id: str, body: GenerateDrafts):
        return service.start(case_id, body.version)

    return router
