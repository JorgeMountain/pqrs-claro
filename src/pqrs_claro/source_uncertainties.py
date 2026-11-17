"""Application decisions tied to literal coverage, never inferred from empty search."""

from typing import Literal

from pydantic import Field, StrictInt

from .models import DomainError, StrictModel
from .request_requirements import build_requirements


class ApplicationAssessment(StrictModel):
    status: Literal["not_requested", "supported", "unresolved"]
    explanation: str = Field(min_length=1, max_length=2000)
    uncertainty_indexes: list[StrictInt] = Field(max_length=20)


class SourceUncertainty(StrictModel):
    requirement_ids: list[str] = Field(min_length=1, max_length=64)
    coverage_indexes: list[StrictInt] = Field(min_length=1, max_length=20)
    basis: Literal["contradiction", "content_gap"]
    affected_claim: str = Field(min_length=1, max_length=2000)
    why_unresolved: str = Field(min_length=1, max_length=2000)
    required_check: str = Field(min_length=1, max_length=2000)


def validated_uncertainties(selection, request, coverage, supports, requirement_checks):
    """Validate two-way links after scope, role and literal citation validation.

    Semantic applicability is explicitly assessed, not guessed from words or dates.
    Python cannot silently lose a declared unresolved decision: every such row
    must have a specific control with authorized passages and request components.
    """
    uncertainties = [item.model_dump() for item in selection.uncertainties]
    requirements = request.get("request_requirements") or build_requirements(request)
    expected = {item["id"] for item in requirements}
    checks = {item["requirement_id"]: item for item in requirement_checks}
    index = {item["chunk_id"]: item for item in supports}
    for rid, check in checks.items():
        for position in check.get("uncertainty_indexes", []):
            row = uncertainties[position]
            if (rid not in row["requirement_ids"]
                    or not set(row["coverage_indexes"]).intersection(check["coverage_indexes"])):
                raise DomainError("El inciso y su incertidumbre deben enlazar la misma cobertura.")
    for position, row in enumerate(coverage):
        application = row["application"]
        references = application["uncertainty_indexes"]
        if not application["explanation"].strip():
            raise DomainError("La decisión de aplicabilidad necesita explicar su alcance.")
        if (len(references) != len(set(references))
                or any(type(i) is not int or not 0 <= i < len(uncertainties)
                       for i in references)):
            raise DomainError(
                "La aplicabilidad referencia una incertidumbre inexistente o repetida.")
        if (application["status"] == "unresolved") != bool(references):
            raise DomainError("Cada aplicabilidad sin resolver necesita un control específico.")
        if any(position not in uncertainties[i]["coverage_indexes"] for i in references):
            raise DomainError(
                "La aplicabilidad y su incertidumbre deben enlazar la misma cobertura.")
    validated = []
    for position, row in enumerate(uncertainties):
        component_ids, covered = row["requirement_ids"], row["coverage_indexes"]
        if (len(component_ids) != len(set(component_ids))
                or not set(component_ids).issubset(expected)):
            raise DomainError("La incertidumbre debe identificar incisos reales sin repetirlos.")
        if (len(covered) != len(set(covered))
                or any(type(i) is not int or not 0 <= i < len(coverage) for i in covered)):
            raise DomainError("La incertidumbre referencia cobertura inexistente o repetida.")
        if any(not row[key].strip() for key in
               ("affected_claim", "why_unresolved", "required_check")):
            raise DomainError("La incertidumbre debe explicar la afirmación, la duda y su cotejo.")
        if any(coverage[i]["application"]["status"] != "unresolved"
               or position not in coverage[i]["application"]["uncertainty_indexes"]
               for i in covered):
            raise DomainError(
                "La incertidumbre debe conservar su decisión de aplicabilidad abierta.")
        if checks and any(not set(covered).intersection(checks[rid]["coverage_indexes"])
                          for rid in component_ids):
            raise DomainError("La incertidumbre no está vinculada a la cobertura de su inciso.")
        if checks and any(checks[rid]["status"] == "pending"
                          and position not in checks[rid].get("uncertainty_indexes", [])
                          for rid in component_ids):
            raise DomainError("El inciso pendiente debe enlazar su incertidumbre sin duplicarla.")
        if checks and not set(covered).issubset({i for rid in component_ids
                                               for i in checks[rid]["coverage_indexes"]}):
            raise DomainError(
                "La incertidumbre incorpora cobertura de otros incisos no vinculados.")
        passages = list(dict.fromkeys(
            (citation["chunk_id"], citation["quote"])
            for i in covered for citation in coverage[i]["citations"]
        ))
        if row["basis"] == "contradiction" and len(passages) < 2:
            raise DomainError("Una contradicción necesita al menos dos pasajes contrastados.")
        validated.append({
            **row,
            "passages": [{"chunk_id": cid, "quote": quote,
                          "source_id": index[cid]["source_id"], "role": index[cid]["role"]}
                         for cid, quote in passages],
        })
    return validated


def uncertainty_pending(uncertainties):
    """Keep declared applicability unresolved even when the model's missing is empty."""
    return [{
        "kind": "clarification", "reason_code": "applicability", "stage": "evidence",
        "basis": item["basis"], "description": item["required_check"],
        "affected_claim": item["affected_claim"], "why_unresolved": item["why_unresolved"],
        "requirement_ids": item["requirement_ids"], "coverage_indexes": item["coverage_indexes"],
        "linked_chunk_ids": list(dict.fromkeys(p["chunk_id"] for p in item["passages"])),
        "linked_source_ids": list(dict.fromkeys(p["source_id"] for p in item["passages"])),
    } for item in uncertainties]
