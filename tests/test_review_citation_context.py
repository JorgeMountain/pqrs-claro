"""La revisión conserva alcance y bloqueos al recibir navegación entre citas."""

from copy import deepcopy

from test_review_engine import fact, inquiry, paragraph, pending, review, support

from pqrs_claro.review_engine import _context, structural_checks


def test_review_context_keeps_request_years_separate_and_fact_aliases_out_of_sources():
    request = inquiry(description="Informe qué sucedió durante 2023.")
    source = support(title="Oficio 950 de 2026", quote="En 2022 el trámite estaba en revisión.")
    row = review(available_supports=[source], facts=[fact()], paragraphs=[paragraph(
        text="La solicitud pregunta por 2023. El oficio de 2026 informa sobre 2022.",
        cited_fact_ids=[fact()["id"]])])
    before = deepcopy(row)
    context, labels = _context(request, row)
    guide = context["citation_context"]
    assert row == before
    assert guide["years_in_request"] == ["2023"]
    assert guide["passages"][0]["years_in_quote"] == ["2022"]
    assert guide["passages"][0]["alias"] == "S1"
    assert "F1" in labels
    assert context["review"]["paragraphs"][0]["cited_fact_ids"] == ["F1"]
    assert context["review"]["available_supports"][0]["quote"] == source["quote"]


def test_accurate_limited_paragraph_still_requires_open_evidence_check():
    row = review(paragraphs=[paragraph(text="Según el oficio, esto no confirma "
        "la situación actual.")], pending=[pending(), pending(
        id="future-signature", kind="clarification", description="Firmar la futura respuesta.",
        stage="fulfillment", blocks_approval=False)])
    checks, issues = structural_checks(row)
    assert [item["code"] for item in issues] == ["pending_closed"]
    assert any(item["code"] == "fulfillment_deferred" and item["passed"] for item in checks)
    assert not any(item["code"] == "historical_current_fact" for item in issues)
