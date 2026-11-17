"""La revisión final conserva el contrato de incisos, incluso tras edición humana."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
import test_review_service_api as service_tests
from langgraph.checkpoint.memory import InMemorySaver
from test_normative_document_requests import norm
from test_normative_document_requests import request as copy_request
from test_review_engine import HASH, engine, inquiry, paragraph, pending, resolution, review
from test_review_service_api import (
    approve,
    assess,
    current,
    prepare,
    save,
)

from pqrs_claro import review_service
from pqrs_claro.models import DomainError
from pqrs_claro.request_requirements import build_requirements
from pqrs_claro.review_engine import structural_checks, validate_review_input
from pqrs_claro.review_graph import build_review_graph
from pqrs_claro.review_service import ReviewService

review_app = service_tests.review_app


def question():
    item = inquiry(description="Informe el estado histórico del trámite; explique cómo reclamar.")
    item["request_requirements"] = build_requirements(item)
    return item


def checklist(*, second="answered"):
    return [{"requirement_id": f"R{index}", "status": state,
             "paragraph_indexes": [0] if state == "answered" else [],
             "pending_indexes": [], "explanation": "Texto cubierto." if state == "answered"
             else "Falta explicar cómo reclamar."}
            for index, state in enumerate(("answered", second), 1)]


@pytest.mark.parametrize("checks", [[], checklist(second="omitted")])
def test_final_reader_cannot_pass_without_a_complete_check_of_saved_text(checks):
    worker, calls = engine({"status": "passed", "issues": [], "requirement_checks": checks})
    value = review()
    before = deepcopy(value)
    result = worker.assess(question(), value)
    assert result["status"] == "needs_changes"
    assert {i["code"] for i in result["issues"]} & {
        "coverage_review_incomplete", "request_component_omitted",
    }
    assert result["requirement_checks"] == checks
    assert value == before
    assert json.loads(calls[0]["input"])["request"]["request_requirements"] == question()[
        "request_requirements"
    ]
    assert len(calls) == (2 if not checks else 1)


def test_final_reader_keeps_literal_requirement_records_in_its_assessment():
    worker, _ = engine({"status": "passed", "issues": [], "requirement_checks": checklist()})
    result = worker.assess(question(), review())
    assert result["status"] == "passed"
    assert result["requirement_checks"] == checklist()


@pytest.mark.parametrize("checks", [[], checklist(second="omitted")])
def test_approval_graph_independently_rejects_a_passing_provider_with_omitted_checks(checks):
    class PassingProvider:
        def assess(self, request, row):
            return {"status": "passed", "issues": [], "local_checks": [],
                    "requirement_checks": checks}

    graph = build_review_graph(PassingProvider(), InMemorySaver())
    config = {"configurable": {"thread_id": "omitted-requirement"}}
    result = graph.invoke({"request": question(), "review": review(), "input_hash": HASH}, config)
    assert result["assessment"]["status"] == "needs_changes"
    assert result["approval"] is None
    assert "__interrupt__" not in result


def test_normative_copy_reaches_final_review_but_rules_do_not_close_case_document_gaps():
    item = copy_request()
    source = norm(role="document", location_kind="page", origin_selection="automatic")
    value = review(case_id=item["case_id"], available_supports=[source], paragraphs=[
        paragraph(text="Se localizó el original para preparar su copia.",
                  cited_chunk_ids=[source["chunk_id"]]),
    ])
    assert validate_review_input(item, value)["available_supports"][0]["role"] == "document"
    finding = {"supports": [], "candidate_documents": [{"chunks": [source]}]}
    candidates = ReviewService._supports(item, finding, {source["chunk_id"]: source})
    assert candidates[0]["role"] == "document"
    resolved = {"id": "copy", "kind": "document", "description": "Localizar la Circular 402.",
                "resolution": {"action": "resolved", "cited_chunk_ids": [source["chunk_id"]],
                               "cited_fact_ids": []}}
    value["pending"] = [resolved]
    assert not structural_checks(value)[1]
    value["available_supports"][0]["role"] = "rule"
    assert "document_resolution_has_file" in {i["code"] for i in structural_checks(value)[1]}
    wrong_scope = {**item, "allowed_collection_ids": []}
    source.update(collection_id="withdrawn", role="document")
    with pytest.raises(DomainError, match="no vinculados"):
        validate_review_input(wrong_scope, value)


def test_saved_edit_requires_a_fresh_component_review_and_keeps_the_text(review_app):
    app, client, provider, _ = review_app
    case, _, row = prepare(app, client)
    row = assess(app, client, case, row)
    assert row["assessment"]["requirement_checks"]
    edited = deepcopy(row["paragraphs"])
    edited[0]["text"] = "Texto humano guardado que necesita nueva comprobación."
    response = save(client, case, row, paragraphs=edited)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["assessment"] is None and saved["approval"] is None
    assert saved["request_snapshot"]["request_requirements"]
    assert current(client, case)["paragraphs"] == saved["paragraphs"]
    provider.assess = lambda request, row: {
        "status": "passed", "issues": [], "local_checks": [], "requirement_checks": [],
    }
    checked = assess(app, client, case, saved)
    assert checked["status"] == "needs_changes"
    assert checked["assessment"]["issues"][0]["code"] == "coverage_review_incomplete"
    assert checked["paragraphs"] == saved["paragraphs"]
    assert approve(client, case, checked).status_code == 409


def test_review_policy_invalidates_approval_and_preserves_text(review_app, monkeypatch):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    row = assess(app, client, case, row)
    approved = approve(client, case, row)
    assert approved.status_code == 200, approved.text
    before = deepcopy(approved.json()["paragraphs"])
    monkeypatch.setattr(review_service, "REVIEW_VERSION", review_service.REVIEW_VERSION + 1)
    stale = current(client, case)
    assert stale["stale"] and stale["status"] == "stale"
    assert stale["paragraphs"] == before
    assert stale["approval"] is None and stale["assessment"] is None


def test_review_rechecks_invalid_checklist_once_without_changing_saved_content():
    item = inquiry()
    item["request_requirements"] = build_requirements(item)
    value = review(pending=[pending(basis="metadata_only", resolution=resolution())])
    before = deepcopy(value)
    invalid = {"requirement_id": "R1", "status": "pending", "paragraph_indexes": [],
               "pending_indexes": [0], "explanation": "El control de catálogo sigue en la lista."}
    answered = {"requirement_id": "R1", "status": "answered", "paragraph_indexes": [0],
                "pending_indexes": [], "explanation": "El párrafo sí explica el estado histórico."}
    worker, _ = engine()
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        result = {"status": "passed", "issues": [],
                  "requirement_checks": [invalid if len(calls) == 1 else answered]}
        return SimpleNamespace(status="completed",
                               output_parsed=kwargs["text_format"].model_validate(result))

    worker.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = worker.assess(item, value)
    assert result["status"] == "passed" and len(calls) == 2
    first, second = (json.loads(c["input"]) for c in calls)
    repair = second.pop("requirement_check_repair")
    assert first == second
    assert repair["previous_checks"] == [invalid]
    assert [x["code"] for x in repair["errors"]] == ["coverage_review_invalid"]
    assert "omitted" in repair["instruction"]
    assert result["requirement_checks"] == [answered]
    assert next(c for c in result["local_checks"]
                if c["code"] == "requirement_check_repair")["passed"]
    assert value == before


@pytest.mark.parametrize("second", ["invalid", "omitted"])
def test_review_stops_after_one_checklist_retry_and_preserves_unanswered_component(second):
    item = inquiry()
    item["request_requirements"] = build_requirements(item)
    value = review()
    before = deepcopy(value)
    worker, _ = engine()
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        checks = [] if len(calls) == 1 or second == "invalid" else [{
            "requirement_id": "R1", "status": "omitted", "paragraph_indexes": [],
            "pending_indexes": [], "explanation": "Falta un componente de la respuesta.",
        }]
        return SimpleNamespace(
            status="completed", output_parsed=kwargs["text_format"].model_validate({
                "status": "passed", "issues": [], "requirement_checks": checks,
            }),
        )

    worker.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = worker.assess(item, value)
    assert result["status"] == "needs_changes" and len(calls) == 2
    expected = "coverage_review_incomplete" if second == "invalid" else "request_component_omitted"
    assert expected in {i["code"] for i in result["issues"]}
    assert not next(c for c in result["local_checks"]
                    if c["code"] == "requirement_check_repair")["passed"]
    assert value == before
