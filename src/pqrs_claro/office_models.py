"""Datos explícitos para preparar un oficio a partir de respuestas aprobadas."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from .models import StrictModel

MAX_OFFICE_CHARS = 600000
MAX_OFFICE_PAGES = 200
MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


def xml_text(value: str) -> str:
    """Conserva Unicode; no sustituye caracteres del contenido aprobado."""
    if not isinstance(value, str):
        raise ValueError("El contenido del oficio debe ser texto.")
    for character in value:
        point = ord(character)
        if not (
            point in (9, 10, 13)
            or 0x20 <= point <= 0xD7FF
            or 0xE000 <= point <= 0xFFFD
            or 0x10000 <= point <= 0x10FFFF
        ):
            raise ValueError(
                f"El texto contiene el carácter U+{point:04X}, incompatible con Word. "
                "Corrige el dato o revisa de nuevo la respuesta; no se sustituirá silenciosamente."
            )
    return value


class OfficeMetadata(StrictModel):
    institution: str = Field(min_length=1, max_length=200)
    department: str = Field(default="", max_length=200)
    city: str = Field(min_length=1, max_length=120)
    issue_date: date
    received_date: date | None = None
    office_number: str = Field(default="", max_length=100)
    petition_number: str = Field(default="", max_length=100)
    recipient: str = Field(min_length=1, max_length=300)
    recipient_contact: str = Field(default="", max_length=300)
    subject: str = Field(min_length=1, max_length=500)
    signer_name: str = Field(min_length=1, max_length=200)
    signer_role: str = Field(min_length=1, max_length=200)
    introduction: str = Field(default="", max_length=6000)
    salutation: str = Field(default="Cordial saludo.", min_length=1, max_length=300)
    closing: str = Field(default="Atentamente,", min_length=1, max_length=300)

    @field_validator("*", mode="before")
    @classmethod
    def text_fields(cls, value):
        if isinstance(value, str):
            return xml_text(value).strip()
        return value

    @field_validator("received_date", mode="before")
    @classmethod
    def optional_received_date(cls, value):
        return None if value == "" else value


class OfficeInput(StrictModel):
    approval_snapshot_hash: Hash
    metadata: OfficeMetadata
    attachment_source_ids: list[str] = Field(default_factory=list, max_length=20)
    prepared_by: str = Field(min_length=1, max_length=240)

    @field_validator("prepared_by", mode="before")
    @classmethod
    def actor(cls, value):
        return xml_text(value).strip()

    @field_validator("attachment_source_ids")
    @classmethod
    def attachment_ids(cls, values):
        if len(values) != len(set(values)) or any(
            not value.strip() or len(value) > 100 for value in values
        ):
            raise ValueError("Selecciona como máximo 20 anexos diferentes de la lista disponible.")
        return values


class OfficeGenerate(OfficeInput):
    preview_hash: Hash
