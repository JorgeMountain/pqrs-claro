"""Historical explanation differs from applying a rule to a present case."""

import pytest
from test_source_sufficiency import coverage, materialize, missing, request, selection, source


def normative():
    return source(category="institutional_norm", validity="unknown", title="Reglamento de talleres")


def proposed(item, **changes):
    return selection(
        [item],
        supports=[
            {"chunk_id": item["chunk_id"], "role": "rule", "reason": "Pasaje normativo solicitado."}
        ],
        coverage=[coverage(item, use="attributed_content")],
        **changes,
    )


def test_historical_norm_description_keeps_warning_but_not_unnecessary_current_validity_pending():
    item = normative()
    result = materialize(
        request("¿Qué requisitos describe el reglamento de talleres de 2021?"),
        [item],
        proposed(item),
    )
    assert result["status"] == "references_found"
    assert not result["missing"]
    assert result["warnings"]
    assert result["sufficiency"]["source_uses"][item["source_id"]] == ["attributed_content"]


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué normativa vigente regula mi inscripción?",
        "¿Puedo solicitar la inscripción este semestre?",
        "¿Qué requisitos aplican para mi caso?",
        "¿Qué requisitos debo cumplir para matricularme en 2027?",
        "¿Qué requisitos de inscripción están previstos para 2027?",
    ],
)
def test_current_application_still_requires_validity(question):
    item = normative()
    result = materialize(request(question), [item], proposed(item))
    assert result["status"] == "needs_evidence"
    assert any(m["reason_code"] == "validity" for m in result["missing"])


@pytest.mark.parametrize(
    "reason,basis",
    [
        ("transcription", "unreadable"),
        ("source_identity", "content_gap"),
        ("specific_gap", "contradiction"),
        ("provenance", "content_gap"),
    ],
)
def test_attribution_does_not_discard_material_checks(reason, basis):
    item = normative()
    result = materialize(
        request("¿Qué requisitos describe el reglamento de 2021?"),
        [item],
        proposed(item, missing=[missing(reason, basis)]),
    )
    assert result["status"] == "needs_evidence"
    assert any(m["basis"] == basis for m in result["missing"])


def test_copy_of_identified_historical_norm_does_not_require_current_legal_effect():
    from test_normative_document_requests import norm
    from test_normative_document_requests import request as copy_request
    from test_normative_document_requests import selection as copy_selection

    item = norm(validity="unknown", review_status="pending")
    result = materialize(copy_request(), [item], copy_selection(item))
    assert result["supports"][0]["role"] == "document"
    assert not any(m["reason_code"] == "provenance" for m in result["missing"])
    assert any(d["original"]["reason_code"] == "provenance" for d in result["gap_decisions"])
    assert not any(m["reason_code"] == "validity" for m in result["missing"])
    assert result["actions"][0]["resolution"]["status"] == "open"
    current = copy_request(description="Adjunte copia de la Circular 402 de 2025 vigente.")
    result = materialize(current, [item], copy_selection(item))
    assert any(m["reason_code"] == "validity" for m in result["missing"])
