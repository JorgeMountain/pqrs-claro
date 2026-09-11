"""Ajustes reales de referencias y recuperación sin alterar controles o texto humano."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_draft_engine import (
    engine,
    finding,
    inquiry,
    proposed_check,
    proposed_draft,
    proposed_plan,
    support,
)

from pqrs_claro.draft_graph import build_draft_graph
from pqrs_claro.draft_repair import repair_targets
from pqrs_claro.models import DomainError


def issue(index=0):
    return {"code": "citation_scope", "description": "Precisar el pasaje citado.",
            "paragraph_index": index}


def patch(**changes):
    return {"paragraph_index": 0, "text": "Según el oficio 0123 de 2024, el comité "
            "informó que aprobó la plaza de prácticas.", "cited_chunk_ids": ["S1"], **changes}


def test_repair_preserves_controls_other_paragraphs_and_original():
    proposal = proposed_draft()
    proposal["paragraphs"].append(deepcopy(proposal["paragraphs"][0]))
    worker, calls = engine(proposed_plan(), proposal, {"paragraphs": [patch()]})
    source_finding = finding()
    plan = worker.plan(inquiry(), source_finding)
    draft = worker.write(inquiry(), source_finding, plan)
    original = deepcopy(draft)
    repaired = worker.repair(inquiry(), source_finding, plan, draft,
                             proposed_check(status="needs_changes", issues=[issue()]))
    assert draft == original
    assert repaired["pending"] == original["pending"]
    assert repaired["status"] == original["status"]
    assert repaired["paragraphs"][1] == original["paragraphs"][1]
    assert repaired["paragraphs"][0]["text"] == patch()["text"]
    context = json.loads(calls[-1]["input"])
    assert context["repair_targets"] == [0]
    assert context["draft"]["paragraphs"][0]["cited_chunk_ids"] == ["S1"]
    assert "pending" not in calls[-1]["text_format"].model_fields


@pytest.mark.parametrize("patches", [
    [patch(paragraph_index=1)],
    [patch(), patch()],
    [patch(cited_chunk_ids=["S99"])],
    [patch(cited_chunk_ids=["S1", "S1"])],
    [patch(cited_chunk_ids=[])],
    [patch(text="Según S99, la plaza está aprobada.")],
])
def test_repair_rejects_scope_or_reference_changes(patches):
    worker, _ = engine(proposed_plan(), proposed_draft(), {"paragraphs": patches})
    plan = worker.plan(inquiry(), finding())
    draft = worker.write(inquiry(), finding(), plan)
    original = deepcopy(draft)
    with pytest.raises(DomainError):
        worker.repair(inquiry(), finding(), plan, draft,
                      proposed_check(status="needs_changes", issues=[issue()]))
    assert draft == original


def test_repair_adds_citable_contiguous_passage_without_using_candidates():
    sources = finding(supports=[support(), support(chunk_id="oficio:2", page=2,
        quote="En 2023 el comité había abierto la convocatoria.")])
    worker, _ = engine(proposed_plan(), proposed_draft(), {"paragraphs": [patch(
        text="Según el oficio 0123 de 2024, la convocatoria se abrió en 2023.",
        cited_chunk_ids=["S2"])]})
    plan = worker.plan(inquiry(), sources)
    draft = worker.write(inquiry(), sources, plan)
    result = worker.repair(inquiry(), sources, plan, draft,
                           proposed_check(status="needs_changes", issues=[issue()]))
    assert result["paragraphs"][0]["cited_chunk_ids"] == ["oficio:2"]
    assert result["pending"] == draft["pending"]


def test_graph_repairs_once_and_rechecks_entire_draft():
    failed = proposed_check(status="needs_changes", issues=[issue()])
    worker, calls = engine(proposed_plan(), proposed_draft(), failed,
                           {"paragraphs": [patch()]}, failed)
    graph = build_draft_graph(worker, InMemorySaver())
    result = graph.invoke({"request": inquiry(), "finding": finding()},
                          {"configurable": {"thread_id": "bounded-repair"}})
    assert len(calls) == 5
    assert result["checks"]["status"] == "needs_changes"
    assert result["repair"]["attempts"] == 1
    assert result["repair"]["changed"] is True
    assert result["repair"]["before_draft"]["pending"] == result["draft"]["pending"]
    assert result["repair"]["before_checks"]["issues"] == [issue()]
    assert json.loads(calls[-1]["input"])["draft"]["paragraphs"][0]["text"] == patch()["text"]


def test_recheck_failure_resumes_without_rewriting_or_repairing_again():
    worker, calls = engine(proposed_plan(), proposed_draft(),
                           proposed_check(status="needs_changes", issues=[issue()]),
                           {"paragraphs": [patch()]},
                           SimpleNamespace(status="incomplete", output_parsed=None),
                           proposed_check())
    graph = build_draft_graph(worker, InMemorySaver())
    config = {"configurable": {"thread_id": "resume-final-check"}}
    with pytest.raises(DomainError):
        graph.invoke({"request": inquiry(), "finding": finding()}, config)
    saved = graph.get_state(config)
    assert saved.next == ("recomprobar",)
    assert saved.values["repair"]["before_checks"]["status"] == "needs_changes"
    assert saved.values["draft"]["paragraphs"][0]["text"] == patch()["text"]
    result = graph.invoke(None, config)
    assert result["checks"]["status"] == "passed"
    assert len(calls) == 6
    assert [call["text_format"].__name__ for call in calls].count("CitationRepair") == 1


@pytest.mark.parametrize("issues,status", [([], "passed"), ([issue(None)], "needs_changes")])
def test_global_pending_or_valid_draft_does_not_trigger_repair(issues, status):
    worker, calls = engine(proposed_plan(), proposed_draft(),
                           proposed_check(status=status, issues=issues))
    graph = build_draft_graph(worker, InMemorySaver())
    result = graph.invoke({"request": inquiry(), "finding": finding()},
                          {"configurable": {"thread_id": "no-repair"}})
    assert len(calls) == 3
    assert "repair" not in result


def test_repair_targets_ignore_boolean_or_invalid_indices():
    checks = proposed_check(status="needs_changes", issues=[issue(True), issue(-1),
        issue(2), issue(None), issue(0)])
    assert repair_targets(checks, {"paragraphs": [{}]}) == [0]


def scope_paragraph():
    return {"text": "La solicitud pide explicar la respuesta del comité sobre la plaza "
            "de prácticas. También solicita identificar los documentos de esa respuesta.",
            "cited_chunk_ids": ["S1"]}


def test_graph_can_remove_only_redundant_request_scope_and_recheck_shifted_paragraphs():
    proposal = proposed_draft()
    proposal["paragraphs"].insert(0, scope_paragraph())
    worker, calls = engine(proposed_plan(), proposal, proposed_check(),
        {"paragraphs": [], "remove_request_scope_indices": [0]}, proposed_check())
    graph = build_draft_graph(worker, InMemorySaver())
    result = graph.invoke({"request": inquiry(), "finding": finding()},
                          {"configurable": {"thread_id": "remove-request-summary"}})
    audit = result["repair"]
    assert audit["removed_request_scope_indices"] == [0]
    assert audit["before_draft"]["paragraphs"][0]["text"] == scope_paragraph()["text"]
    assert result["draft"]["paragraphs"] == audit["before_draft"]["paragraphs"][1:]
    assert result["draft"]["pending"] == audit["before_draft"]["pending"]
    assert "_removed_request_scope_indices" not in result["draft"]
    assert result["checks"]["status"] == "passed"
    assert len(calls) == 5
    assert json.loads(calls[3]["input"])["removable_request_scope_indices"] == [0]


@pytest.mark.parametrize("text,code", [
    (scope_paragraph()["text"], "irrelevant_citation"),
    ("Según el oficio 0123 de 2024, el comité informó la aprobación.", "request_scope_only"),
    ("La solicitud pregunta por la plaza. Según el oficio de 2024, fue aprobada.",
     "request_scope_only"),
    ("El antecedente no confirma la situación actual.", "request_scope_only"),
])
def test_removal_requires_explicit_scope_issue_and_independent_scope_validation(text, code):
    worker, _ = engine(proposed_plan(), proposed_draft(text=text),
                        {"paragraphs": [], "remove_request_scope_indices": [0]})
    plan = worker.plan(inquiry(), finding())
    draft = worker.write(inquiry(), finding(), plan)
    before = deepcopy(draft)
    with pytest.raises(DomainError, match="retirar contenido"):
        worker.repair(inquiry(), finding(), plan, draft,
                      proposed_check(status="needs_changes", issues=[{**issue(), "code": code}]))
    assert draft == before


def test_repair_cannot_replace_and_remove_same_summary():
    worker, _ = engine(proposed_plan(), proposed_draft(text=scope_paragraph()["text"]),
        {"paragraphs": [patch()], "remove_request_scope_indices": [0]})
    plan = worker.plan(inquiry(), finding())
    draft = worker.write(inquiry(), finding(), plan)
    with pytest.raises(DomainError, match="párrafo no señalado o repetido"):
        worker.repair(
            inquiry(), finding(), plan, draft,
            proposed_check(
                status="needs_changes", issues=[{**issue(), "code": "request_scope_only"}]
            ),
        )


@pytest.mark.parametrize("invalid_ids", [[""], ["S99"]])
def test_rejected_patch_preserves_draft_and_finishes_without_recheck_or_retry(invalid_ids):
    failed = proposed_check(status="needs_changes", issues=[issue()])
    proposal = proposed_draft()
    proposal["paragraphs"].append(deepcopy(proposal["paragraphs"][0]))
    worker, calls = engine(
        proposed_plan(), proposal, failed,
        {"paragraphs": [patch(cited_chunk_ids=invalid_ids)]},
    )
    graph = build_draft_graph(worker, InMemorySaver())
    config = {"configurable": {"thread_id": "reject-invalid-citation"}}
    result = graph.invoke({"request": inquiry(), "finding": finding()}, config)

    assert len(calls) == 4
    assert [call["text_format"].__name__ for call in calls].count("CitationRepair") == 1
    audit = result["repair"]
    assert audit["status"] == "rejected"
    assert audit["attempts"] == 1
    assert audit["changed"] is False
    assert audit["removed_request_scope_indices"] == []
    assert audit["reason"]
    assert result["draft"] == audit["before_draft"]
    assert result["draft"]["pending"]
    assert result["draft"]["paragraphs"][0]["text"] == proposal["paragraphs"][0]["text"]
    assert result["draft"]["paragraphs"][1]["text"] == proposal["paragraphs"][1]["text"]
    assert result["draft"]["status"] != "error"
    assert not result.get("error")
    assert result["checks"]["status"] == "needs_changes"
    assert result["checks"]["local_checks"] == audit["before_checks"]["local_checks"]
    assert result["checks"]["issues"][:-1] == audit["before_checks"]["issues"] == [issue()]
    rejection = result["checks"]["issues"][-1]
    assert rejection["code"] == "citation_repair_rejected"
    assert rejection["paragraph_index"] is None
    assert audit["reason"] in rejection["description"]

    saved = graph.get_state(config)
    assert saved.next == ()
    assert not any(task.error for task in saved.tasks)
    resumed = graph.invoke(None, config)
    assert resumed["draft"] == result["draft"]
    assert resumed["checks"] == result["checks"]
    assert resumed["repair"] == audit
    assert len(calls) == 4


@pytest.mark.parametrize(
    "failure", [DomainError("La entrada de reparación no es válida."), RuntimeError("API caída.")]
)
def test_graph_does_not_convert_generic_domain_or_api_failure_to_rejected_patch(failure):
    calls = []

    class FailingEngine:
        def plan(self, request, source_finding):
            calls.append("plan")
            return proposed_plan()

        def write(self, request, source_finding, plan):
            calls.append("write")
            return proposed_draft()

        def check(self, request, source_finding, plan, draft):
            calls.append("check")
            return proposed_check(status="needs_changes", issues=[issue()])

        def repair(self, request, source_finding, plan, draft, checks):
            calls.append("repair")
            raise failure

    graph = build_draft_graph(FailingEngine(), InMemorySaver())
    config = {"configurable": {"thread_id": "preserve-real-repair-error"}}
    with pytest.raises(type(failure), match=str(failure)):
        graph.invoke({"request": inquiry(), "finding": finding()}, config)
    assert calls == ["plan", "write", "check", "repair"]
    saved = graph.get_state(config)
    assert saved.next == ("ajustar_citas",)
    assert "repair" not in saved.values
    assert saved.values["checks"]["issues"] == [issue()]


def test_incomplete_provider_response_is_not_a_postvalidation_patch_rejection():
    worker, calls = engine(
        proposed_plan(), proposed_draft(),
        proposed_check(status="needs_changes", issues=[issue()]),
        SimpleNamespace(status="incomplete", output_parsed=None),
    )
    graph = build_draft_graph(worker, InMemorySaver())
    config = {"configurable": {"thread_id": "preserve-incomplete-api-response"}}
    with pytest.raises(DomainError):
        graph.invoke({"request": inquiry(), "finding": finding()}, config)
    assert len(calls) == 4
    saved = graph.get_state(config)
    assert saved.next == ("ajustar_citas",)
    assert "repair" not in saved.values


def test_rejected_patch_is_atomic_when_an_earlier_replacement_was_valid():
    proposal = proposed_draft()
    proposal["paragraphs"].append(deepcopy(proposal["paragraphs"][0]))
    failed = proposed_check(status="needs_changes", issues=[issue(0), issue(1)])
    worker, calls = engine(
        proposed_plan(), proposal, failed,
        {"paragraphs": [patch(), patch(paragraph_index=1, cited_chunk_ids=["S99"])]},
    )
    graph = build_draft_graph(worker, InMemorySaver())
    result = graph.invoke(
        {"request": inquiry(), "finding": finding()},
        {"configurable": {"thread_id": "atomic-rejected-citation-patch"}},
    )
    assert len(calls) == 4
    assert result["repair"]["status"] == "rejected"
    assert result["repair"]["target_indices"] == [0, 1]
    assert result["draft"] == result["repair"]["before_draft"]
    assert result["draft"]["paragraphs"][0]["text"] != patch()["text"]
    assert [p["text"] for p in result["draft"]["paragraphs"]] == [
        p["text"] for p in proposal["paragraphs"]
    ]
    assert result["checks"]["issues"][:-1] == failed["issues"]
