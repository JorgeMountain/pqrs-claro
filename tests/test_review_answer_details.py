"""Real Review graph/API with explicit provider doubles; no model or browser calls."""

import json
from copy import deepcopy

import pytest
import test_review_service_api as service_tests
from langgraph.checkpoint.memory import InMemorySaver
from test_answer_details import A, B, checks_for, word_range
from test_draft_service_api import ready_map
from test_review_answer_coverage import assessment, question, unit, unit_check
from test_review_engine import HASH, engine, review, support
from test_review_service_api import approve, assess, current, prepare, save, url

from pqrs_claro import review_service
from pqrs_claro.answer_coverage import DetailCheck, materialize_detailed_units
from pqrs_claro.review_graph import build_review_graph

review_app = service_tests.review_app
TEXT = f"La {A} o la {B} expide el informe, según el caso."
GENERIC = "El órgano correspondiente expide el informe, según el caso."


def detailed_unit(source, request=None, names=(A, B)):
    """Numeric provider selection materialized against the actual fixture source."""
    citation = {"chunk_id": "S1", "line_start": 1, "line_end": 1}
    details = [{
        "kind": "authority", "citation": citation,
        "members": [word_range(source["quote"], name)],
        "reason": "La identidad del emisor es necesaria para responder.",
    } for name in names]
    details.append({
        "kind": "alternatives", "citation": citation,
        "members": [word_range(source["quote"], name) for name in names],
        "reason": "Identifica opciones distintas, aplicables según el caso.",
    })
    proposal = {
        "requirement_id": "R1", "kind": "answer", "required": True,
        "claim": "El órgano correspondiente expide el informe.", "citations": [citation],
        "reason": "La petición requiere conocer al emisor.",
        "details": details, "no_details_reason": "",
    }
    return materialize_detailed_units(
        [proposal], request or question(), {source["chunk_id"]: source},
        {source["chunk_id"]: "S1"},
    )[0]


def value(text=TEXT):
    source = support(quote=TEXT)
    return review(
        available_supports=[source], coverage_units=[detailed_unit(source)],
        paragraphs=[{"text": text, "cited_chunk_ids": [source["chunk_id"]],
                     "cited_fact_ids": []}],
    )


def falsely_answered_checks(row):
    """A passing model selects literal generic prose instead of either required name."""
    evidence = {"paragraph_index": 0, "member_index": 1,
                **word_range(row["paragraphs"][0]["text"], row["paragraphs"][0]["text"])}
    return [DetailCheck.model_validate({
        "detail_id": f"U1-K{number}", "status": "answered",
        "evidence": [evidence] if number < 3 else [evidence, {**evidence, "member_index": 2}],
        "pending_indexes": [], "explanation": "El doble afirma erróneamente que está completo.",
    }).model_dump() for number in (1, 2, 3)]


def attach_details(app, monkeypatch):
    original_add = app.state.library.add

    def add(filename, data, **kwargs):
        # Preserve the fixture's normal creation, extraction, map and API lifecycle.
        if filename == "norma.txt":
            data = TEXT.encode()
        return original_add(filename, data, **kwargs)

    monkeypatch.setattr(app.state.library, "add", add)
    planner = app.state.drafts.engine
    original_plan, original_write = planner.plan, planner.write

    def plan(request, finding):
        return {**original_plan(request, finding),
                "coverage_units": [detailed_unit(finding["supports"][0], request)]}

    def write(request, finding, planned):
        result = original_write(request, finding, planned)
        result["paragraphs"][0]["text"] = TEXT
        return result

    monkeypatch.setattr(planner, "plan", plan)
    monkeypatch.setattr(planner, "write", write)
    reviewer = app.state.reviews.engine
    original_assess = reviewer.assess

    def check(request, row):
        checks = checks_for(row) if A in row["paragraphs"][0]["text"] else (
            falsely_answered_checks(row)
        )
        return {**original_assess(request, row), "unit_checks": [unit_check()],
                "detail_checks": checks}

    monkeypatch.setattr(reviewer, "assess", check)


