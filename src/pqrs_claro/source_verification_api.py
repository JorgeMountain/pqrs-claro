"""Registro humano y aplicación acotada de comprobaciones de las fuentes."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from .models import DomainError
from .storage import Conflict
from .verification_policy import application_matches_check


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationPassage(StrictBody):
    chunk_id: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=40000)


class VerificationScope(StrictBody):
    person: str | None = Field(default=None, max_length=1000)
    period: str | None = Field(default=None, max_length=1000)
    subject: str | None = Field(default=None, max_length=1000)


class CreateVerification(StrictBody):
    version: int = Field(ge=1)
    fact: str = Field(min_length=1, max_length=3000)
    source_id: str | None = Field(default=None, max_length=100)
    passage: VerificationPassage | None = None
    basis: str = Field(min_length=1, max_length=6000)
    attributed_to: str | None = Field(default=None, max_length=500)
    recorded_by: str = Field(min_length=1, max_length=200)
    scope: VerificationScope = Field(default_factory=VerificationScope)
    request_ids: list[str] = Field(min_length=1, max_length=100)


class ApplyVerification(StrictBody):
    version: int = Field(ge=1)
    request_ids: list[str] = Field(min_length=1, max_length=100)
    check_key: str = Field(pattern=r"^check-[a-f0-9]{24}$")
    basis: str = Field(min_length=1, max_length=6000)
    recorded_by: str = Field(min_length=1, max_length=200)


class RevokeVerification(StrictBody):
    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=3000)
    recorded_by: str = Field(min_length=1, max_length=200)


def _matching_checks(run, request_ids, check_key):
    matched = []
    results = {result["request_id"]: result for result in run.get("results", [])}
    for request_id in request_ids:
        result = results.get(request_id, {})
        checks = [*result.get("checks", []), *result.get("missing", [])]
        item = next((check for check in checks if check.get("check_key") == check_key), None)
        if item is None:
            raise DomainError("Selecciona una comprobación vigente en cada pregunta indicada.")
        matched.append(item)
    return matched


def source_verification_router(verifications, source_service):
    router = APIRouter()

    @router.get("/api/cases/{case_id}/verifications")
    def list_records(case_id: str):
        return verifications.list(case_id)

    @router.post("/api/cases/{case_id}/verifications", status_code=201)
    def record_human(case_id: str, body: CreateVerification):
        # kind, fecha y revisión documental se asignan aquí, nunca desde la IA/cliente.
        return verifications.record_human(case_id, **body.model_dump())

    @router.post("/api/cases/{case_id}/verifications/{verification_id}/applications",
                 status_code=201)
    def apply(case_id: str, verification_id: str, body: ApplyVerification):
        case = verifications._case(case_id, body.version)
        request_ids = verifications._requests(case, body.request_ids)
        run = source_service.get(case_id)
        if run.get("stale") or run.get("status") != "ready":
            raise Conflict("Actualiza el análisis de fuentes antes de aplicar una comprobación.")
        record = verifications.get(verification_id)
        checks = _matching_checks(run, request_ids, body.check_key)
        for request_id, check in zip(request_ids, checks, strict=True):
            reason = check.get("reason_code")
            if check.get("stage") == "fulfillment":
                raise DomainError(
                    "Esta actuación se completa en la preparación o entrega de la respuesta, "
                    "no mediante una comprobación de fuentes."
                )
            if (check.get("evidence_state") in {"document_missing", "analysis_error"}
                    or check.get("state") in {"document_missing", "analysis_error"}
                    or reason in {"document_missing", "missing_document", "extraction_error",
                                  "partial_extraction", "analysis_error", "retrieval_error"}):
                raise DomainError(
                    "Esta incidencia requiere localizar el archivo o corregir su lectura; "
                    "una comprobación escrita no la resuelve."
                )
            if record["source_id"]:
                if record["source_id"] not in check.get("linked_source_ids", []):
                    raise DomainError(
                        "La comprobación no corresponde a la fuente de este pendiente."
                    )
            elif reason not in {"fact_confirmation", "applicability", "fact", "model_fact"}:
                raise DomainError(
                    "La confirmación sin archivo sólo puede aplicarse a un hecho concreto; "
                    "los controles documentales necesitan su fuente."
                )
            if record["kind"] == "antecedent_declared" and reason in {
                "source_identity", "provenance", "issued_version", "validity", "transcription",
            }:
                raise DomainError(
                    "La declaración del antecedente no sustituye esta revisión documental humana."
                )
            proposed = {
                "case_id": case_id, "verification_id": verification_id, "record": record,
                "request_ids": request_ids, "check_key": body.check_key,
                "check_reason": reason, "scope_key": check.get("scope_key"),
            }
            if not application_matches_check(proposed, check, request_id):
                raise DomainError(
                    "La comprobación no cubre el documento, pasaje o alcance exacto de este "
                    "pendiente. Selecciona el soporte correspondiente."
                )
        return verifications.apply(
            case_id, verification_id, **body.model_dump(),
            check_reason=checks[0].get("reason_code"), scope_key=checks[0].get("scope_key"),
        )

    @router.post("/api/cases/{case_id}/verifications/{verification_id}/revoke", status_code=201)
    def revoke_record(case_id: str, verification_id: str, body: RevokeVerification):
        return verifications.revoke(
            case_id, "verification", verification_id, **body.model_dump(),
        )

    @router.post("/api/cases/{case_id}/verification-applications/{application_id}/revoke",
                 status_code=201)
    def revoke_application(case_id: str, application_id: str, body: RevokeVerification):
        return verifications.revoke(
            case_id, "application", application_id, **body.model_dump(),
        )

    return router
