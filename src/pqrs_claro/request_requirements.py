"""Literal request components used to audit coverage, never evidence or inference."""

import re
from typing import Literal

from pydantic import Field, StrictInt

from .models import DomainError, StrictModel

PROCEDURE_SCOPE_CHECK_GUIDANCE = """
Comprueba también la unidad del procedimiento: relaciona para CADA regla su objeto,
supuesto de inicio, etapa, población, autoridad y efecto con el trámite preguntado.
Dos pasajes literales del mismo documento no autorizan a combinar sus reglas por
compartir palabras. Un paso de solicitud inicial no se vuelve requisito de revisión,
ni la autoridad de una actuación distinta complementa la competencia de la consultada.
Señala code=procedure_scope_mixing y el párrafo afectado si el texto presenta una regla
de otro supuesto como complemento, requisito o vía adicional sin respaldo para ese nexo,
aunque cada frase aislada tenga cita y el núcleo de la pregunta esté contestado.
La evaluación previa de fuentes, el plan y coverage_complete no dispensan este control.
No marques mezcla cuando el texto distingue correctamente los procedimientos y conserva
el supuesto y la autoridad de cada uno: una comparación pedida o un límite explícito
de no aplicabilidad pueden ser pertinentes. Señala la transferencia concreta que falla,
no una diferencia de vocabulario ni un control legítimo de vigencia o procedencia.
"""

REQUIREMENT_REPAIR_INSTRUCTION = (
    "Repite únicamente la comprobación con el mismo texto y fuentes. "
    "Corrige la estructura del checklist sin inventar cobertura: answered necesita "
    "párrafos con respuesta íntegra y citas suficientes; pending necesita un "
    "pendiente específico todavía abierto, no uno cerrado ni solo metadata_only. "
    "Los controles heredados de procedencia/vigencia pueden coexistir con answered "
    "si el contenido preguntado sí está respondido con el alcance correcto. "
    "Si realmente falta contenido y no hay brecha concreta abierta, usa omitted "
    "y explica lo que falta. No suprimas controles ni alteres textos o fuentes."
)

# Split structural coordination, not subject vocabulary. Keep conditions in the
# same clause; splitting every 'y' would turn a list of documents into new duties.
_BOUNDARY = re.compile(
    r";\s*|(?<=[?？])\s+(?=[¿A-ZÁÉÍÓÚ])|"
    r"\s+(?:y|e|and)\s+(?=(?:(?:con|en|ante|por|desde|hasta|a|de)\s+)?"
    r"(?:qu[eé]|cu[aá]l(?:es)?|c[oó]mo|cu[aá]ndo|qui[eé]n(?:es)?|"
    r"cu[aá]nt[oa]s?|what|which|how|when|who)\b)",
    re.IGNORECASE,
)


def build_requirements(request):
    """Preserve every character apart from separators/whitespace; no paraphrase."""
    text = str(request.get("description") or request.get("title") or "").strip()
    return [
        {"id": f"R{i}", "text": part.strip()}
        for i, part in enumerate((p for p in _BOUNDARY.split(text) if p.strip()), 1)
    ]


class RequirementCheck(StrictModel):
    requirement_id: str = Field(min_length=1, max_length=40)
    status: Literal["supported", "pending"]
    coverage_indexes: list[StrictInt] = Field(default_factory=list, max_length=20)
    missing_indexes: list[StrictInt] = Field(default_factory=list, max_length=30)
    explanation: str = Field(min_length=1, max_length=2000)


class SourceRequirementCheck(RequirementCheck):
    # Separate index space: materialized application controls never renumber the
    # model's original missing/evaluated_gaps list.
    uncertainty_indexes: list[StrictInt] = Field(default_factory=list, max_length=20)