def test_review_sends_aliased_detail_sources_and_current_numeric_text_without_mutation():
    row = value()
    expected = checks_for(row)
    provider = assessment(detail_checks=expected)
    provider.pop("local_checks")
    worker, calls = engine(provider)
    before = deepcopy(row)
    result = worker.assess(question(), row)
    assert result["status"] == "passed" and len(calls) == 1
    assert result["detail_checks"] == expected and row == before
    payload = json.loads(calls[0]["input"])
    sent = payload["review"]["coverage_units"][0]
    assert all(detail["citation"]["chunk_id"] == "S1" for detail in sent["details"])
    assert all(member["chunk_id"] == "S1" for detail in sent["details"]
               for member in detail["members"])
    assert [d["members"][0]["quote"] for d in sent["details"][:2]] == [A, B]
    assert payload["numbered_detail_paragraphs"][0]["paragraph_index"] == 0
    assert "procedure_scope_readings" not in payload


def test_review_rejects_false_answered_names_without_retrying_semantic_omission():
    row = value(GENERIC)
    provider = assessment(detail_checks=falsely_answered_checks(row))
    provider.pop("local_checks")
    worker, calls = engine(provider)
    result = worker.assess(question(), row)
    assert result["status"] == "needs_changes" and len(calls) == 1
    assert result["unit_checks"][0]["status"] == "answered"
    assert len([i for i in result["issues"] if i["code"] == "answer_detail_omitted"]) == 2
    assert row["paragraphs"][0]["text"] == GENERIC and row["pending"] == []


@pytest.mark.parametrize("detail_checks", ["falsely_answered", "missing"])
def test_graph_independently_blocks_missing_names_despite_passing_unit_and_provider(detail_checks):
    row = value(GENERIC)

    class Passing:
        def assess(self, request, saved):
            return assessment(detail_checks=(falsely_answered_checks(saved)
                                             if detail_checks == "falsely_answered" else []))

    graph = build_review_graph(Passing(), InMemorySaver())
    result = graph.invoke({"request": question(), "review": row, "input_hash": HASH},
                          {"configurable": {"thread_id": "named-details-required"}})
    assert result["assessment"]["status"] == "needs_changes"
    assert result["assessment"]["unit_checks"][0]["status"] == "answered"
    assert result["approval"] is None and "__interrupt__" not in result
    expected = "answer_detail_omitted" if detail_checks == "falsely_answered" else (
        "detail_review_incomplete"
    )
    assert expected in {i["code"] for i in result["assessment"]["issues"]}


def test_graph_cannot_replace_missing_names_with_nonblocking_fulfillment_pending():
    row = value(GENERIC)
    row["pending"] = [{
        "id": "fulfillment-copy", "kind": "document", "resolution": None,
        "description": "Preparar la copia al enviar la respuesta.",
        "basis": "explicit_fulfillment_request", "stage": "fulfillment",
        "blocks_approval": False,
    }]
    checks = [{
        "detail_id": detail["id"], "status": "pending", "evidence": [],
        "pending_indexes": [0], "explanation": "Quedaría para preparar la copia.",
    } for detail in row["coverage_units"][0]["details"]]
    before = deepcopy(row)

    class Passing:
        def assess(self, request, saved):
            return assessment(detail_checks=checks)

    result = build_review_graph(Passing(), InMemorySaver()).invoke(
        {"request": question(), "review": row, "input_hash": HASH},
        {"configurable": {"thread_id": "fulfillment-cannot-cover-content"}},
    )
    assert result["assessment"]["status"] == "needs_changes"
    assert "detail_review_invalid" in {i["code"] for i in result["assessment"]["issues"]}
    assert result["approval"] is None and "__interrupt__" not in result
    assert row == before and result["review"]["pending"] == before["pending"]


