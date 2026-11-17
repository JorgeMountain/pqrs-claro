"""The saved human response must account for its current, citation-bound units."""

import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest
import test_review_service_api as service_tests
from langgraph.checkpoint.memory import InMemorySaver
from test_draft_service_api import ready_map
from test_review_engine import HASH, engine, inquiry, pending, resolution, review, support
from test_review_service_api import approve, assess, current, prepare, save, url, wait_review

from pqrs_claro.models import DomainError
from pqrs_claro.request_requirements import build_requirements
from pqrs_claro.review_engine import OpenAIDraftEngine, validate_review_input
from pqrs_claro.review_graph import build_review_graph
from pqrs_claro.review_service import input_hash

review_app = service_tests.review_app


def question():
    value = inquiry()
    value["request_requirements"] = build_requirements(value)
    return value


def unit(source=None, **changes):
    source = source or support()
    return {
        "id": "U1", "requirement_id": "R1", "kind": "answer", "required": True,
        "claim": source["quote"],
        "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
        "reason": "La petición pregunta por este dato del soporte.",
        "details_version": 1, "details": [],
        "no_details_reason": "Dato simple sin identidad nombrada ni alternativa.", **changes,
    }


def unit_check(**changes):
    return {
        "unit_id": "U1", "status": "answered", "paragraph_indexes": [0],
        "pending_indexes": [], "explanation": "El párrafo conserva el dato y su alcance.",
        **changes,
    }


def assessment(**changes):
    return {
        "status": "passed", "issues": [], "local_checks": [],
        "requirement_checks": [{
            "requirement_id": "R1", "status": "answered", "paragraph_indexes": [0],
            "pending_indexes": [], "explanation": "Respuesta al inciso guardado.",
        }],
        "unit_checks": [unit_check()], **changes,
    }


def provider_assessment(**changes):
    result = assessment(**changes)
    result.pop("local_checks")
    return result


def attach_plan_units(app, monkeypatch):
    planner = app.state.drafts.engine
    original_plan = planner.plan

    def plan(request, finding):
        return {**original_plan(request, finding),
                "coverage_units": [unit(finding["supports"][0])]}

    monkeypatch.setattr(planner, "plan", plan)
    reviewer = app.state.reviews.engine
    original_assess = reviewer.assess

    def check(request, row):
        return {**original_assess(request, row), "unit_checks": [unit_check()]}

    monkeypatch.setattr(reviewer, "assess", check)


def test_saved_units_reach_provider_as_closed_aliases_without_mutation():
    worker, calls = engine(provider_assessment())
    value = review(coverage_units=[unit()])
    before = deepcopy(value)
    result = worker.assess(question(), value)
    assert result["status"] == "passed"
    assert result["unit_checks"] == [unit_check()]
    sent = json.loads(calls[0]["input"])["review"]["coverage_units"][0]
    assert sent["citations"] == [{"chunk_id": "S1", "quote": support()["quote"]}]
    assert value == before and len(calls) == 1


@pytest.mark.parametrize("bad", [
    {"citations": [{"chunk_id": support()["chunk_id"], "quote": "Una cita inventada."}]},
    {"citations": [{"chunk_id": "otro:1:1:1-2", "quote": support()["quote"]}]},
    {"requirement_id": "R2"},
])
def test_review_rejects_units_without_current_literal_authorized_support(bad):
    with pytest.raises(DomainError):
        validate_review_input(question(), review(coverage_units=[unit(**bad)]))


def test_missing_required_unit_check_has_one_structural_retry_only():
    worker, calls = engine(provider_assessment(unit_checks=[]))
    value = review(coverage_units=[unit()])
    result = worker.assess(question(), value)
    assert len(calls) == 2 and result["status"] == "needs_changes"
    assert "unit_review_incomplete" in {i["code"] for i in result["issues"]}
    first, second = [json.loads(c["input"]) for c in calls]
    repair = second.pop("requirement_check_repair")
    assert first == second
    assert repair["previous_unit_checks"] == []
    assert not next(c for c in result["local_checks"]
                    if c["code"] == "requirement_check_repair")["passed"]


