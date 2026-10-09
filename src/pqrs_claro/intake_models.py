"""Contrato de recomendaciones y decisiones de revisión inicial FIAGA."""

from typing import Literal

from pydantic import Field, StrictBool

from .models import StrictModel

CheckKey = Literal["requirements", "respect", "repetition", "classification"]
DocumentRoute = Literal["continue", "complement", "reject", "specialist"]


class PilotReviewMode(StrictModel):
    version: int = Field(ge=1)
    revision: int = Field(ge=0)
    enabled: StrictBool


RequestRoute = Literal["continue", "reiterate", "specialist"]
PetitionType = Literal[
    "information",
    "documents",
    "individual",
    "general",
    "consultation",
    "complaint",
    "claim",
    "suggestion",
    "denunciation",
    "congratulation",
    "undetermined",
]
POLICY_VERSION = 2
DOCUMENT_CHECKS = ["requirements", "respect"]
REQUEST_CHECKS = ["repetition", "classification"]
TERM_REFERENCE = {
    "information": 10,
    "documents": 10,
    "consultation": 30,
    **dict.fromkeys(
        [
            "individual",
            "general",
            "complaint",
            "claim",
            "suggestion",
            "denunciation",
            "congratulation",
        ],
        15,
    ),
}


class OriginalSelection(StrictModel):
    page: int = Field(ge=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)


class IntakeCheck(StrictModel):
    key: CheckKey
    state: Literal["no_observation", "attention", "unverified", "unavailable"]
    summary: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=4000)
    original_refs: list[OriginalSelection] = Field(max_length=12)
    chunk_ids: list[str] = Field(max_length=12)
    pending: list[str] = Field(max_length=15)


class RequestIntake(StrictModel):
    request_id: str
    summary: str = Field(min_length=1, max_length=2000)
    petition_type: PetitionType
    topic: str = Field(min_length=1, max_length=500)
    checks: list[IntakeCheck] = Field(min_length=2, max_length=2)
    proposed_route: RequestRoute
    draft: str | None = Field(max_length=12000)
    draft_missing: list[str] = Field(max_length=15)
    classification_model: str | None = None
    classification_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_probabilities: dict[str, float] | None = None


class DocumentIntake(StrictModel):
    checks: list[IntakeCheck] = Field(min_length=2, max_length=2)
    proposed_route: DocumentRoute
    draft: str | None = Field(max_length=12000)
    draft_missing: list[str] = Field(max_length=15)


class SpecialTreatment(StrictModel):
    detected: bool
    sender: str | None
    subject: str | None
    requested_information: str | None
    stated_term: str | None
    reason: str
    original_refs: list[OriginalSelection] = Field(max_length=12)


class IntakeAssessment(StrictModel):
    document: DocumentIntake
    requests: list[RequestIntake] = Field(min_length=1, max_length=200)
    special_treatment: SpecialTreatment
    warnings: list[str] = Field(max_length=25)


class RepetitionCheck(IntakeCheck):
    key: Literal["repetition"]


class ContextRequestIntake(StrictModel):
    """Generative review contract: classification belongs exclusively to JEV."""

    request_id: str
    summary: str = Field(min_length=1, max_length=2000)
    topic: str = Field(min_length=1, max_length=500)
    checks: list[RepetitionCheck] = Field(min_length=1, max_length=1)
    proposed_route: RequestRoute
    draft: str | None = Field(max_length=12000)
    draft_missing: list[str] = Field(max_length=15)


class IntakeContextAssessment(StrictModel):
    document: DocumentIntake
    requests: list[ContextRequestIntake] = Field(min_length=1, max_length=200)
    special_treatment: SpecialTreatment
    warnings: list[str] = Field(max_length=25)


class IntakeStart(StrictModel):
    mode: Literal["incremental", "full"] = "full"
    version: int = Field(ge=1)
    revision: int = Field(ge=0)


class DocumentDecision(StrictModel):
    route: DocumentRoute
    note: str = Field(min_length=1, max_length=5000)
    reviewed: StrictBool
    communication: str = Field(default="", max_length=12000)


class RequestDecision(StrictModel):
    request_id: str
    route: RequestRoute
    petition_type: PetitionType
    note: str = Field(min_length=1, max_length=5000)
    reviewed: StrictBool
    communication: str = Field(default="", max_length=12000)


class IntakeDecision(StrictModel):
    revision: int = Field(ge=1)
    reviewed_by: str = Field(min_length=1, max_length=200)
    document: DocumentDecision
    requests: list[RequestDecision] = Field(min_length=1, max_length=200)
