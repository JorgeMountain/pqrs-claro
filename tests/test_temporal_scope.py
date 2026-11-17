"""Bounded temporal repairs with simulated model outputs, never semantic API claims."""

import json
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_draft_engine import engine, finding, inquiry, proposed_check, support

from pqrs_claro.draft_graph import build_draft_graph
from pqrs_claro.request_intent import TEMPORAL_SCOPE_GUIDANCE


def temporal_inputs(source_text, text):
    request = inquiry(
        title="Estado y publicación del resultado",
        description="Indique el estado, la fecha y el lugar previstos para publicar el resultado."
                    " Comprueben el resultado cuando esté disponible.",
    )
    source = support(title="Aviso de revisión técnica", filename="aviso.pdf",
                     quote=source_text, category="historical_attachment",
                     role="historical_evidence")
    found = finding(supports=[source], missing=[{
        "kind": "fact", "reason_code": "requested_followup", "stage": "fulfillment",
        "description": "Comprobar el resultado anunciado cuando esté disponible.",
        "affected_claim": "La comprobación del resultado anunciado.",
        "why_unresolved": "La comprobación solicitada se realizará cuando exista el resultado.",
        "basis": "content_gap", "linked_chunk_ids": [source["chunk_id"]],
    }])
    plan = {"objective": "Explicar el estado y las previsiones con su alcance documental.",
            "points": [{"description": "Conservar el estado, fecha, lugar y condición.",
                        "cited_chunk_ids": ["S1"]}]}
    draft = {"paragraphs": [{"text": text, "cited_chunk_ids": ["S1"]}], "pending": []}
    return request, found, plan, draft


def temporal_issue():
    return {"code": "unsupported_temporal_implication", "paragraph_index": 0,
            "description": "El texto presupone un resultado obtenido que el pasaje solo anuncia."}


@pytest.mark.parametrize("source_text,before_text,after_text", [
    (
        "La revisión está en curso. El resultado se publicará el jueves en el tablero técnico.",
        "Según el aviso, la revisión está en curso, pero no se conoce cuál fue el resultado. "
        "Se publicará el jueves en el tablero técnico.",
        "Según el aviso, la revisión está en curso y el documento no informa el resultado. "
        "Anuncia su publicación para el jueves en el tablero técnico.",
    ),
    (
        "La revisión se realizará si la sala queda habilitada. El resultado se publicará "
        "el jueves en el tablero técnico, si se completa la revisión.",
        "Según el aviso, no se conoce cuál fue el resultado de la revisión. "
        "Se publicará el jueves en el tablero técnico si se completa la revisión.",
        "Según el aviso, la revisión se realizará si la sala queda habilitada. "
        "Prevé publicar el resultado el jueves en el tablero técnico, si se completa "
        "la revisión; el documento no informa un resultado obtenido.",
    ),
])
def test_first_temporal_issue_reaches_one_bounded_repair_with_controls_and_details_preserved(
    source_text, before_text, after_text,
):
    request, found, plan, proposal = temporal_inputs(source_text, before_text)
    original = deepcopy((request, found))
    failed = proposed_check(status="needs_changes", issues=[temporal_issue()])
    worker, calls = engine(plan, proposal, failed, {"paragraphs": [{
        "paragraph_index": 0, "text": after_text, "cited_chunk_ids": ["S1"],
    }]}, proposed_check())
    result = build_draft_graph(worker, InMemorySaver()).invoke(
        {"request": request, "finding": found},
        {"configurable": {"thread_id": "temporal-bounded"}},
    )
    assert len(calls) == 5 and result["repair"]["attempts"] == 1
    assert result["checks"]["status"] == "passed"
    assert result["draft"]["paragraphs"][0]["text"] == after_text
    assert result["draft"]["paragraphs"][0]["cited_chunk_ids"] == [found["supports"][0]["chunk_id"]]
    assert result["draft"]["pending"] == result["repair"]["before_draft"]["pending"]
    assert any(p["reason_code"] == "requested_followup" for p in result["draft"]["pending"])
    assert (request, found) == original
    payload = json.loads(calls[3]["input"])
    assert payload["repair_targets"] == [0] and payload["repair_issues"] == [temporal_issue()]
    assert all(TEMPORAL_SCOPE_GUIDANCE in call["instructions"] for call in calls)
    assert "unsupported_temporal_implication" in calls[3]["instructions"]
    assert "pending" not in calls[3]["text_format"].model_fields


@pytest.mark.parametrize("source_text,text", [
    (
        "La revisión está en curso y el documento no informa el resultado.",
        "Según el aviso, la revisión está en curso y el documento no informa el resultado.",
    ),
    (
        "La revisión concluyó el lunes con resultado favorable.",
        "Según el aviso, la revisión concluyó el lunes y su resultado fue favorable.",
    ),
    (
        "La oficina informó el lunes que el resultado se publicará el jueves.",
        "Según el aviso, la oficina informó el lunes que el resultado se publicará el jueves.",
    ),
    (
        "Si se habilita la sala, la revisión podría realizarse el jueves.",
        "Según el aviso, si se habilita la sala, la revisión podría realizarse el jueves.",
    ),
])
def test_supported_present_past_future_and_conditional_are_not_rewritten(source_text, text):
    request, found, plan, proposal = temporal_inputs(source_text, text)
    # A completed or merely informational event has no invented future mandate.
    request["description"] = "Explique el estado que informa el aviso."
    found["missing"] = []
    worker, calls = engine(plan, proposal, proposed_check())
    result = build_draft_graph(worker, InMemorySaver()).invoke(
        {"request": request, "finding": found},
        {"configurable": {"thread_id": "temporal-legitimate"}},
    )
    assert len(calls) == 3 and "repair" not in result
    assert result["draft"]["paragraphs"][0]["text"] == text
    assert result["draft"]["pending"] == []
    assert result["checks"]["status"] == "passed"


def test_new_temporal_issue_at_recheck_remains_visible_without_an_automatic_second_round():
    request, found, plan, proposal = temporal_inputs(
        "El resultado se publicará el jueves en el tablero técnico.",
        "Según el aviso, no se conoce cuál fue el resultado.",
    )
    first_issue = {"code": "citation_scope", "paragraph_index": 0,
                   "description": "Conservar el lugar y fecha previstos."}
    worker, calls = engine(plan, proposal,
                           proposed_check(status="needs_changes", issues=[first_issue]),
                           {"paragraphs": [{"paragraph_index": 0,
                              "text": "Según el aviso, no se conoce cuál fue el resultado. "
                                      "Se prevé publicarlo el jueves en el tablero técnico.",
                              "cited_chunk_ids": ["S1"]}]},
                           proposed_check(status="needs_changes", issues=[temporal_issue()]))
    result = build_draft_graph(worker, InMemorySaver()).invoke(
        {"request": request, "finding": found},
        {"configurable": {"thread_id": "temporal-late-review"}},
    )
    assert len(calls) == 5 and result["repair"]["attempts"] == 1
    assert result["checks"]["status"] == "needs_changes"
    assert result["checks"]["issues"] == [temporal_issue()]
    assert result["draft"]["pending"] == result["repair"]["before_draft"]["pending"]
