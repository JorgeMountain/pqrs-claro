"""La cobertura orienta el contenido atribuido; no resuelve ni aprueba por sí sola."""

import json
from copy import deepcopy

import pytest
from test_draft_engine import (
    engine as draft_engine,
)
from test_draft_engine import (
    finding,
    inquiry,
    proposed_check,
    proposed_draft,
    proposed_plan,
    support,
)
from test_review_engine import (
    engine as review_engine,
)
from test_review_engine import (
    inquiry as review_inquiry,
)
from test_review_engine import (
    issue,
    paragraph,
    pending,
    provider_result,
    review,
)
from test_review_engine import (
    support as review_support,
)

from pqrs_claro.draft_engine import aliased_sufficiency
from pqrs_claro.models import DomainError
from pqrs_claro.review_engine import _context, structural_checks, validate_review_input


def test_source_snapshot_links_to_current_resolution_without_rewriting_history():
    value = review(pending=[pending(resolution={
        "action": "not_applicable", "note": "La pregunta pide contenido histórico atribuido.",
        "cited_chunk_ids": [review_support()["chunk_id"]], "cited_fact_ids": [],
        "by": "Revisor ficticio", "at": "2026-09-10T12:00:00+00:00",
    })], source_checks=[{"id": "pending-1", "state": "confirmation_pending",
                         "resolution": {"status": "open"}}])
    original = deepcopy(value)
    body, _ = _context(review_inquiry(), value)
    assert body["review"]["source_checks"] == original["source_checks"]
    assert body["review"]["source_check_review_links"] == [{
        "source_check_id": "pending-1", "current_pending_alias": "M1",
        "source_state_is_historical": True,
    }]
    assert body["review"]["pending"][0]["resolution"]["action"] == "not_applicable"
    assert value == original


def test_historical_resolved_check_does_not_close_current_open_pending():
    value = review(pending=[pending()], source_checks=[{
        "id": "pending-1", "resolution": {"status": "resolved"},
    }])
    body, _ = _context(review_inquiry(), value)
    assert body["review"]["pending"][0]["resolution"] is None
    _, issues = structural_checks(validate_review_input(review_inquiry(), value))
    assert issues


def coverage(source, *, complete=True, use="attributed_content"):
    return {
        "policy_version": 1,
        "coverage_complete": complete,
        "coverage": [{
            "aspect": "Contenido de la respuesta anterior",
            "claim": source["quote"],
            "use": use,
            "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
            "explanation": "El pasaje permite describir lo informado en el oficio.",
        }],
        "source_uses": {source["source_id"]: [use]},
    }


def unknown_source(factory=support):
    return factory(
        document_status="unknown", review_status="pending", verification_status="pending"
    )


def test_coverage_aliases_only_available_passages_and_preserves_the_original_map():
    selected = unknown_source()
    value = coverage(selected)
    value["coverage"][0]["citations"].append({"chunk_id": "not-selected", "quote": "Otro texto."})
    before = deepcopy(value)
    result = aliased_sufficiency(value, {selected["chunk_id"]: "S1"})
    assert result["coverage"][0]["citations"] == [
        {"chunk_id": "S1", "quote": selected["quote"]},
        {"chunk_id": "not-selected", "quote": "Otro texto."},
    ]
    assert result["source_uses"] == value["source_uses"]
    assert value == before
    assert aliased_sufficiency(None, {}) is None


def test_draft_stages_receive_coverage_without_turning_unknown_metadata_into_pending():
    selected = unknown_source()
    value = finding(status="references_found", supports=[selected], missing=[],
                    sufficiency=coverage(selected))
    before = deepcopy(value)
    worker, calls = draft_engine(proposed_plan(), proposed_draft(), proposed_check())
    plan = worker.plan(inquiry(), value)
    draft = worker.write(inquiry(), value, plan)
    checked = worker.check(inquiry(), value, plan, draft)
    assert draft["pending"] == []
    assert draft["status"] == "needs_review"
    assert checked["status"] == "passed"
    assert "approved" not in draft
    for call in calls:
        payload = json.loads(call["input"])
        assert payload["finding"]["sufficiency"] == aliased_sufficiency(
            value["sufficiency"], {selected["chunk_id"]: "S1"}
        )
        assert payload["finding"]["supports"][0]["document_status"] == "unknown"
        assert payload["finding"]["supports"][0]["verification_status"] == "pending"
    assert value == before