def test_graph_also_rejects_fulfillment_as_evidence_for_a_content_unit():
    row = value()
    row["pending"] = [{
        "id": "future-delivery", "kind": "document", "resolution": None,
        "description": "Preparar la entrega del documento.", "stage": "fulfillment",
        "blocks_approval": False, "basis": "explicit_fulfillment_request",
    }]
    before = deepcopy(row)

    class Passing:
        def assess(self, request, saved):
            return assessment(
                unit_checks=[unit_check(status="pending", paragraph_indexes=[],
                                        pending_indexes=[0])],
                detail_checks=checks_for(saved),
            )

    result = build_review_graph(Passing(), InMemorySaver()).invoke(
        {"request": question(), "review": row, "input_hash": HASH},
        {"configurable": {"thread_id": "fulfillment-cannot-cover-unit"}},
    )
    assert result["assessment"]["status"] == "needs_changes"
    assert {i["code"] for i in result["assessment"]["issues"]} == {"unit_review_invalid"}
    assert result["approval"] is None and "__interrupt__" not in result
    assert row == before and result["review"]["pending"] == before["pending"]


def test_review_without_details_does_not_duplicate_paragraphs_as_numbered_words():
    row = value()
    row["coverage_units"] = []
    provider = assessment(unit_checks=[])
    provider.pop("local_checks")
    worker, calls = engine(provider)
    assert worker.assess(question(), row)["status"] == "passed"
    assert len(calls) == 1
    payload = json.loads(calls[0]["input"])
    assert payload["numbered_detail_paragraphs"] == []
    assert payload["review"]["paragraphs"][0]["text"] == row["paragraphs"][0]["text"]


def test_full_review_prose_fits_original_context_budget_with_all_thirty_paragraphs():
    row = value()
    text = (TEXT + " " + "El trámite estaba en revisión. " * 300)[:6000]
    row["paragraphs"] = [{**row["paragraphs"][0], "text": text} for _ in range(30)]
    provider = assessment(detail_checks=checks_for(row))
    provider.pop("local_checks")
    worker, calls = engine(provider)
    before = deepcopy(row)
    result = worker.assess(question(), row)
    assert result["status"] == "passed" and len(calls) == 1
    assert len(calls[0]["input"]) <= 600000
    payload = json.loads(calls[0]["input"])
    assert len(payload["review"]["paragraphs"]) == 30
    assert all(p["text"] == text for p in payload["review"]["paragraphs"])
    assert [p["paragraph_index"] for p in payload["numbered_detail_paragraphs"]] == list(range(30))
    assert all(len(p["text"]) == 6000 for p in row["paragraphs"])
    assert payload["review"]["available_supports"][0]["quote"] == TEXT and row == before


def test_api_edited_names_cannot_reuse_approval_or_passing_unit_check(review_app, monkeypatch):
    app, client, _, _ = review_app
    attach_details(app, monkeypatch)
    case, _, row = prepare(app, client)
    accepted = approve(client, case, assess(app, client, case, row))
    assert accepted.status_code == 200, accepted.text
    accepted = accepted.json()
    snapshot = app.state.reviews.store.approval(accepted["approval"]["id"])
    assert snapshot["review"]["coverage_units"] == row["coverage_units"]
    assert snapshot["review"]["assessment"]["detail_checks"] == checks_for(row)
    edited = [{**row["paragraphs"][0], "text": GENERIC}]
    saved = save(client, case, accepted, paragraphs=edited)
    assert saved.status_code == 200, saved.text
    saved = saved.json()
    assert saved["assessment"] is None and saved["approval"] is None
    assert current(client, case)["paragraphs"] == edited
    assert current(client, case)["coverage_units"] == row["coverage_units"]
    assert approve(client, case, accepted).status_code == 409
    checked = assess(app, client, case, saved)
    assert checked["status"] == "needs_changes"
    assert checked["assessment"]["unit_checks"][0]["status"] == "answered"
    assert "answer_detail_omitted" in {i["code"] for i in checked["assessment"]["issues"]}
    assert approve(client, case, checked).status_code == 409
    assert checked["paragraphs"] == edited and checked["pending"] == row["pending"]
    assert snapshot == app.state.reviews.store.approval(accepted["approval"]["id"])


