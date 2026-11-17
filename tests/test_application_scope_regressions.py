"""Independent polarity controls; fictitious sources and no provider calls."""

import pytest
from test_normative_attribution import normative, proposed
from test_normative_document_requests import norm
from test_normative_document_requests import request as copy_request
from test_normative_document_requests import selection as copy_selection
from test_source_sufficiency import materialize, missing, request

from pqrs_claro.source_sufficiency import _requests_current_application


@pytest.mark.parametrize("scope", [
    "No determinen cuál se aplica hoy.",
    "No solicito que determinen si está vigente.",
    "No se establezca si me corresponde actualmente.",
    "Sin decidir si puedo solicitarlo este semestre.",
])
def test_explicit_scope_exclusion_does_not_invent_a_current_application(scope):
    inquiry = request("Describa el contenido del reglamento de 2021. " + scope)
    item = normative()
    result = materialize(inquiry, [item], proposed(item))
    assert not _requests_current_application(inquiry)
    assert not any(gap["reason_code"] == "validity" for gap in result["missing"])
    assert result["supports"][0]["quote"] == item["quote"]


@pytest.mark.parametrize("scope", [
    "¿No se aplica hoy el reglamento?",
    "¿Por qué no determinaron cuál estaba vigente y cuál se aplica hoy?",
    "No determinen cuál regía antes; indiquen qué norma está vigente hoy.",
    "No determinen cuál regía antes, pero indiquen qué norma está vigente hoy.",
    "No determinen cuál regía antes y confirmen qué norma está vigente hoy.",
    "No determinen cuál regía antes, aclaren qué norma está vigente hoy.",
    "No determinen cuál regía antes, ¿qué norma está vigente hoy?",
])
def test_negative_fact_question_and_later_positive_scope_keep_validity(scope):
    inquiry = request("Describa el contenido del reglamento. " + scope)
    item = normative()
    result = materialize(inquiry, [item], proposed(item))
    assert _requests_current_application(inquiry)
    assert any(gap["reason_code"] == "validity" for gap in result["missing"])


@pytest.mark.parametrize("reason,basis", [
    ("provenance", "content_gap"),
    ("transcription", "unreadable"),
    ("specific_gap", "contradiction"),
])
def test_excluded_application_cannot_discard_material_content_controls(reason, basis):
    inquiry = request(
        "Describa el contenido del reglamento de 2021. No determinen cuál se aplica hoy."
    )
    item = normative()
    gap = missing(reason, basis)
    if basis == "contradiction":
        gap.update(
            description="Los pasajes indican dos plazos incompatibles para la inscripción.",
            affected_claim="El plazo de inscripción es de cinco u ocho días.",
            why_unresolved="Los dos pasajes no permiten elegir un único plazo.",
        )
    result = materialize(
        inquiry, [item], proposed(item, missing=[gap])
    )
    # Generic model gaps are normalized by evidence_contract._reason; preserve
    # the material control and its original evaluation, not its generic label.
    normalized_reason = "fact_confirmation" if reason == "specific_gap" else reason
    assert any(control["reason_code"] == normalized_reason and control["basis"] == basis
               and control["blocks_approval"] and control["resolution"]["status"] == "open"
               for control in result["missing"])
    assert result["sufficiency"]["evaluated_gaps"][0]["description"] == gap["description"]
    assert result["sufficiency"]["evaluated_gaps"][0]["reason_code"] == reason
    assert result["status"] == "needs_evidence"


def test_excluded_application_preserves_copy_and_open_delivery_without_generic_authentication():
    item = norm(validity="unknown", review_status="pending")
    inquiry = copy_request(description=(
        "Adjunte copia de la Circular 402 de 2025. No determinen cuál se aplica hoy."
    ))
    result = materialize(inquiry, [item], copy_selection(item))
    assert result["missing"] == []
    assert any(d["original"]["reason_code"] == "provenance" for d in result["gap_decisions"])
    assert result["supports"][0]["role"] == "document"
    assert result["supports"][0]["quote"] == item["quote"]
    assert result["actions"][0]["reason_code"] == "document_delivery"
    assert result["actions"][0]["resolution"]["status"] == "open"


@pytest.mark.parametrize("description", [
    "Adjunte copia certificada de la Circular 402 de 2025. "
    "No determinen cuál se aplica hoy.",
    "Adjunte copia de la Circular 402 de 2025 y certifiquen su autenticidad. "
    "No determinen cuál se aplica hoy.",
])
def test_explicit_certification_is_not_removed_by_excluded_application(description):
    item = norm(validity="unknown", review_status="pending")
    result = materialize(copy_request(description=description), [item], copy_selection(item))
    assert not result["sufficiency"]["copy_without_current_application"]
    assert any(gap["reason_code"] == "provenance" for gap in result["missing"])
    assert result["actions"]