def test_review_transports_coverage_but_keeps_text_and_metadata_unchanged():
    selected = unknown_source(review_support)
    value = review(available_supports=[selected], sufficiency=coverage(selected))
    before = deepcopy(value)
    worker, calls = review_engine()
    result = worker.assess(review_inquiry(), value)
    assert result["status"] == "passed"
    assert value == before
    payload = json.loads(calls[0]["input"])["review"]
    assert payload["sufficiency"] == aliased_sufficiency(
        value["sufficiency"], {selected["chunk_id"]: "S1"}
    )
    assert payload["paragraphs"][0]["text"] == value["paragraphs"][0]["text"]
    assert payload["paragraphs"][0]["cited_chunk_ids"] == ["S1"]
    assert payload["available_supports"][0]["document_status"] == "unknown"


@pytest.mark.parametrize("complete", [False, True])
def test_coverage_cannot_close_an_existing_current_fact_check(complete):
    selected = unknown_source(review_support)
    control = pending(
        description="Confirmar si el trámite sigue abierto en la fecha consultada.",
        affected_claim="El trámite sigue abierto en la fecha consultada.",
        why_unresolved="El oficio solo informa un estado anterior.",
    )
    value = review(available_supports=[selected], pending=[control],
                   sufficiency=coverage(selected, complete=complete))
    before = deepcopy(value)
    worker, calls = review_engine()
    result = worker.assess(review_inquiry(), value)
    assert result["status"] == "needs_changes"
    assert any(item["code"] == "pending_closed" for item in result["issues"])
    payload = json.loads(calls[0]["input"])["review"]
    assert payload["pending"][0]["resolution"] is None
    assert payload["pending"][0]["affected_claim"] == control["affected_claim"]
    assert payload["pending"][0]["why_unresolved"] == control["why_unresolved"]
    assert value == before


def test_coverage_does_not_reopen_a_resolved_check_referenced_by_the_redactor():
    selected = unknown_source()
    control = {
        "kind": "clarification", "description": "Cotejar el contenido citado del oficio.",
        "check_key": "confirmed-content", "stage": "evidence",
        "resolution": {"status": "resolved", "note": "Cotejo ficticio ya registrado."},
    }
    value = finding(status="references_found", supports=[selected], missing=[],
                    checks=[control], sufficiency=coverage(selected))
    proposal = proposed_draft()
    proposal["pending"] = [{"kind": "clarification", "description": control["description"],
                            "existing_check_keys": [control["check_key"]]}]
    before = deepcopy(value)
    worker, _ = draft_engine(proposed_plan(), proposal)
    plan = worker.plan(inquiry(), value)
    result = worker.write(inquiry(), value, plan)
    assert result["pending"] == []
    assert value == before


@pytest.mark.parametrize("code, description", [
    ("current_fact", "S1 describe un estado anterior y no acredita el estado actual afirmado."),
    ("content_conflict", "El párrafo dice cerrado, pero S1 indica un trámite en revisión."),
    ("requested_document", "S1 menciona un acta; no sustituye la copia del acta solicitada."),
    ("official_status", "S1 no respalda la afirmación de que el oficio fue expedido oficialmente."),
])
def test_coverage_never_suppresses_concrete_provider_findings(code, description):
    selected = unknown_source(review_support)
    value = review(available_supports=[selected], sufficiency=coverage(selected))
    worker, _ = review_engine(provider_result(
        status="needs_changes", issues=[issue(code=code, description=description)]
    ))
    result = worker.assess(review_inquiry(), value)
    assert result["status"] == "needs_changes"
    assert any(item["code"] == code for item in result["issues"])


@pytest.mark.parametrize("cited", [[], ["retired-source"]])
def test_paragraph_citations_cannot_be_filled_silently_from_coverage(cited):
    selected = unknown_source(review_support)
    value = review(available_supports=[selected], sufficiency=coverage(selected),
                   paragraphs=[paragraph(cited_chunk_ids=cited)])
    worker, calls = review_engine()
    result = worker.assess(review_inquiry(), value)
    assert result["status"] == "needs_changes"
    assert calls == []


