"""Entradas explícitas de revisión; ninguna acepta una evaluación o firma del cliente."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StringConstraints, field_validator, model_validator

from .models import StrictModel

Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
InputHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ReviewParagraph(StrictModel):
    text: str = Field(min_length=1, max_length=6000)
    cited_chunk_ids: list[Reference] = Field(default_factory=list, max_length=8)
    cited_fact_ids: list[Reference] = Field(default_factory=list, max_length=8)
    # Se revisa y aprueba junto al texto; el exportador no decide su función con IA.
    office_section: Literal["response", "context", "conclusion"] = "response"

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Escribe el párrafo o retíralo de la respuesta.")
        return value

    @field_validator("cited_chunk_ids", "cited_fact_ids")
    @classmethod
    def unique_references(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Una referencia no puede estar repetida.")
        return value


class PendingResolutionInput(StrictModel):
    pending_id: Reference
    action: Literal["open", "resolved", "not_applicable"]
    note: str = Field(default="", max_length=8000)
    cited_chunk_ids: list[Reference] = Field(default_factory=list, max_length=8)
    cited_fact_ids: list[Reference] = Field(default_factory=list, max_length=8)
    document_decision: Literal["issued", "draft", "provenance_reviewed"] | None = None
    document_source_id: Reference | None = None

    @model_validator(mode="after")
    def justified(self):
        if self.document_decision:
            if self.action != "resolved" or not self.document_source_id:
                raise ValueError("La decisión documental requiere confirmar una fuente concreta.")
            if self.cited_fact_ids or self.cited_chunk_ids or self.note.strip():
                raise ValueError(
                    "La confirmación rápida utiliza la fuente y el texto fijados por el servidor."
                )
            return self
        if self.document_source_id:
            raise ValueError("Indica la decisión sobre ese documento.")
        if self.action != "open" and not self.note.strip():
            raise ValueError("Explica cómo se resolvió el pendiente o por qué no aplica.")
        if self.action == "resolved" and not (self.cited_chunk_ids or self.cited_fact_ids):
            raise ValueError("Una resolución necesita al menos una fuente o aporte citado.")
        for ids in (self.cited_chunk_ids, self.cited_fact_ids):
            if len(ids) != len(set(ids)):
                raise ValueError("Una referencia no puede estar repetida.")
        return self


class ReviewEdit(StrictModel):
    revision: int = Field(ge=1, strict=True)
    edited_by: Actor
    paragraphs: list[ReviewParagraph] = Field(max_length=30)
    pending_resolutions: list[PendingResolutionInput] = Field(default_factory=list, max_length=300)

    @field_validator("pending_resolutions")
    @classmethod
    def unique_pending(cls, value):
        if len({item.pending_id for item in value}) != len(value):
            raise ValueError("Envía una sola decisión por pendiente.")
        return value


class FactInput(StrictModel):
    revision: int = Field(ge=1, strict=True)
    text: str = Field(min_length=1, max_length=6000)
    author: Actor
    basis: str = Field(min_length=1, max_length=3000)
    observed_at: str = Field(min_length=10, max_length=10)

    @field_validator("text", "basis")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El aporte y su fundamento deben estar completos.")
        return value

    @field_validator("observed_at")
    @classmethod
    def iso_date(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Indica la fecha del conocimiento como AAAA-MM-DD.")
        date.fromisoformat(value)
        return value


class ReviewApprove(StrictModel):
    revision: int = Field(ge=1, strict=True)
    assessment_hash: InputHash
    approved_by: Actor
    note: str = Field(default="", max_length=3000)
    confirmed: StrictBool

    @field_validator("confirmed")
    @classmethod
    def explicit_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("La aprobación requiere confirmación explícita.")
        return value


class ResponseReading(StrictModel):
    content_hash: InputHash
    reviewed_by: Actor
    confirmed: StrictBool

    @field_validator("confirmed")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirma expresamente que revisaste todas las respuestas.")
        return value