def test_api_legacy_detail_refresh_preserves_saved_text_and_legitimate_pending(
    review_app, monkeypatch,
):
    app, client, worker, _ = review_app
    attach_details(app, monkeypatch)
    gap = {"kind": "clarification", "description": "Cotejar vigencia de las dos versiones.",
           "basis": "content_gap", "reason_code": "applicability"}
    case, _, row = prepare(app, client, pending=[gap])
    original_units = deepcopy(row["coverage_units"])
    for current_unit in row["coverage_units"]:
        for key in ("details_version", "details", "no_details_reason"):
            current_unit.pop(key)
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")
    calls = []

    def refresh(request, saved):
        calls.append(deepcopy(saved))
        return [detailed_unit(saved["available_supports"][0], request)]

    monkeypatch.setattr(worker, "prepare_units", refresh, raising=False)
    checked = assess(app, client, case, row)
    assert len(calls) == 1 and worker.calls == 1
    assert checked["coverage_units"] == original_units
    assert checked["paragraphs"] == row["paragraphs"] and checked["pending"] == row["pending"]
    assert checked["status"] == "needs_evidence" and checked["approval"] is None
    assert all(p["resolution"] is None for p in checked["pending"])
    assert approve(client, case, checked).status_code == 409


def test_api_legacy_details_cannot_silently_skip_refresh(review_app, monkeypatch):
    app, client, worker, _ = review_app
    attach_details(app, monkeypatch)
    case, _, row = prepare(app, client)
    for current_unit in row["coverage_units"]:
        for key in ("details_version", "details", "no_details_reason"):
            current_unit.pop(key)
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")
    checked = assess(app, client, case, row)
    assert checked["status"] == "error" and worker.calls == 0
    assert checked["paragraphs"] == row["paragraphs"]
    assert checked["coverage_units"] == row["coverage_units"]
    assert checked["assessment"] is None and checked["approval"] is None
    assert approve(client, case, checked).status_code == 409


@pytest.mark.parametrize("legacy_kind,read_first,policy", [
    ("empty", True, "version"), ("empty", False, "details"),
    ("absent", True, "details"), ("absent", False, "version"),
])
def test_changed_policy_refreshes_empty_or_absent_legacy_inventory_even_on_direct_sync(
    review_app, monkeypatch, legacy_kind, read_first, policy,
):
    app, client, worker, _ = review_app
    gap = {"kind": "clarification", "description": "Cotejar aplicabilidad al caso actual.",
           "basis": "content_gap", "reason_code": "applicability"}
    case, _, row = prepare(app, client, pending=[gap])
    if legacy_kind == "absent":
        row.pop("coverage_units")
    else:
        row["coverage_units"] = []
    row = app.state.reviews.store.save(row, expected=row["revision"], event="synchronized")
    if policy == "version":
        monkeypatch.setattr(review_service, "REVIEW_VERSION", review_service.REVIEW_VERSION + 1)
    else:
        monkeypatch.setattr(review_service, "DETAIL_POLICY_HASH", "c" * 64)
    if read_first:
        projected = current(client, case)
        assert projected["stale"] and projected["coverage_units"] is None
        assert projected["paragraphs"] == row["paragraphs"]
        assert projected["pending"] == row["pending"]
    synced = client.post(url(case, "/start"), json={"version": case["version"]})
    assert synced.status_code == 200, synced.text
    synced = synced.json()["requests"][0]
    assert synced["coverage_units"] is None
    calls = []

    def refresh(request, saved):
        calls.append(deepcopy(saved))
        return [unit(saved["available_supports"][0])]

    original_assess = worker.assess

    def checked_units(request, saved):
        return {**original_assess(request, saved), "unit_checks": [unit_check()]}

    monkeypatch.setattr(worker, "prepare_units", refresh, raising=False)
    monkeypatch.setattr(worker, "assess", checked_units)
    checked = assess(app, client, case, synced)
    assert len(calls) == 1 and worker.calls == 1
    assert checked["coverage_units"][0]["details_version"] == 1
    assert checked["paragraphs"] == row["paragraphs"] and checked["pending"] == row["pending"]
    assert checked["status"] == "needs_evidence" and checked["approval"] is None


def test_current_empty_inventory_does_not_force_replanning(review_app, monkeypatch):
    app, client, worker, _ = review_app
    case, _, row = prepare(app, client)
    assert row["coverage_units"] == []

    def unexpected_refresh(*_):
        pytest.fail("A current empty inventory, such as copy-only content, remains valid")

    monkeypatch.setattr(worker, "prepare_units", unexpected_refresh, raising=False)
    checked = assess(app, client, case, row)
    assert checked["status"] == "ready" and checked["coverage_units"] == []
    assert checked["paragraphs"] == row["paragraphs"] and checked["pending"] == row["pending"]
    assert approve(client, case, checked).status_code == 200


