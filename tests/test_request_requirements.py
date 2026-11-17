"""General coverage checks: literal components and explicit unresolved content."""

from copy import deepcopy

import pytest
from test_source_sufficiency import materialize, missing, request, selection

from pqrs_claro.models import DomainError
from pqrs_claro.request_requirements import (
    build_requirements,
    draft_requirement_issues,
    validate_requirement_checks,
)


def inquiry():
    value = request("¿Qué requisitos tiene el subsidio rural y cómo se solicita la revisión?")
    value["request_requirements"] = build_requirements(value)
    return value


def checked_selection(**changes):
    return selection(
        requirement_checks=[
            {
                "requirement_id": "R1",
                "status": "supported",
                "coverage_indexes": [0],
                "missing_indexes": [],
                "explanation": "El pasaje enumera los requisitos.",
            },
            {
                "requirement_id": "R2",
                "status": "pending",
                "coverage_indexes": [],
                "missing_indexes": [0],
                "explanation": "Falta el procedimiento de revisión.",
            },
        ],
        coverage_complete=False,
        missing=[
            missing(
                reason="specific_gap",
                basis="content_gap",
                description="Localizar el procedimiento de revisión del subsidio rural.",
            )
        ],
        **changes,
    )


def test_components_are_literal_and_do_not_turn_document_lists_into_delivery():
    text = ("Indique formulario y constancia exigidos; "
            "cómo solicitar revisión y ante quién presentarla.")
    assert build_requirements({"description": text}) == [
        {"id": "R1", "text": "Indique formulario y constancia exigidos"},
        {"id": "R2", "text": "cómo solicitar revisión"},
        {"id": "R3", "text": "ante quién presentarla."},
    ]
    assert build_requirements({"title": "¿Qué plazo existe? ¿Cómo se reclama?"}) == [
        {"id": "R1", "text": "¿Qué plazo existe?"},
        {"id": "R2", "text": "¿Cómo se reclama?"},
    ]


def test_explicit_partial_coverage_keeps_specific_pending():
    result = materialize(inquiry(), proposed=checked_selection())
    assert result["status"] == "needs_evidence"
    assert result["sufficiency"]["requirement_checks"][1]["status"] == "pending"
    assert "procedimiento de revisión" in result["missing"][0]["description"]


@pytest.mark.parametrize(
    "failure",
    [
        "omitted",
        "duplicate",
        "unknown",
        "bad_coverage",
        "bad_pending",
        "no_pending",
        "false_complete",
    ],
)
def test_unaccounted_request_is_rejected_not_declared_document_missing(failure):
    value = checked_selection()
    if failure == "omitted":
        value.requirement_checks.pop()
    elif failure == "duplicate":
        value.requirement_checks[1].requirement_id = "R1"
    elif failure == "unknown":
        value.requirement_checks[1].requirement_id = "R3"
    elif failure == "bad_coverage":
        value.requirement_checks[0].coverage_indexes = [99]
    elif failure == "bad_pending":
        value.requirement_checks[1].missing_indexes = [-1]
    elif failure == "no_pending":
        value.requirement_checks[1].missing_indexes = []
    else:
        value.coverage_complete = True
    before = value.model_dump()
    with pytest.raises(DomainError):
        validate_requirement_checks(inquiry(), value)
    assert value.model_dump() == before


def test_draft_omitted_component_blocks_even_if_metadata_check_exists():
    draft = {
        "paragraphs": [{"text": "Requisitos atribuidos al reglamento."}],
        "pending": [{"description": "Comprobar procedencia del reglamento."}],
    }
    review = {
        "requirement_checks": [
            {
                "requirement_id": "R1",
                "status": "answered",
                "paragraph_indexes": [0],
                "pending_indexes": [],
                "explanation": "Requisitos explicados.",
            },
            {
                "requirement_id": "R2",
                "status": "omitted",
                "paragraph_indexes": [],
                "pending_indexes": [],
                "explanation": "No explica cómo solicitar revisión.",
            },
        ]
    }
    issues = draft_requirement_issues(inquiry(), review, draft)
    assert [i["code"] for i in issues] == ["request_component_omitted"]
    assert "cómo se solicita la revisión" in issues[0]["description"]
    partial = deepcopy(review)
    partial["requirement_checks"].pop()
    assert (
        draft_requirement_issues(inquiry(), partial, draft)[0]["code"]
        == "coverage_review_incomplete"
    )


def test_catalog_warning_cannot_substitute_a_specific_unresolved_component():
    value = checked_selection()
    value.missing[0].basis = "metadata_only"
    value.missing[0].reason_code = "provenance"
    with pytest.raises(DomainError, match="aviso de catálogo"):
        validate_requirement_checks(inquiry(), value)


def test_draft_specific_unresolved_component_is_valid_but_not_marked_answered():
    draft = {
        "paragraphs": [{"text": "Requisitos atribuidos al reglamento."}],
        "pending": [{"description": "Localizar procedimiento de revisión."}],
    }
    checks = [
        {
            "requirement_id": "R1",
            "status": "answered",
            "paragraph_indexes": [0],
            "pending_indexes": [],
            "explanation": "Requisitos explicados.",
        },
        {
            "requirement_id": "R2",
            "status": "pending",
            "paragraph_indexes": [],
            "pending_indexes": [0],
            "explanation": "Falta el procedimiento.",
        },
    ]
    assert not draft_requirement_issues(inquiry(), {"requirement_checks": checks}, draft)
    checks[1]["pending_indexes"] = [1]
    assert (
        draft_requirement_issues(inquiry(), {"requirement_checks": checks}, draft)[0]["code"]
        == "coverage_review_invalid"
    )
