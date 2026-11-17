"""Complete a grounded omission without overwriting answers or pending controls."""

from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_draft_answer_coverage import checks, inputs
from test_draft_engine import engine

from pqrs_claro.draft_graph import build_draft_graph
from pqrs_claro.draft_repair import CitationRepairRejected, repair_unit_ids


def missing_review():
    result = checks(omitted=True)
    result["requirement_checks"][1].update(status="omitted", paragraph_indexes=[])
    result["unit_checks"][1]["paragraph_indexes"] = []
    return result


def complete_review():
    result = checks()
    result["requirement_checks"][1]["paragraph_indexes"] = [1]
    result["unit_checks"][1]["paragraph_indexes"] = [1]
    return result


def initial_draft():
    return {"paragraphs": [{
        "text": "El oficio informa que en 2024 el comité fijó cuatro equipos como límite.",
        "cited_chunk_ids": ["S1"],
    }], "pending": []}


def addition(**changes):
    return {"unit_id": "U2",
            "text": "Según el oficio, el fundamento fue el estudio técnico de cargas.",
            "cited_chunk_ids": ["S1"], **changes}


def test_graph_completes_wholly_omitted_requirement_and_preserves_existing_content():
    request, finding, plan = inputs()
    worker, calls = engine(plan, initial_draft(), missing_review(),
                           {"paragraphs": [], "omitted_unit_paragraphs": [addition()]},
                           complete_review())
    result = build_draft_graph(worker, InMemorySaver()).invoke(
        {"request": request, "finding": finding},
        {"configurable": {"thread_id": "whole-grounded-omission"}},
    )
    assert len(calls) == 5  # Existing bounded repair and mandatory full recheck.
    assert result["checks"]["status"] == "passed"
    assert result["repair"]["added_unit_ids"] == ["U2"]
    before = result["repair"]["before_draft"]
    assert result["draft"]["paragraphs"][:-1] == before["paragraphs"]
    assert result["draft"]["pending"] == before["pending"]
    assert before["pending"]  # Authenticity control stays open.
    assert result["draft"]["paragraphs"][-1]["text"] == addition()["text"]
    assert result["repair"]["before_checks"]["request_trace"]["missing_unit_ids"] == ["U2"]
    assert result["checks"]["request_trace"]["missing_unit_ids"] == []


@pytest.mark.parametrize("added", [
    [addition(unit_id="U1")],  # Already answered.
    [addition(unit_id="U3")],  # Optional context.
    [addition(), addition()],
    [addition(cited_chunk_ids=["S99"])],
])
def test_added_paragraph_cannot_invent_an_obligation_or_change_its_sources(added):
    request, finding, proposed = inputs()
    worker, _ = engine(proposed, initial_draft(), missing_review(),
                        {"paragraphs": [], "omitted_unit_paragraphs": added})
    plan = worker.plan(request, finding)
    draft = worker.write(request, finding, plan)
    checked = worker.check(request, finding, plan, draft)
    original = deepcopy(draft)
    with pytest.raises(CitationRepairRejected):
        worker.repair(request, finding, plan, draft, checked)
    assert draft == original


def test_trace_cannot_create_an_omission_without_review_and_respects_paragraph_limit():
    request, finding, proposed = inputs()
    worker, _ = engine(proposed, initial_draft(), missing_review())
    plan = worker.plan(request, finding)
    draft = worker.write(request, finding, plan)
    checked = worker.check(request, finding, plan, draft)
    assert repair_unit_ids(checked, draft, plan) == ["U2"]
    assert repair_unit_ids(checked, {"paragraphs": [{}] * 20}, plan) == []
    checked["unit_checks"][1]["status"] = "pending"
    assert repair_unit_ids(checked, draft, plan) == []