def test_api_corrected_source_invalidates_detail_inventory_before_another_assessment(
    review_app, monkeypatch,
):
    app, client, _, _ = review_app
    attach_details(app, monkeypatch)
    case, source, row = prepare(app, client)
    accepted = approve(client, case, assess(app, client, case, row))
    assert accepted.status_code == 200, accepted.text
    replacement = app.state.library.add(
        "norma-corregida.txt", TEXT.replace(B, "Junta de Proyectos Abiertos").encode(),
        title=source["title"], category=source["category"], origin=source["origin"],
        document_id=source["document_id"],
    )
    assert replacement["version"] == source["version"] + 1
    # A normal API read observes invalidation; no browser reload claim is made here.
    stale = current(client, case)
    assert stale["stale"] and stale["coverage_units"] is None
    assert stale["assessment"] is None and stale["approval"] is None
    assert stale["paragraphs"] == row["paragraphs"] and stale["pending"] == row["pending"]
    assert approve(client, case, accepted.json()).status_code == 409
    ready_map(app, case)
    synced = client.post(url(case, "/start"), json={"version": case["version"]})
    assert synced.status_code == 200, synced.text
    current_row = synced.json()["requests"][0]
    assert current_row["coverage_units"] is None
    assert current_row["paragraphs"] == row["paragraphs"]


def test_api_revocation_hides_named_details_and_member_quotes_in_current_and_history(
    review_app, monkeypatch,
):
    app, client, _, _ = review_app
    attach_details(app, monkeypatch)
    case, _, row = prepare(app, client)
    library = app.state.library
    library.save_collection({"id": "detail-private", "title": "Colección de prueba"})
    library.link_collections(case["id"], ["detail-private"])
    names = ("Comisión Reservada Bruma", "Dirección Reservada Aurora")
    secret = f"La {names[0]} o la {names[1]} expide el informe, según el caso."
    source = library.add(
        "reservado.txt", secret.encode(), title="Fuente reservada", origin="Prueba",
        category="historical_attachment", collection_id="detail-private",
    )
    _, chunks = library.snapshot(case["id"], source_ids={source["id"]})
    private = {**chunks[0], "role": "antecedent", "origin_selection": "candidate"}
    row["available_supports"].append(private)
    request = {**question(), "allowed_collection_ids": ["detail-private"]}
    row["coverage_units"] = [detailed_unit(private, request, names)]
    row["request_snapshot"]["allowed_collection_ids"] = ["detail-private"]
    row = app.state.reviews.store.save(row, expected=row["revision"], event="edited")
    history_url = url(case, "/requests/P1/history")
    assert names[0] in client.get(history_url).text
    changed = client.put(f"/api/cases/{case['id']}/source-collections",
                         json={"collection_ids": []})
    assert changed.status_code == 200 and changed.json()["scope_reduced"]
    for path in (url(case), history_url, f"/api/cases/{case['id']}/office/workspace"):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert all(name not in response.text for name in names)
        assert source["id"] not in response.text
    visible = current(client, case)
    assert not visible["coverage_units"] and visible["assessment"] is None
    assert visible["approval"] is None and approve(client, case, row).status_code == 409


def test_graph_requires_refresh_for_readable_legacy_units_before_new_approval():
    row = value()
    row["coverage_units"] = [unit(row["available_supports"][0])]
    for key in ("details_version", "details", "no_details_reason"):
        row["coverage_units"][0].pop(key)

    class Passing:
        def assess(self, request, saved):
            return assessment()

    result = build_review_graph(Passing(), InMemorySaver()).invoke(
        {"request": question(), "review": row, "input_hash": HASH},
        {"configurable": {"thread_id": "legacy-details-refresh-required"}},
    )
    assert result["assessment"]["status"] == "needs_changes"
    assert "detail_inventory_stale" in {i["code"] for i in result["assessment"]["issues"]}
    assert result["approval"] is None and "__interrupt__" not in result