def test_repaired_unit_check_is_accepted_without_rewriting_text():
    worker, _ = engine()
    value = review(coverage_units=[unit()])
    before, calls = deepcopy(value), []

    def parse(**kwargs):
        calls.append(kwargs)
        result = provider_assessment(unit_checks=[] if len(calls) == 1 else [unit_check()])
        return SimpleNamespace(status="completed",
                               output_parsed=kwargs["text_format"].model_validate(result))

    worker.client.responses.parse = parse
    checked = worker.assess(question(), value)
    assert checked["status"] == "passed" and len(calls) == 2
    assert value == before


def test_semantic_omission_is_not_retried_or_approved_by_passing_provider():
    omitted = unit_check(status="omitted", paragraph_indexes=[], explanation="Falta la condición.")
    worker, calls = engine(provider_assessment(unit_checks=[omitted]))
    value = review(coverage_units=[unit(kind="condition")])
    result = worker.assess(question(), value)
    assert result["status"] == "needs_changes" and len(calls) == 1
    assert "answer_unit_omitted" in {i["code"] for i in result["issues"]}


@pytest.mark.parametrize("checks", [[], [unit_check(status="omitted", paragraph_indexes=[])]])
def test_approval_graph_independently_enforces_required_units(checks):
    class Passing:
        def assess(self, request, row):
            return assessment(unit_checks=checks)

    graph = build_review_graph(Passing(), InMemorySaver())
    result = graph.invoke({"request": question(), "review": review(coverage_units=[unit()]),
                           "input_hash": HASH},
                          {"configurable": {"thread_id": "units-cannot-disappear"}})
    assert result["assessment"]["status"] == "needs_changes"
    assert result["approval"] is None and "__interrupt__" not in result


@pytest.mark.parametrize("gap", [pending(basis="metadata_only"),
                                 pending(resolution=resolution())])
def test_catalog_or_closed_gap_cannot_replace_an_omitted_unit(gap):
    checked = unit_check(status="pending", paragraph_indexes=[], pending_indexes=[0])
    worker, calls = engine(provider_assessment(unit_checks=[checked]))
    result = worker.assess(question(), review(coverage_units=[unit()], pending=[gap]))
    assert result["status"] == "needs_changes" and len(calls) == 2
    assert "unit_review_invalid" in {i["code"] for i in result["issues"]}


def test_optional_unit_does_not_invent_a_pending_or_force_extra_content():
    worker, calls = engine(provider_assessment(unit_checks=[]))
    value = review(coverage_units=[unit(required=False, kind="context")])
    result = worker.assess(question(), value)
    assert result["status"] == "passed" and len(calls) == 1
    assert value["pending"] == []


def test_plan_units_survive_save_reload_and_approval_snapshot(review_app, monkeypatch):
    app, client, _, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, _, row = prepare(app, client)
    original = deepcopy(row["coverage_units"])
    assert len(original) == 1
    checked = assess(app, client, case, row)
    approved = approve(client, case, checked)
    assert approved.status_code == 200, approved.text
    snapshot = app.state.reviews.store.approval(approved.json()["approval"]["id"])
    assert snapshot["review"]["coverage_units"] == original
    assert snapshot["review"]["assessment"]["unit_checks"] == [unit_check()]
    edited = deepcopy(row["paragraphs"])
    edited[0]["text"] += " Nueva redacción humana."
    saved = save(client, case, approved.json(), paragraphs=edited).json()
    assert saved["assessment"] is None and saved["approval"] is None
    assert current(client, case)["coverage_units"] == original
    altered = {**saved, "coverage_units": [unit(row["available_supports"][0], claim="Otro dato.")]}
    assert input_hash(altered) != input_hash(saved)


def test_changed_sources_invalidate_units_and_refresh_only_plan_before_check(
    review_app, monkeypatch,
):
    app, client, worker, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, source, row = prepare(app, client)
    before = deepcopy(row["paragraphs"])
    app.state.library.review(source["id"], reviewed_by="Revisora", review_note="Cambio de fuente",
                             validity="current")
    assert current(client, case)["coverage_units"] is None
    ready_map(app, case)
    response = client.post(url(case, "/start"), json={"version": case["version"]})
    synced = response.json()["requests"][0]
    assert synced["coverage_units"] is None and synced["paragraphs"] == before
    calls = []

    def prepare_units(request, value):
        calls.append(deepcopy(value))
        return [unit(value["available_supports"][0])]

    monkeypatch.setattr(worker, "prepare_units", prepare_units, raising=False)
    checked = assess(app, client, case, synced)
    assert len(calls) == 1 and checked["status"] == "ready"
    assert checked["paragraphs"] == before
    assert checked["pending"] == synced["pending"]
    assert checked["coverage_units"] == [unit(checked["available_supports"][0])]
    assert checked["assessment"]["input_hash"] == input_hash(checked)