def validate_requirement_checks(request, selection):
    """Reject unaccounted components. Semantic entailment remains an AI/human check."""
    requirements = request.get("request_requirements")
    if not requirements:
        return []  # Compatibility for external/legacy assessor adapters.
    expected = [r["id"] for r in requirements]
    checks = [
        r.model_dump() if hasattr(r, "model_dump") else r for r in selection.requirement_checks
    ]
    if (
        len(expected) != len(set(expected))
        or len(checks) != len(expected)
        or {r["requirement_id"] for r in checks} != set(expected)
    ):
        raise DomainError(
            "La evaluación debe comprobar cada inciso de la solicitud exactamente una vez."
        )
    for row in checks:
        covered, missing = row["coverage_indexes"], row["missing_indexes"]
        uncertain = row.get("uncertainty_indexes", [])
        if any(type(i) is not int or not 0 <= i < len(selection.coverage) for i in covered):
            raise DomainError("Un inciso apunta a una afirmación de cobertura que no existe.")
        if any(type(i) is not int or not 0 <= i < len(selection.missing) for i in missing):
            raise DomainError("Un inciso apunta a un pendiente que no existe.")
        uncertainties = getattr(selection, "uncertainties", [])
        if (len(uncertain) != len(set(uncertain))
                or any(type(i) is not int or not 0 <= i < len(uncertainties) for i in uncertain)):
            raise DomainError("Un inciso apunta a una incertidumbre inexistente o repetida.")
        if row["status"] == "supported" and (not covered or missing or uncertain):
            raise DomainError(
                "Un inciso respaldado necesita cobertura y no puede tener brechas sin resolver."
            )
        if row["status"] == "pending" and not (missing or uncertain):
            raise DomainError(
                "Un inciso sin resolver necesita un pendiente concreto, no solo una advertencia."
            )
        if (
            row["status"] == "pending"
            and missing
            and not uncertain
            and all(selection.missing[i].basis == "metadata_only" for i in missing)
        ):
            raise DomainError(
                "Un aviso de catálogo por sí solo no identifica el contenido que falta "
                "para un inciso. Explica la brecha concreta o comprueba su cobertura."
            )
        if not row["explanation"].strip():
            raise DomainError("Cada inciso necesita explicar su cobertura o brecha.")
    if selection.coverage_complete != all(r["status"] == "supported" for r in checks):
        raise DomainError(
            "La cobertura completa debe coincidir con la comprobación de todos los incisos."
        )
    return checks


class DraftRequirementCheck(StrictModel):
    requirement_id: str = Field(min_length=1, max_length=40)
    status: Literal["answered", "pending", "omitted"]
    paragraph_indexes: list[StrictInt] = Field(default_factory=list, max_length=20)
    pending_indexes: list[StrictInt] = Field(default_factory=list, max_length=60)
    explanation: str = Field(min_length=1, max_length=2000)


def _open_content_pending(item):
    resolution = item.get("resolution") or {}
    return (item.get("basis") != "metadata_only"
            and resolution.get("action") in {None, "open"}
            and resolution.get("status") in {None, "open"})


def draft_requirement_issues(request, review, draft):
    requirements = request.get("request_requirements")
    if not requirements:
        return []
    checks = review.get("requirement_checks", [])
    expected = {r["id"] for r in requirements}
    if len(checks) != len(requirements) or {c["requirement_id"] for c in checks} != expected:
        return [
            {
                "code": "coverage_review_incomplete",
                "paragraph_index": None,
                "description": "La comprobación no revisó todos los incisos; "
                "vuelve a comprobar la respuesta.",
            }
        ]
    issues = []
    for row in checks:
        pi, mi = row["paragraph_indexes"], row["pending_indexes"]
        valid = all(type(i) is int and 0 <= i < len(draft["paragraphs"]) for i in pi) and all(
            type(i) is int and 0 <= i < len(draft["pending"]) for i in mi
        )
        if (
            not valid
            or (row["status"] == "answered" and (not pi or mi))
            or (row["status"] == "pending" and (
                not mi or not any(_open_content_pending(draft["pending"][i]) for i in mi)))
        ):
            issues.append(
                {
                    "code": "coverage_review_invalid",
                    "paragraph_index": None,
                    "description": f"El inciso {row['requirement_id']} "
                    "no tiene vínculos de revisión válidos.",
                }
            )
        elif row["status"] == "omitted":
            literal = next(r["text"] for r in requirements if r["id"] == row["requirement_id"])
            issues.append(
                {
                    "code": "request_component_omitted",
                    "paragraph_index": None,
                    "description": "Falta responder o dejar un pendiente específico para: "
                    f"{literal}. "
                    + row["explanation"],
                }
            )
    return issues