def test_metadata_only_repair_can_leave_correct_attributed_content_intact():
    selected = unknown_source()
    value = finding(status="references_found", supports=[selected], missing=[],
                    sufficiency=coverage(selected))
    worker, calls = draft_engine(proposed_plan(), proposed_draft(), {"paragraphs": []})
    plan = worker.plan(inquiry(), value)
    draft = worker.write(inquiry(), value, plan)
    before = deepcopy(draft)
    result = worker.repair(inquiry(), value, plan, draft, {
        "status": "needs_changes", "issues": [{"code": "generic_provenance", "paragraph_index": 0,
        "description": "Comprobar la procedencia solo porque document_status es unknown."}],
    })
    assert result == before
    payload = json.loads(calls[-1]["input"])
    assert payload["repair_targets"] == [0]
    assert payload["finding"]["sufficiency"]["coverage_complete"] is True
    assert payload["finding"]["sufficiency"]["coverage"][0]["use"] == "attributed_content"


def test_coverage_of_attributed_content_does_not_excuse_current_claim_locally():
    selected = unknown_source()
    value = finding(status="references_found", supports=[selected], missing=[],
                    sufficiency=coverage(selected))
    worker, _ = draft_engine(proposed_plan(), proposed_draft(
        text="El comité informó la aprobación en el Oficio 0123 de 2024. "
        "Actualmente la plaza está aprobada."
    ), proposed_check())
    plan = worker.plan(inquiry(), value)
    draft = worker.write(inquiry(), value, plan)
    result = worker.check(inquiry(), value, plan, draft)
    assert result["status"] == "needs_changes"
    assert any(issue["code"] == "historical_current_fact" for issue in result["issues"])


def test_new_concrete_pending_preserves_explanations_and_materializes_known_aliases():
    selected = unknown_source()
    value = finding(status="references_found", supports=[selected], missing=[],
                    sufficiency=coverage(selected))
    proposal = proposed_draft()
    proposal["pending"] = [{
        "kind": "fact", "description": "Confirmar el estado actual del trámite.",
        "difference": "S1 informa un estado anterior, no el actual.",
        "affected_claim": "El estado informado en S1 continúa vigente.",
        "why_unresolved": "S1 no informa el estado en la fecha de la nueva consulta.",
        "basis": "content_gap",
    }]
    before = deepcopy(value)
    worker, calls = draft_engine(proposed_plan(), proposal)
    plan = worker.plan(inquiry(), value)
    result = worker.write(inquiry(), value, plan)
    assert result["status"] == "needs_evidence"
    assert len(result["pending"]) == 1
    control = result["pending"][0]
    assert control["basis"] == "content_gap"
    assert control["resolution"]["status"] == "open"
    for field in ("difference", "affected_claim", "why_unresolved"):
        assert "S1" not in control[field]
        assert selected["title"] in control[field]
    assert value == before
    assert len(calls) == 2


def test_legacy_pending_proposal_keeps_compatible_explanation_defaults():
    value = finding(status="references_found", missing=[])
    proposal = proposed_draft()
    proposal["pending"] = [{
        "kind": "fact", "description": "Confirmar el estado actual del trámite.",
    }]
    worker, _ = draft_engine(proposed_plan(), proposal)
    plan = worker.plan(inquiry(), value)
    control = worker.write(inquiry(), value, plan)["pending"][0]
    assert control["affected_claim"] == ""
    assert control["why_unresolved"] == ""
    assert control["basis"] == "unspecified"


@pytest.mark.parametrize("field", ["affected_claim", "why_unresolved"])
def test_pending_explanations_reject_unknown_source_aliases(field):
    value = finding(status="references_found", missing=[])
    proposal = proposed_draft()
    proposal["pending"] = [{
        "kind": "fact", "description": "Confirmar el estado actual del trámite.",
        field: "El contenido de S99 no permite confirmar el estado actual.",
        "basis": "content_gap",
    }]
    worker, calls = draft_engine(proposed_plan(), proposal)
    plan = worker.plan(inquiry(), value)
    with pytest.raises(DomainError, match="alias de fuente desconocido"):
        worker.write(inquiry(), value, plan)
    assert len(calls) == 2


def test_pending_basis_rejects_an_unknown_category_without_accepting_the_draft():
    value = finding(status="references_found", missing=[])
    proposal = proposed_draft()
    proposal["pending"] = [{
        "kind": "fact", "description": "Confirmar el estado actual del trámite.",
        "basis": "automatically_verified",
    }]
    worker, calls = draft_engine(proposed_plan(), proposal)
    plan = worker.plan(inquiry(), value)
    with pytest.raises(DomainError, match="borrador incompleto"):
        worker.write(inquiry(), value, plan)
    assert len(calls) == 2