def test_invalidated_units_do_not_silently_disappear_for_legacy_provider(review_app, monkeypatch):
    app, client, worker, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, _, row = prepare(app, client)
    row["coverage_units"] = None
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")
    checked = assess(app, client, case, row)
    assert checked["status"] == "error" and worker.calls == 0
    assert "inventario" in checked["error"]
    assert checked["paragraphs"] == row["paragraphs"] and checked["coverage_units"] is None
    assert approve(client, case, checked).status_code == 409


def test_edit_during_plan_refresh_cannot_overwrite_saved_text_or_units(review_app, monkeypatch):
    app, client, worker, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, _, row = prepare(app, client)
    row["coverage_units"] = None
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")
    entered, release = threading.Event(), threading.Event()

    def prepare_units(request, value):
        entered.set()
        assert release.wait(10)
        return [unit(value["available_supports"][0])]

    monkeypatch.setattr(worker, "prepare_units", prepare_units, raising=False)
    response = client.post(url(case, "/requests/P1/assess"), json={"revision": row["revision"]})
    assert response.status_code == 202 and entered.wait(5)
    editing = current(client, case)
    paragraphs = deepcopy(editing["paragraphs"])
    paragraphs[0]["text"] += " Cambio humano durante el inventario."
    saved = save(client, case, editing, paragraphs=paragraphs)
    assert saved.status_code == 200, saved.text
    release.set()
    finished = wait_review(app, client, case)
    assert finished["paragraphs"] == paragraphs and finished["coverage_units"] is None
    assert finished["assessment"] is None and worker.calls == 0


def test_revocation_hides_unit_claims_and_quotes_even_from_history(review_app, monkeypatch):
    app, client, _, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, _, row = prepare(app, client)
    library = app.state.library
    library.save_collection({"id": "units-private", "title": "Reservado"})
    library.link_collections(case["id"], ["units-private"])
    secret = "Motivación reservada en una unidad ficticia."
    source = library.add("reservado.txt", secret.encode(), title="Reservado", origin="Prueba",
                         category="historical_attachment", collection_id="units-private")
    _, chunks = library.snapshot(case["id"], source_ids={source["id"]})
    private = {**chunks[0], "role": "antecedent", "origin_selection": "candidate"}
    row["available_supports"].append(private)
    row["coverage_units"] = [unit(private)]
    row["request_snapshot"]["allowed_collection_ids"] = ["units-private"]
    app.state.reviews.store.save(row, expected=row["revision"], event="edited")
    library.link_collections(case["id"], [])
    for tail in ("", "/requests/P1/history"):
        response = client.get(url(case, tail))
        assert response.status_code == 200, response.text
        assert secret not in response.text and source["id"] not in response.text


def test_refresh_uses_current_complete_sources_and_plan_only(monkeypatch):
    worker, _ = engine()
    value = review(coverage_units=None, pending=[pending(basis="content_gap")])
    before, calls = deepcopy(value), []

    def plan(planner, request, finding, *, review_coverage_refresh=False):
        calls.append(deepcopy(finding))
        assert planner.client is worker.client and review_coverage_refresh
        assert finding["supports"] == value["available_supports"]
        return {"coverage_units": [unit()]}

    monkeypatch.setattr(OpenAIDraftEngine, "plan", plan)
    assert worker.prepare_units(question(), value) == [unit()]
    assert len(calls) == 1 and value == before
    assert calls[0]["missing"] == value["pending"]


def test_refresh_does_not_reopen_a_resolved_control_from_historical_source_state(monkeypatch):
    worker, _ = engine()
    closed = pending(check_key="pending-1", basis="content_gap", resolution=resolution())
    value = review(coverage_units=None, pending=[closed], source_checks=[{
        **closed, "resolution": {"status": "open"},
    }])
    before, calls = deepcopy(value), []

    def plan(planner, request, finding, *, review_coverage_refresh=False):
        calls.append(deepcopy(finding))
        return {"coverage_units": [unit()]}

    monkeypatch.setattr(OpenAIDraftEngine, "plan", plan)
    worker.prepare_units(question(), value)
    finding = calls[0]
    assert finding["missing"] == []
    assert finding["checks"][0]["resolution"] == {
        "status": "resolved", "kind": "human_decision", "decision": resolution(),
    }
    assert finding["human_decisions"] == [closed] and value == before


