"""Una comprobación cerrada no puede sustituir un inciso que falta en el texto."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_review_engine import HASH, inquiry, paragraph, pending, resolution, review

from pqrs_claro.request_requirements import build_requirements, draft_requirement_issues
from pqrs_claro.review_engine import structural_checks
from pqrs_claro.review_graph import build_review_graph


def request():
    item = inquiry(description="Informe el estado histórico del trámite; explique cómo reclamar.")
    item["request_requirements"] = build_requirements(item)
    return item


def assessment():
    return {
        "status": "passed", "issues": [], "local_checks": [],
        "requirement_checks": [
            {"requirement_id": "R1", "status": "answered", "paragraph_indexes": [0],
             "pending_indexes": [], "explanation": "El párrafo describe el estado histórico."},
            {"requirement_id": "R2", "status": "pending", "paragraph_indexes": [],
             "pending_indexes": [0], "explanation": "Falta explicar cómo reclamar."},
        ],
    }


def closed_gap(action):
    return pending(
        description="Localizar procedimiento para reclamar.", basis="content_gap",
        resolution=resolution(action=action, note="Decisión documentada del gestor."),
    )


@pytest.mark.parametrize("action", ["resolved", "not_applicable"])
def test_closed_evidence_check_cannot_stand_for_an_unanswered_requirement(action):
    value = review(pending=[closed_gap(action)])
    # All legacy structural checks pass: valid resolution, citations and text.
    assert not structural_checks(value)[1]
    issues = draft_requirement_issues(request(), assessment(), value)
    assert issues, "Un control cerrado dejó pasar un inciso omitido sin texto ni pendiente abierto."


@pytest.mark.parametrize("action", ["resolved", "not_applicable"])
def test_approval_graph_rejects_closed_gap_even_when_provider_calls_it_pending(action):
    class PassingProvider:
        def assess(self, request, row):
            return assessment()

    graph = build_review_graph(PassingProvider(), InMemorySaver())
    result = graph.invoke(
        {"request": request(), "review": review(pending=[closed_gap(action)]), "input_hash": HASH},
        {"configurable": {"thread_id": f"closed-requirement-{action}"}},
    )
    assert result["assessment"]["status"] == "needs_changes"
    assert "__interrupt__" not in result
    assert result["approval"] is None


@pytest.mark.parametrize("state", [None, {"status": "open"}, {"action": "open"}])
def test_specific_open_gap_still_validly_records_incomplete_content(state):
    value = review(pending=[pending(description="Localizar cómo reclamar.",
                                   basis="content_gap", resolution=state)])
    assert not draft_requirement_issues(request(), assessment(), value)


def test_registry_resolved_check_cannot_replace_unanswered_content():
    value = review(pending=[pending(
        description="Localizar cómo reclamar.", basis="content_gap",
        resolution={"status": "resolved"},
    )])
    assert draft_requirement_issues(request(), assessment(), value)


def test_open_catalog_control_alone_cannot_replace_unanswered_content():
    value = review(pending=[pending(
        description="Revisar procedencia del documento.", basis="metadata_only",
        resolution=None,
    )])
    assert draft_requirement_issues(request(), assessment(), value)


def test_nonblocking_copy_delivery_remains_a_valid_deferred_action():
    item = inquiry(description="Faciliten copia del oficio localizado.")
    item["request_requirements"] = build_requirements(item)
    value = review(
        paragraphs=[paragraph(text="Se localizó el oficio para preparar la copia solicitada.")],
        pending=[pending(
            description="Preparar la copia localizada para su entrega tras la aprobación.",
            stage="fulfillment", blocks_approval=False, basis="explicit_fulfillment_request",
        )],
    )
    checked = {
        "status": "passed", "issues": [], "local_checks": [],
        "requirement_checks": [{
            "requirement_id": "R1", "status": "pending", "paragraph_indexes": [0],
            "pending_indexes": [0],
            "explanation": "Copia localizada; entrega posterior conservada.",
        }],
    }
    assert not draft_requirement_issues(item, checked, value)
    assert not structural_checks(value)[1]
