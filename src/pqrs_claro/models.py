"""Datos del expediente y comprobaciones que nunca se delegan a la IA."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 40
MAX_TEXT_CHARS = 120_000


class DomainError(ValueError):
    """Problema recuperable que la interfaz puede explicar en español."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(StrictModel):
    number: int = Field(ge=1)
    text: str
    method: Literal["native", "ocr"]
    needs_review: bool


class SourceRef(StrictModel):
    page: int = Field(ge=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=1)


class Request(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^P[1-9][0-9]*$")
    label: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=8000)
    parent_id: str | None = None
    source_refs: list[SourceRef] = Field(min_length=1, max_length=80)


class Identification(StrictModel):
    subject: str = Field(min_length=1, max_length=500)
    requester: str | None = Field(default=None, max_length=500)
    document_date: str | None = Field(default=None, max_length=200)
    requests: list[Request] = Field(min_length=1, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)


def validate_pages(pages: list[Page]) -> None:
    """Comprueba límites completos: ningún documento se recorta silenciosamente."""
    if not pages or len(pages) > MAX_PAGES:
        raise DomainError(f"El documento debe tener entre 1 y {MAX_PAGES} páginas.")
    if [page.number for page in pages] != list(range(1, len(pages) + 1)):
        raise DomainError("Las páginas deben estar numeradas en orden, desde 1 y sin saltos.")
    if sum(len(page.text) for page in pages) > MAX_TEXT_CHARS:
        raise DomainError("El documento supera el límite de 120.000 caracteres de texto.")
    if not any(page.text.strip() for page in pages):
        raise DomainError("El documento no contiene texto legible para identificar solicitudes.")


def source_quote(pages: list[Page], page: int, line_start: int, line_end: int) -> str:
    """Recupera líneas originales con numeración inclusiva, empezando en uno."""
    source = next((item for item in pages if item.number == page), None)
    if source is None:
        raise DomainError(f"La referencia apunta a la página {page}, que no existe.")
    lines = source.text.splitlines()
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        raise DomainError(f"El rango de líneas de la página {page} no es válido.")
    quote = "\n".join(lines[line_start - 1 : line_end])
    if not quote.strip():
        raise DomainError(f"La referencia de la página {page} solo contiene líneas vacías.")
    return quote


def validate_identification(identification: Identification, pages: list[Page]) -> None:
    """Valida citas literales y jerarquía antes de guardar o confirmar una versión."""
    validate_pages(pages)
    if not identification.subject.strip() or not identification.requests:
        raise DomainError("Debe existir un asunto y al menos una solicitud.")
    requests = identification.requests
    ids = [request.id for request in requests]
    if len(ids) != len(set(ids)):
        raise DomainError("Cada solicitud debe tener un identificador único.")
    positions = {request_id: position for position, request_id in enumerate(ids)}
    parents = {request.id: request.parent_id for request in requests}
    for request in requests:
        if not all(value.strip() for value in (request.label, request.title, request.description)):
            raise DomainError(f"Completa el rótulo, título y descripción de {request.id}.")
        if not request.source_refs:
            raise DomainError(f"La solicitud {request.id} necesita al menos una referencia.")
        if request.parent_id is not None and request.parent_id not in positions:
            raise DomainError(f"El padre de {request.id} no existe en las solicitudes.")
        visited: set[str] = set()
        cursor: str | None = request.id
        while cursor is not None:
            if cursor in visited:
                raise DomainError("Las relaciones entre solicitudes contienen un ciclo.")
            visited.add(cursor)
            cursor = parents.get(cursor)
        if request.parent_id and positions[request.parent_id] >= positions[request.id]:
            raise DomainError(f"La solicitud padre debe aparecer antes de {request.id}.")
        for ref in request.source_refs:
            original = source_quote(pages, ref.page, ref.line_start, ref.line_end)
            if ref.quote != original:
                raise DomainError(f"La cita de {request.id} no coincide con las líneas originales.")