@pytest.mark.parametrize("gap", [
    {"kind": "clarification", "description": "Cotejar vigencia del reglamento.",
     "basis": "metadata_only", "reason_code": "validity"},
    {"kind": "clarification", "description": "Resolver contradicción entre dos versiones.",
     "basis": "content_gap", "reason_code": "applicability"},
    {"kind": "clarification", "description": "Cotejar transcripción del pasaje.",
     "basis": "content_gap", "reason_code": "transcription"},
    {"kind": "document", "description": "Preparar copia del archivo tras aprobar.",
     "basis": "explicit_fulfillment_request", "stage": "fulfillment",
     "blocks_approval": False},
])
def test_unit_refresh_preserves_legitimate_pending_without_closing_it(
    review_app, monkeypatch, gap,
):
    app, client, worker, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, _, row = prepare(app, client, pending=[gap])
    assert row["pending"]
    row["coverage_units"] = None
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")
    monkeypatch.setattr(worker, "prepare_units", lambda request, value: [
        unit(value["available_supports"][0])], raising=False)
    result = assess(app, client, case, row)
    assert result["pending"] == row["pending"]
    assert result["paragraphs"] == row["paragraphs"]
    assert all(p["resolution"] is None for p in result["pending"])
    if gap.get("stage") == "fulfillment":
        assert result["status"] == "ready"
    else:
        assert result["status"] == "needs_evidence"


def test_failed_plan_refresh_keeps_human_text_and_all_pending(review_app, monkeypatch):
    app, client, worker, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, _, row = prepare(app, client, pending=[{
        "kind": "clarification", "description": "Cotejar el alcance del registro.",
    }])
    row["coverage_units"] = None
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")

    def fail(request, value):
        raise DomainError("No se pudo reconstruir el inventario con las fuentes actuales.")

    monkeypatch.setattr(worker, "prepare_units", fail, raising=False)
    result = assess(app, client, case, row)
    assert result["status"] == "error" and result["coverage_units"] is None
    assert result["paragraphs"] == row["paragraphs"] and result["pending"] == row["pending"]
    assert result["assessment"] is None and worker.calls == 0


def test_edited_away_unit_cannot_reuse_old_approval(review_app, monkeypatch):
    app, client, worker, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, _, row = prepare(app, client)
    checked = assess(app, client, case, row)
    approved = approve(client, case, checked)
    assert approved.status_code == 200, approved.text
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] = "Texto que omite una condición material de la respuesta."
    saved = save(client, case, approved.json(), paragraphs=paragraphs).json()
    original = worker.assess

    def omitted(request, value):
        return {**original(request, value), "unit_checks": [
            unit_check(status="omitted", paragraph_indexes=[], explanation="Falta la condición.")
        ]}

    monkeypatch.setattr(worker, "assess", omitted)
    result = assess(app, client, case, saved)
    assert result["status"] == "needs_changes"
    assert "answer_unit_omitted" in {i["code"] for i in result["assessment"]["issues"]}
    assert approve(client, case, result).status_code == 409
    assert result["paragraphs"] == paragraphs and result["coverage_units"] == row["coverage_units"]


def test_source_change_during_refresh_discards_units_before_assessment(review_app, monkeypatch):
    app, client, worker, _ = review_app
    attach_plan_units(app, monkeypatch)
    case, source, row = prepare(app, client)
    row["coverage_units"] = None
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")
    entered, release = threading.Event(), threading.Event()

    def prepare_units(request, value):
        entered.set()
        assert release.wait(10)
        return [unit(value["available_supports"][0])]

    monkeypatch.setattr(worker, "prepare_units", prepare_units, raising=False)
    response = client.post(url(case, "/requests/P1/assess"), json={"revision": row["revision"]})
    assert response.status_code == 202 and entered.wait(5)
    app.state.library.review(source["id"], reviewed_by="Revisora", review_note="Cambio concurrente",
                             validity="current")
    release.set()
    finished = wait_review(app, client, case)
    assert finished["stale"] and finished["coverage_units"] is None
    assert finished["assessment"] is None and finished["approval"] is None and worker.calls == 0
    assert finished["paragraphs"] == row["paragraphs"]
