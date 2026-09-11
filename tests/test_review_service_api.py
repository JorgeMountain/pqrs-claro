"""Durabilidad y límites fase 6: API/SQLite/LangGraph reales y proveedor doble."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_draft_service_api import FakeDraftEngine, generate, prepared_case, ready_map

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.models import DomainError
from pqrs_claro.review_engine import structural_checks, validate_review_input
from pqrs_claro.review_service import ReviewService, input_hash


class FakeReviewEngine:
    """No llama a OpenAI ni pretende comprobar suficiencia semántica real."""

    def __init__(self, *, fail_once=False, block=False, changes=False):
        self.calls = 0
        self.fail_once, self.block, self.changes = fail_once, block, changes
        self.entered, self.release = threading.Event(), threading.Event()

    def assess(self, request, review):
        self.calls += 1
        if self.block:
            self.block = False
            self.entered.set()
            assert self.release.wait(10)
        if self.fail_once and self.calls == 1:
            raise DomainError("Fallo ficticio recuperable.")
        checks, issues = structural_checks(validate_review_input(request, review))
        if self.changes:
            issues.append(
                dict(
                    code="unsupported",
                    description="Hallazgo semántico simulado.",
                    paragraph_index=0,
                )
            )
        return dict(
            status="needs_changes" if issues else "passed", issues=issues, local_checks=checks
        )


@pytest.fixture
def review_app(tmp_path):
    engine = FakeReviewEngine()
    settings = Settings(data_dir=tmp_path / "data", model="test-model", api_key="")
    app = create_app(settings, draft_engine=FakeDraftEngine(), review_engine=engine)
    with TestClient(app) as client:
        yield app, client, engine, settings


def url(case, tail=""):
    return f"/api/cases/{case['id']}/review{tail}"


def wait_drafts(app, client, case):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if case["id"] not in app.state.drafts.active:
            return client.get(f"/api/cases/{case['id']}/drafts").json()
        time.sleep(0.01)
    pytest.fail("Los borradores de prueba no terminaron")


def prepare(app, client, *, count=1, pending=None):
    case, source = prepared_case(app, count=count)
    if pending:
        run = app.state.library.latest_run(case["id"])
        for finding in run["results"]:
            finding["missing"] = pending
        app.state.library.save_run(run)
    assert generate(client, case).status_code == 202
    assert wait_drafts(app, client, case)["status"] in {"ready", "partial"}
    response = client.post(url(case, "/start"), json={"version": case["version"]})
    assert response.status_code == 200, response.text
    return case, source, response.json()["requests"][0]


def current(client, case, request_id="P1"):
    return next(
        row for row in client.get(url(case)).json()["requests"] if row["request_id"] == request_id
    )


def save(client, case, row, *, paragraphs=None, resolutions=None):
    return client.put(
        url(case, f"/requests/{row['request_id']}"),
        json={
            "revision": row["revision"],
            "edited_by": "Revisora ficticia",
            "paragraphs": row["paragraphs"] if paragraphs is None else paragraphs,
            "pending_resolutions": resolutions or [],
        },
    )


def wait_review(app, client, case, request_id="P1"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (case["id"], request_id) not in app.state.reviews.active:
            return current(client, case, request_id)
        time.sleep(0.01)
    pytest.fail("La comprobación no terminó")


def assess(app, client, case, row):
    response = client.post(
        url(case, f"/requests/{row['request_id']}/assess"), json={"revision": row["revision"]}
    )
    assert response.status_code == 202, response.text
    return wait_review(app, client, case, row["request_id"])


def approve(client, case, row, **changes):
    body = dict(
        revision=row["revision"],
        assessment_hash=(row.get("assessment") or {}).get("input_hash", "0" * 64),
        approved_by="Responsable ficticia",
        note="Aprobación explícita de un ejemplo aislado.",
        confirmed=True,
    )
    body.update(changes)
    return client.post(url(case, f"/requests/{row['request_id']}/approve"), json=body)


def fact(client, case, row, **changes):
    body = dict(
        revision=row["revision"],
        text="Observé el estado del caso ficticio.",
        author="Responsable ficticia",
        basis="Consulté el registro ficticio directamente.",
        observed_at="2026-09-07",
    )
    body.update(changes)
    return client.post(url(case, f"/requests/{row['request_id']}/facts"), json=body)


def test_start_requires_current_complete_drafts_and_preserves_case(review_app):
    app, client, engine, _ = review_app
    case, _ = prepared_case(app)
    before = app.state.store.get(case["id"])
    assert client.get(url(case)).json()["status"] == "idle"
    assert client.post(url(case, "/start"), json={"version": case["version"]}).status_code == 409
    assert generate(client, case).status_code == 202
    wait_drafts(app, client, case)
    response = client.post(url(case, "/start"), json={"version": case["version"]})
    rows = response.json()["requests"]
    assert response.status_code == 200 and len(rows) == 2
    assert rows[0]["revision"] == 1 and rows[0]["edited_by"] is None
    assert rows[0]["available_supports"][0]["origin_selection"] == "automatic"
    assert (
        client.post(url(case, "/start"), json={"version": case["version"]}).json()["requests"]
        == rows
    )
    assert app.state.store.get(case["id"]) == before and engine.calls == 0


def test_edit_invalidate_check_and_approval_noop_preserves_and_history_immutable(review_app):
    app, client, engine, _ = review_app
    case, _, row = prepare(app, client)
    row = assess(app, client, case, row)
    assert row["status"] == "ready", row
    assert row["assessment"]["input_hash"] == input_hash(row)
    response = approve(client, case, row)
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved"
    snapshot = client.get(url(case, "/approved")).json()
    assert snapshot["status"] == "approved"
    no_op = save(client, case, approved).json()
    assert no_op == approved
    explicit_default = deepcopy(approved["paragraphs"])
    explicit_default[0]["office_section"] = "response"
    assert save(client, case, approved, paragraphs=explicit_default).json() == approved
    paragraphs = deepcopy(approved["paragraphs"])
    paragraphs[0]["text"] += " Texto humano añadido."
    changed = save(client, case, approved, paragraphs=paragraphs).json()
    assert changed["status"] == "editing" and not changed["assessment"] and not changed["approval"]
    assert client.get(url(case, "/approved")).status_code == 409
    assert approve(client, case, approved).status_code == 409
    restored = save(client, case, changed, paragraphs=approved["paragraphs"]).json()
    assert not restored["approval"] and not restored["assessment"]
    assert (
        app.state.reviews.store.approval(approved["approval"]["id"])["snapshot_hash"]
        == snapshot["requests"][0]["snapshot_hash"]
    )
    history = client.get(url(case, "/requests/P1/history")).json()["revisions"]
    assert history[0]["event"] == "edited" and history[0]["actor"] == "Revisora ficticia"
    assert any(h["body"]["approval"] for h in history)
    assert engine.calls == 1


def test_office_section_change_invalidates_approval_and_preserves_previous_snapshot(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    row = approve(client, case, assess(app, client, case, row)).json()
    snapshot = client.get(url(case, "/approved")).json()
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["office_section"] = "context"
    changed = save(client, case, row, paragraphs=paragraphs).json()
    assert changed["status"] == "editing"
    assert changed["paragraphs"][0]["office_section"] == "context"
    assert changed["paragraphs"][0]["text"] == row["paragraphs"][0]["text"]
    assert changed["approval"] is None and changed["assessment"] is None
    assert client.get(url(case, "/approved")).status_code == 409
    assert (
        app.state.reviews.store.approval(row["approval"]["id"])["snapshot_hash"]
        == (snapshot["requests"][0]["snapshot_hash"])
    )


@pytest.mark.parametrize(
    "change,value",
    [
        ("confirmed", False),
        ("confirmed", "true"),
        ("approved_by", " "),
        ("assessment_hash", "invalid"),
    ],
)
def test_approval_requires_explicit_valid_confirmation(review_app, change, value):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    row = assess(app, client, case, row)
    assert approve(client, case, row, **{change: value}).status_code == 422
    assert current(client, case)["approval"] is None


@pytest.mark.parametrize("mode", ["unassessed", "bad_hash", "pending", "changes", "empty"])
def test_approval_never_bypasses_pending_failed_check_or_missing_graph(review_app, mode):
    app, client, engine, _ = review_app
    pending = [dict(kind="fact", description="Falta un hecho.")] if mode == "pending" else None
    case, _, row = prepare(app, client, pending=pending)
    engine.changes = mode == "changes"
    if mode == "empty":
        row = save(client, case, row, paragraphs=[]).json()
    if mode != "unassessed":
        row = assess(app, client, case, row)
    response = approve(
        client, case, row, **({"assessment_hash": "0" * 64} if mode == "bad_hash" else {})
    )
    assert response.status_code == 409, response.text
    assert current(client, case)["approval"] is None


def test_parallel_edits_use_optimistic_revision(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)

    def change(text):
        paragraphs = deepcopy(row["paragraphs"])
        paragraphs[0]["text"] = text
        return save(client, case, row, paragraphs=paragraphs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(change, ["Primera edición humana.", "Otra edición humana."]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert current(client, case)["revision"] == row["revision"] + 1


def test_written_fact_attributed_and_removal_preserves_dangling_text_and_history(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    response = fact(client, case, row)
    assert response.status_code == 201, response.text
    row = response.json()
    contribution = row["facts"][0]
    assert contribution["author"] == "Responsable ficticia" and len(contribution["sha256"]) == 64
    paragraphs = [
        {
            "text": "Según la responsable ficticia, el estado fue observado el 7 de septiembre.",
            "cited_chunk_ids": [],
            "cited_fact_ids": [contribution["id"]],
        }
    ]
    row = save(client, case, row, paragraphs=paragraphs).json()
    row = assess(app, client, case, row)
    assert row["status"] == "ready", row
    response = client.request(
        "DELETE",
        url(case, f"/requests/P1/facts/{contribution['id']}"),
        json={"revision": row["revision"], "edited_by": "Revisora ficticia"},
    )
    assert response.status_code == 200, response.text
    row = response.json()
    assert not row["facts"] and row["paragraphs"] == paragraphs and not row["assessment"]
    assert save(client, case, row).status_code == 200
    row = assess(app, client, case, row)
    assert row["status"] == "needs_changes" and any(
        i["code"] == "current_references" for i in row["assessment"]["issues"]
    )
    assert any(
        h["body"]["facts"]
        for h in client.get(url(case, "/requests/P1/history")).json()["revisions"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("author", " "),
        ("basis", ""),
        ("observed_at", "ayer"),
        ("observed_at", "2026-02-30"),
        ("assessment", {}),
    ],
)
def test_fact_requires_attribution_and_rejects_extra_fields(review_app, field, value):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    assert fact(client, case, row, **{field: value}).status_code == 422
    assert not current(client, case)["facts"]


def test_pending_ids_dedup_exact_server_control_and_document_cannot_use_fact_only(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(
        app,
        client,
        pending=[
            dict(kind="document", description="Falta el acta."),
            dict(kind="document", description=" Falta el acta. "),
        ],
    )
    assert len(row["pending"]) == 1
    identifier = row["pending"][0]["id"]
    row = fact(client, case, row).json()
    decision = dict(
        pending_id=identifier,
        action="resolved",
        note="Lo digo yo.",
        cited_chunk_ids=[],
        cited_fact_ids=[row["facts"][0]["id"]],
    )
    assert save(client, case, row, resolutions=[decision]).status_code == 422
    decision.update(action="not_applicable", note="")
    assert save(client, case, row, resolutions=[decision]).status_code == 422
    decision.update(note="Duplicidad identificada con el documento ya solicitado.")
    changed = save(client, case, row, resolutions=[decision]).json()
    assert changed["pending"][0]["resolution"]["by"] == "Revisora ficticia"
    assert changed["assessment"] is None and changed["status"] == "editing"
    invalid = {**decision, "pending_id": "inventado"}
    assert save(client, case, changed, resolutions=[invalid]).status_code == 422
    response = client.put(
        url(case, "/requests/P1"),
        json=dict(
            revision=changed["revision"],
            edited_by="Revisora",
            paragraphs=changed["paragraphs"],
            pending=[],
        ),
    )
    assert response.status_code == 422


@pytest.mark.parametrize("change", ["review", "original", "version"])
def test_source_change_latches_stale_and_sync_keeps_human_work(review_app, change):
    app, client, _, _ = review_app
    case, source, row = prepare(app, client)
    row = fact(client, case, row).json()
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] = "Edición humana que debe conservarse."
    row = save(client, case, row, paragraphs=paragraphs).json()
    row = assess(app, client, case, row)
    row = approve(client, case, row).json()
    if change == "review":
        app.state.library.review(
            source["id"], reviewed_by="Revisora", review_note="Nueva revisión", validity="current"
        )
    elif change == "version":
        app.state.library.add(
            "norma.txt",
            b"Version nueva de la norma ficticia.",
            title="Norma ficticia",
            category="institutional_norm",
            origin="Prueba",
            document_id=source["document_id"],
        )
    else:
        path = app.state.library.original(source["id"])
        original = path.read_bytes()
        path.write_bytes(b"Bytes alterados")
    stale = current(client, case)
    assert stale["stale"] and stale["status"] == "stale" and stale["approval"] is None
    assert stale["paragraphs"] == paragraphs and stale["facts"] == row["facts"]
    assert client.get(url(case, "/approved")).status_code == 409
    if change == "original":
        path.write_bytes(original)
        assert current(client, case)["stale"]
    ready_map(app, case)
    synced = client.post(url(case, "/start"), json={"version": case["version"]}).json()["requests"][
        0
    ]
    assert not synced["stale"] and synced["status"] == "editing"
    assert synced["paragraphs"] == paragraphs and synced["facts"] == row["facts"]
    assert synced["assessment"] is None and synced["approval"] is None


def test_midflight_edit_discards_old_assessment_without_overwriting_text(review_app):
    app, client, engine, _ = review_app
    case, _, row = prepare(app, client)
    engine.block = True
    response = client.post(url(case, "/requests/P1/assess"), json={"revision": row["revision"]})
    assert response.status_code == 202
    try:
        assert engine.entered.wait(5)
        checking = current(client, case)
        assert checking["status"] == "checking"
        assert (
            client.post(
                url(case, "/requests/P1/assess"), json={"revision": checking["revision"]}
            ).status_code
            == 409
        )
        paragraphs = deepcopy(checking["paragraphs"])
        paragraphs[0]["text"] = "Cambio mientras se evalúa; no sobrescribir."
        changed = save(client, case, checking, paragraphs=paragraphs).json()
    finally:
        engine.release.set()
    final = wait_review(app, client, case)
    assert final == changed and final["assessment"] is None
    assert assess(app, client, case, final)["status"] == "ready"
    assert engine.calls == 2


def test_source_change_during_check_stales_result(review_app):
    app, client, engine, _ = review_app
    case, source, row = prepare(app, client)
    engine.block = True
    client.post(url(case, "/requests/P1/assess"), json={"revision": row["revision"]})
    try:
        assert engine.entered.wait(5)
        app.state.library.review(
            source["id"], reviewed_by="Revisora", review_note="Cambió", validity="current"
        )
    finally:
        engine.release.set()
    final = wait_review(app, client, case)
    assert final["status"] == "stale" and not final["assessment"]


def test_restart_preserves_interrupt_and_approved_snapshot_without_model_recall(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", model="test-model")
    first_engine = FakeReviewEngine()
    app = create_app(settings, draft_engine=FakeDraftEngine(), review_engine=first_engine)
    with TestClient(app) as client:
        case, _, row = prepare(app, client)
        ready = assess(app, client, case, row)
        assert ready["status"] == "ready", ready
    second_engine = FakeReviewEngine()
    reopened = create_app(settings, review_engine=second_engine)
    with TestClient(reopened) as client:
        assert current(client, case) == ready
        response = approve(client, case, ready)
        assert response.status_code == 200, response.text
        approved = client.get(url(case, "/approved")).json()
        assert second_engine.calls == 0
    third = create_app(settings, review_engine=FakeReviewEngine())
    with TestClient(third) as client:
        assert client.get(url(case, "/approved")).json() == approved


def test_interrupted_check_recovers_and_can_retry_without_text_loss(review_app):
    app, client, engine, _ = review_app
    case, _, row = prepare(app, client)
    engine.fail_once = True
    failed = assess(app, client, case, row)
    assert failed["status"] == "error" and failed["paragraphs"] == row["paragraphs"]
    failed["status"] = "checking"
    stored = app.state.reviews.store.save(failed, expected=failed["revision"], event="test_cut")
    app.state.reviews.recover()
    recovered = current(client, case)
    assert recovered["status"] == "error" and recovered["revision"] > stored["revision"]
    assert assess(app, client, case, recovered)["status"] == "ready"


def test_full_case_approval_requires_every_current_request_and_hides_removed_requests(review_app):
    app, client, _, _ = review_app
    case, _, _ = prepare(app, client, count=2)
    first = assess(app, client, case, current(client, case))
    assert approve(client, case, first).status_code == 200
    assert client.get(url(case, "/approved")).status_code == 409
    second = assess(app, client, case, current(client, case, "P2"))
    assert approve(client, case, second).status_code == 200
    assert client.get(url(case, "/approved")).status_code == 200
    identification = deepcopy(case["identification"])
    identification["requests"] = [identification["requests"][1]]
    case = app.state.store.update(case["id"], identification=identification)
    current_review = client.get(url(case)).json()
    assert [row["request_id"] for row in current_review["requests"]] == ["P2"]
    assert current_review["status"] == "stale"
    assert client.get(url(case, "/requests/P1/history")).status_code == 200


def test_unknown_citations_extra_approval_fields_and_cross_case_fact_are_rejected(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    other, _, other_row = prepare(app, client)
    foreign = fact(client, other, other_row).json()["facts"][0]["id"]
    row = current(client, case)
    for field, value in (("cited_chunk_ids", "foreign-chunk"), ("cited_fact_ids", foreign)):
        paragraphs = deepcopy(row["paragraphs"])
        paragraphs[0][field] = [value]
        assert save(client, case, row, paragraphs=paragraphs).status_code == 422
    response = client.put(
        url(case, "/requests/P1"),
        json=dict(
            revision=row["revision"],
            edited_by="Revisora",
            paragraphs=row["paragraphs"],
            approval={"approved_by": "fake"},
        ),
    )
    assert response.status_code == 422


def test_provider_error_does_not_expose_raw_data(review_app):
    app, client, engine, _ = review_app
    case, _, row = prepare(app, client)

    def fail(*_):
        raise ValueError("secret-provider-response")

    engine.assess = fail
    final = assess(app, client, case, row)
    assert final["status"] == "error" and "secret-provider" not in str(final)


def test_stale_human_edit_and_fact_remain_saveable_without_allowing_assessment(review_app):
    app, client, _, _ = review_app
    case, source, row = prepare(app, client)
    app.state.library.review(
        source["id"], reviewed_by="Responsable", review_note="Cambio", validity="current"
    )
    row = current(client, case)
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] += " Edición guardada con fuentes por actualizar."
    changed = save(client, case, row, paragraphs=paragraphs)
    assert changed.status_code == 200, changed.text
    row = changed.json()
    assert row["stale"] and row["status"] == "stale"
    row = fact(client, case, row).json()
    assert row["facts"] and row["stale"]
    assert (
        client.post(
            url(case, "/requests/P1/assess"), json={"revision": row["revision"]}
        ).status_code
        == 409
    )
    ready_map(app, case)
    synced = client.post(url(case, "/start"), json={"version": case["version"]}).json()["requests"][
        0
    ]
    assert (
        synced["status"] == "editing"
        and synced["paragraphs"] == paragraphs
        and synced["facts"] == row["facts"]
    )


def test_pending_decision_requires_current_sources_but_reopen_remains_available(review_app):
    app, client, _, _ = review_app
    case, source, row = prepare(
        app, client, pending=[dict(kind="document", description="Falta el acta.")]
    )
    decision = dict(
        pending_id=row["pending"][0]["id"], action="not_applicable",
        note="Ya se solicitó en otro numeral.", cited_chunk_ids=[], cited_fact_ids=[],
    )
    saved = save(client, case, row, resolutions=[decision]).json()
    assert saved["paragraphs"] == row["paragraphs"]
    assert saved["pending"][0]["resolution"]["action"] == "not_applicable"
    app.state.library.review(
        source["id"], reviewed_by="Responsable", review_note="Cambio", validity="current"
    )
    saved = current(client, case)
    rejected = save(client, case, saved, resolutions=[decision])
    assert rejected.status_code == 409
    assert "Las fuentes cambiaron" in rejected.json()["detail"]
    decision.update(action="open", note="")
    reopened = save(client, case, saved, resolutions=[decision])
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["pending"][0]["resolution"] is None
    assert reopened.json()["paragraphs"] == row["paragraphs"]


def test_cut_after_graph_approval_recovers_same_decision_without_provider_recall(
    review_app, monkeypatch
):
    app, client, engine, _ = review_app
    case, _, row = prepare(app, client)
    row = assess(app, client, case, row)
    real_save = app.state.reviews.store.save

    def cut(value, **kwargs):
        if kwargs["event"] == "approved":
            monkeypatch.setattr(app.state.reviews.store, "save", real_save)
            raise RuntimeError("Corte simulado después de reanudar el grafo")
        return real_save(value, **kwargs)

    monkeypatch.setattr(app.state.reviews.store, "save", cut)
    with pytest.raises(RuntimeError, match="Corte simulado"):
        approve(client, case, row)
    assert current(client, case)["status"] == "ready"
    assert approve(client, case, row, approved_by="Otra persona").status_code == 409
    recovered = approve(client, case, row)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "approved" and engine.calls == 1
    assert client.get(url(case, "/approved")).status_code == 200


def test_explicit_reassessment_replaces_old_interrupt(review_app):
    app, client, engine, _ = review_app
    case, _, row = prepare(app, client)
    first = assess(app, client, case, row)
    second = assess(app, client, case, first)
    assert second["status"] == "ready" and engine.calls == 2
    assert second["check_thread_id"] != first["check_thread_id"]
    assert approve(client, case, first).status_code == 409
    assert approve(client, case, second).status_code == 200


def test_reopening_pending_ignores_references_to_retired_fact(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(
        app, client, pending=[dict(kind="fact", description="Confirmar el dato.")]
    )
    row = fact(client, case, row).json()
    identifier = row["facts"][0]["id"]
    decision = dict(
        pending_id=row["pending"][0]["id"],
        action="resolved",
        note="Aporte atribuido.",
        cited_chunk_ids=[],
        cited_fact_ids=[identifier],
    )
    row = save(client, case, row, resolutions=[decision]).json()
    row = client.request(
        "DELETE",
        url(case, f"/requests/P1/facts/{identifier}"),
        json={"revision": row["revision"], "edited_by": "Revisora"},
    ).json()
    response = save(client, case, row, resolutions=[{**decision, "action": "open"}])
    assert response.status_code == 200, response.text
    assert response.json()["pending"][0]["resolution"] is None


def test_candidate_added_during_sync_can_be_explicitly_cited_to_resolve_document(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(
        app, client, pending=[dict(kind="document", description="Falta el acta del caso.")]
    )
    row = fact(client, case, row).json()
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] = "Texto humano conservado para la revisión del acta."
    row = save(client, case, row, paragraphs=paragraphs).json()
    attachment = app.state.library.add(
        "acta.txt",
        b"Acta ficticia del caso: estado observado.",
        title="Acta del caso",
        category="case_evidence",
        origin="Prueba explícita",
        case_id=case["id"],
    )
    run = ready_map(app, case)
    _, _, chunks, _ = app.state.sources.inputs(case["id"])
    chunk = next(item for item in chunks if item["source_id"] == attachment["id"])
    finding = run["results"][0]
    norm = next(item for item in chunks if item["category"] == "institutional_norm")
    finding["supports"] = [{**norm, "role": "rule", "reason": "Norma ficticia de prueba."}]
    finding["candidate_documents"] = [
        {
            **{
                key: chunk[key]
                for key in ("source_id", "document_id", "version", "title", "filename", "category")
            },
            "selected_as_support": False,
            "chunks": [
                {
                    key: chunk[key]
                    for key in (
                        "chunk_id",
                        "page",
                        "line_start",
                        "line_end",
                        "quote",
                        "location_kind",
                    )
                }
            ],
        }
    ]
    finding["missing"] = [
        dict(kind="clarification", description="Precisar el alcance de la nueva acta.")
    ]
    app.state.library.save_run(run)
    synced = client.post(url(case, "/start"), json={"version": case["version"]}).json()["requests"][
        0
    ]
    assert synced["paragraphs"] == paragraphs and synced["facts"] == row["facts"]
    candidate = next(s for s in synced["available_supports"] if s["source_id"] == attachment["id"])
    assert candidate["origin_selection"] == "candidate" and candidate["quote"] == chunk["quote"]
    assert len(synced["pending"]) == 1
    assert synced["pending"][0]["description"] == "Precisar el alcance de la nueva acta."
    assert synced["pending"][0]["id"] != row["pending"][0]["id"]
    history = client.get(url(case, "/requests/P1/history")).json()["revisions"]
    assert any(revision["body"]["pending"] == row["pending"] for revision in history)
    decisions = [
        dict(
            pending_id=item["id"],
            action="resolved",
            note="Archivo ficticio aportado y cotejado para esta prueba.",
            cited_chunk_ids=[chunk["chunk_id"]],
            cited_fact_ids=[],
        )
        for item in synced["pending"]
    ]
    paragraphs[0]["cited_chunk_ids"] = [chunk["chunk_id"]]
    saved = save(client, case, synced, paragraphs=paragraphs, resolutions=decisions).json()
    assessed = assess(app, client, case, saved)
    assert assessed["status"] == "ready", assessed
    assert approve(client, case, assessed).status_code == 200


@pytest.mark.parametrize("changed", [None, "scope_key", "source_versions", "description"])
def test_sync_reuses_resolution_only_for_same_check_scope_and_version(changed):
    request = {"id": "P1", "description": "Aclarar el periodo del antecedente."}
    item = {
        "kind": "clarification",
        "description": "Cotejar el periodo del antecedente.",
        "check_key": "check-one",
        "id": "check-one",
        "reason_code": "applicability",
        "stage": "evidence",
        "state": "confirmation_pending",
        "scope_key": "scope-1",
        "request_ids": ["P1"],
        "linked_source_ids": ["source-1"],
        "linked_chunk_ids": ["chunk-1"],
        "source_versions": [{"source_id": "source-1", "version": 1}],
        "resolution": {"status": "open"},
    }
    finding = {"request_id": "P1", "supports": [], "missing": [item]}
    first = ReviewService._pending([], finding, request=request)
    resolution = {
        "action": "resolved",
        "note": "Se cotejó el periodo de este pasaje.",
        "cited_chunk_ids": ["chunk-1"],
        "cited_fact_ids": [],
        "by": "Responsable ficticia",
        "at": "2026-09-09T12:00:00Z",
    }
    first[0]["resolution"] = resolution
    if changed:
        item[changed] = {
            "scope_key": "scope-2",
            "description": "Cotejar otro hecho del antecedente.",
            "source_versions": [{"source_id": "source-1", "version": 2}],
        }[changed]
    second = ReviewService._pending(first, finding, request=request)
    assert second[0]["resolution"] == (None if changed else resolution)
    assert second[0]["linked_source_ids"] == ["source-1"]
    assert second[0]["source_versions"] == item["source_versions"]


def test_sync_drops_resolved_source_check_even_if_old_draft_proposes_it_again():
    item = {
        "kind": "fact",
        "description": "Confirmar el periodo.",
        "check_key": "check-one",
        "id": "check-one",
        "stage": "evidence",
        "scope_key": "scope-1",
        "resolution": {"status": "resolved"},
    }
    finding = {"request_id": "P1", "missing": [], "checks": [item]}
    old = [{**item, "resolution": None, "origins": ["draft"]}]
    assert ReviewService._pending(old, finding, {"pending": [item]}) == []


def test_future_signature_does_not_block_content_approval_or_claim_completion(review_app):
    app, client, _, _ = review_app
    action = dict(
        kind="clarification",
        description="Tramitar la firma de la respuesta aprobada.",
        stage="fulfillment",
        blocks_approval=False,
    )
    case, _, row = prepare(app, client, pending=[action])
    assessed = assess(app, client, case, row)
    assert assessed["status"] == "ready"
    assert assessed["pending"][0]["resolution"] is None
    result = approve(client, case, assessed)
    assert result.status_code == 200, result.text
    approved = result.json()
    assert approved["pending"][0]["resolution"] is None
    assert approved["paragraphs"] == row["paragraphs"]


def test_parent_context_reaches_draft_engine_and_review_snapshot(review_app):
    app, client, _, _ = review_app
    case, _ = prepared_case(app, count=2)
    identification = deepcopy(case["identification"])
    identification["requests"][0].update(
        title="Profesor del programa", description="Informar sobre la profesora Ana en 2015."
    )
    identification["requests"][1].update(
        parent_id="P1", description="Confirmar si figuró como titular ese semestre."
    )
    case = app.state.store.update(case["id"], identification=identification)
    ready_map(app, case)
    seen = []
    original_visit = app.state.drafts.engine.visit

    def capture(phase, request):
        seen.append((phase, deepcopy(request)))
        original_visit(phase, request)

    app.state.drafts.engine.visit = capture
    assert generate(client, case).status_code == 202
    wait_drafts(app, client, case)
    child_calls = [request for _, request in seen if request["id"] == "P2"]
    assert len(child_calls) == 3
    for request in child_calls:
        assert (
            request["context"]["ancestors"][0]["description"]
            == (identification["requests"][0]["description"])
        )
    response = client.post(url(case, "/start"), json={"version": case["version"]})
    assert response.status_code == 200, response.text
    child = next(row for row in response.json()["requests"] if row["request_id"] == "P2")
    assert child["request_snapshot"]["context"] == child_calls[0]["context"]
