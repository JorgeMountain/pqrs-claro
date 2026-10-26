"""Fase 5: API y grafo reales, motores dobles explícitos y archivos temporales."""

import threading
import time
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.models import DomainError
from pqrs_claro.storage import now


class FakeDraftEngine:
    """Doble observable: ningún resultado de estas pruebas procede de OpenAI."""

    def __init__(self, *, fail_once=None, block=None, pending=False, bad_checks=False):
        self.calls = Counter()
        self.fail_once, self.block = fail_once, block
        self.pending, self.bad_checks = pending, bad_checks
        self.entered, self.release = threading.Event(), threading.Event()

    def visit(self, phase, request):
        key = (request["id"], phase)
        self.calls[key] += 1
        if self.block == key:
            self.block = None
            self.entered.set()
            assert self.release.wait(10), "Faltó liberar el motor doble"
        if self.fail_once == key and self.calls[key] == 1:
            raise DomainError("Fallo transitorio ficticio; avance conservado.")

    def plan(self, request, finding):
        self.visit("plan", request)
        return {
            "objective": request["description"],
            "points": [
                {
                    "description": "Plan ficticio",
                    "cited_chunk_ids": [s["chunk_id"] for s in finding["supports"]],
                }
            ],
        }

    def write(self, request, finding, plan):
        self.visit("write", request)
        return {
            "status": "needs_evidence" if self.pending else "needs_review",
            "paragraphs": [
                {
                    "text": "Borrador ficticio atribuido al soporte.",
                    "cited_chunk_ids": [s["chunk_id"] for s in finding["supports"]],
                }
            ],
            "pending": [{"kind": "fact", "description": "Confirmar el hecho del caso."}]
            if self.pending
            else [],
        }

    def check(self, request, finding, plan, draft):
        self.visit("check", request)
        return {
            "status": "needs_changes" if self.bad_checks else "passed",
            "issues": [
                {
                    "code": "missing_fact",
                    "description": "Falta contrastar un hecho.",
                    "paragraph_index": 0,
                }
            ]
            if self.bad_checks
            else [],
            "local_checks": [{"code": "test", "passed": True, "description": "Doble explícito"}],
        }


@pytest.fixture
def draft_app(tmp_path):
    engine = FakeDraftEngine()
    settings = Settings(data_dir=tmp_path / "data", model="test-model", api_key="")
    app = create_app(settings, draft_engine=engine)
    with TestClient(app) as client:
        yield app, client, engine, settings


def prepared_case(app, *, confirmed=True, with_map=True, count=2):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 80), "Solicito los requisitos institucionales.")
        case = app.state.store.create("Prueba explícita de fase 5.pdf", doc.tobytes())
    case = app.state.store.update(
        case["id"],
        status="confirmed" if confirmed else "needs_review",
        identification={
            "subject": "Requisitos",
            "requests": [
                {
                    "id": f"P{index}",
                    "label": str(index),
                    "title": "Requisitos",
                    "description": "Informar los requisitos institucionales.",
                    "source_refs": [
                        {
                            "page": 1,
                            "line_start": 1,
                            "line_end": 1,
                            "quote": "Solicito los requisitos institucionales.",
                        }
                    ],
                }
                for index in range(1, count + 1)
            ],
        },
    )
    source = app.state.library.add(
        "norma.txt",
        b"Norma ficticia: el comite registra los requisitos institucionales.",
        title="Norma ficticia",
        category="institutional_norm",
        origin="Prueba aislada",
    )
    if with_map:
        ready_map(app, case)
    return case, source


def ready_map(app, case):
    current, sources, chunks, fingerprint = app.state.sources.inputs(case["id"])
    run = dict(
        id=uuid4().hex,
        case_id=case["id"],
        fingerprint=fingerprint,
        status="ready",
        source_snapshot=sources,
        source_count=len(sources),
        searched_at=now(),
        stale=False,
        error=None,
        completed_count=current["request_count"],
        total_count=current["request_count"],
        results=[
            {
                "request_id": request["id"],
                "status": "references_found",
                "summary": "Mapa ficticio para probar fase 5.",
                "supports": [{**chunks[0], "role": "rule", "reason": "Texto normativo ficticio."}],
                "missing": [],
                "warnings": [],
            }
            for request in current["identification"]["requests"]
        ],
    )
    app.state.library.save_run(run)
    return run


def generate(client, case):
    return client.post(
        f"/api/cases/{case['id']}/drafts/generate", json={"version": case["version"]}
    )


def wait_drafts(app, client, case):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/cases/{case['id']}/drafts").json()
        # El worker puede terminar después del GET: no devolver esa lectura
        # anterior todavía running solo porque active ya quedó vacío.
        if run["status"] != "running" and case["id"] not in app.state.drafts.active:
            return run
        time.sleep(0.01)
    pytest.fail("El grafo de borradores no terminó")


def test_requires_confirmed_current_case_and_complete_current_source_map(draft_app):
    app, client, engine, _ = draft_app
    case, _ = prepared_case(app, confirmed=False, with_map=False)
    assert generate(client, case).status_code == 409
    case = app.state.store.update(case["id"], status="confirmed")
    assert generate(client, case).status_code == 409
    ready_map(app, case)
    old = {**case, "version": case["version"] - 1}
    assert generate(client, old).status_code == 409
    run = app.state.library.latest_run(case["id"])
    run["results"].pop()
    app.state.library.save_run(run)
    assert generate(client, case).status_code == 409
    assert not engine.calls
    assert client.get("/api/cases/missing/drafts").status_code == 404


@pytest.mark.parametrize("configured,expected", [(1, 1), (5, 5), (99, 6)])
def test_configured_concurrency_is_bounded_and_keeps_every_check(
    draft_app, configured, expected
):
    app, client, engine, settings = draft_app
    app.state.drafts.settings = replace(settings, draft_concurrency=configured)
    case, _ = prepared_case(app, count=7)
    entered, release, lock = threading.Event(), threading.Event(), threading.Lock()
    active = maximum = 0
    visit = engine.visit

    def blocking_visit(phase, request):
        nonlocal active, maximum
        if phase == "plan":
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == expected:
                    entered.set()
            try:
                assert release.wait(10), "No se liberaron las redacciones de prueba"
            finally:
                with lock:
                    active -= 1
        return visit(phase, request)

    engine.visit = blocking_visit
    try:
        assert generate(client, case).status_code == 202
        assert entered.wait(5), "No se alcanzó la concurrencia configurada"
    finally:
        release.set()
    run = wait_drafts(app, client, case)
    assert maximum == run["concurrency"] == expected
    assert run["status"] == "ready" and len(run["results"]) == 7
    assert len(engine.calls) == 21 and set(engine.calls.values()) == {1}


def test_prompt_change_drops_failed_checkpoint_but_keeps_completed_drafts(draft_app):
    app, client, engine, _ = draft_app
    engine.cache_key = "instructions-v1"
    engine.fail_once = ("P1", "write")
    case, _ = prepared_case(app, count=1)
    assert generate(client, case).status_code == 202
    assert wait_drafts(app, client, case)["status"] == "failed"
    engine.cache_key = "instructions-v2"
    assert generate(client, case).status_code == 202
    complete = wait_drafts(app, client, case)
    assert complete["status"] == "ready"
    assert engine.calls == {("P1", "plan"): 2, ("P1", "write"): 2, ("P1", "check"): 1}
    engine.cache_key = "instructions-v3"
    assert generate(client, case).json()["id"] == complete["id"]
    assert engine.calls[("P1", "plan")] == 2


def test_completed_drafts_are_cached_exact_citations_and_case_unchanged(draft_app):
    app, client, engine, settings = draft_app
    case, _ = prepared_case(app)
    before = app.state.store.get(case["id"])
    idle = client.get(f"/api/cases/{case['id']}/drafts").json()
    assert idle["status"] == "idle" and idle["total_count"] == 2
    assert generate(client, case).status_code == 202
    run = wait_drafts(app, client, case)
    assert run["status"] == "ready", run
    assert run["completed_count"] == run["total_count"] == 2
    assert run["requires_human_review"] is True
    assert len(engine.calls) == 6 and set(engine.calls.values()) == {1}
    for result in run["results"]:
        assert result["status"] == "needs_review"
        assert result["timings"]["validation_calls"] > 0
        assert result["timings"]["total_seconds"] >= result["timings"]["validation_seconds"]
        assert {k: v["calls"] for k, v in result["timings"]["engine"].items()} == {
            "plan": 1, "write": 1, "check": 1}
        assert result["supports"][0]["quote"].startswith("Norma ficticia:")
        assert result["draft"]["paragraphs"][0]["cited_chunk_ids"] == [
            result["supports"][0]["chunk_id"]
        ]
    assert generate(client, case).json()["id"] == run["id"]
    assert app.state.store.get(case["id"]) == before
    assert (settings.data_dir / "borradores.sqlite").is_file()
    assert (settings.data_dir / "draft_checkpoints.sqlite").is_file()


def test_performance_endpoint_tracks_provider_calls_inside_parallel_graphs(draft_app, monkeypatch):
    from types import SimpleNamespace

    from pqrs_claro.performance_metrics import provider_call

    app, client, engine, settings = draft_app
    case, _ = prepared_case(app, count=3)
    visit = engine.visit

    def metered_visit(phase, request):
        visit(phase, request)
        provider_call(f"draft.{phase}", lambda **_: SimpleNamespace(
            status="completed", model="test-model",
            usage={"input_tokens": 100, "output_tokens": 20}), model="test-model")

    monkeypatch.setattr(engine, "visit", metered_visit)
    assert client.get("/api/cases/missing/performance").status_code == 404
    assert generate(client, case).status_code == 202
    assert wait_drafts(app, client, case)["status"] == "ready"
    data = client.get(f"/api/cases/{case['id']}/performance").json()
    assert data["provider_calls"] == 9
    assert data["recorded_input_tokens"] == 900
    assert data["estimated_cost_usd"] is None
    assert {e["request_id"] for e in data["events"] if e["kind"] == "provider"} == {
        "P1", "P2", "P3"}
    # Reading or reopening a saved result cannot add provider consumption.
    assert generate(client, case).status_code == 202
    assert client.get(f"/api/cases/{case['id']}/performance").json()["provider_calls"] == 9


@pytest.mark.parametrize("mode", ["pending", "bad_checks"])
def test_evidence_or_check_gaps_remain_pending_without_approval(draft_app, mode):
    app, client, engine, _ = draft_app
    setattr(engine, mode, True)
    case, _ = prepared_case(app)
    assert generate(client, case).status_code == 202
    run = wait_drafts(app, client, case)
    assert run["status"] == "partial", run
    assert all(result["status"] == "needs_evidence" for result in run["results"])
    assert all(result["draft"]["status"] == "needs_evidence" for result in run["results"])
    assert not any("approved" in result for result in run["results"])
    assert generate(client, case).json()["id"] == run["id"]


def test_failed_request_retries_only_failed_step_preserving_completed_history(draft_app):
    app, client, engine, _ = draft_app
    engine.fail_once = ("P2", "write")
    case, _ = prepared_case(app)
    generate(client, case)
    first = wait_drafts(app, client, case)
    assert first["status"] == "partial", first
    assert [result["status"] for result in first["results"]] == ["needs_review", "error"]
    assert first["results"][1]["timings"]["engine"]["write"]["calls"] == 1
    assert generate(client, case).status_code == 202
    second = wait_drafts(app, client, case)
    assert second["status"] == "ready", second
    assert second["id"] != first["id"]
    assert engine.calls == {
        ("P1", "plan"): 1,
        ("P1", "write"): 1,
        ("P1", "check"): 1,
        ("P2", "plan"): 1,
        ("P2", "write"): 2,
        ("P2", "check"): 1,
    }
    with app.state.drafts.store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM draft_runs").fetchone()[0] == 2


def test_source_review_or_identification_change_stales_but_preserves_drafts(draft_app):
    app, client, engine, _ = draft_app
    case, source = prepared_case(app)
    generate(client, case)
    first = wait_drafts(app, client, case)
    app.state.library.review(
        source["id"],
        reviewed_by="Revisor ficticio",
        review_note="Contraste de prueba",
        validity="current",
    )
    stale = client.get(f"/api/cases/{case['id']}/drafts").json()
    assert stale["status"] == "stale" and stale["results"] == first["results"]
    assert generate(client, case).status_code == 409
    ready_map(app, case)
    assert generate(client, case).status_code == 202
    second = wait_drafts(app, client, case)
    assert second["status"] == "ready" and second["fingerprint"] != first["fingerprint"]
    assert set(engine.calls.values()) == {2}
    identification = deepcopy(case["identification"])
    identification["requests"][0]["description"] = "Solicito además los anexos."
    app.state.store.update(case["id"], identification=identification, status="needs_review")
    stale = client.get(f"/api/cases/{case['id']}/drafts").json()
    assert stale["status"] == "stale" and stale["results"] == second["results"]


@pytest.mark.parametrize("tamper", ["quote", "foreign", "duplicate"])
def test_selected_supports_must_be_exact_and_in_current_scope(draft_app, tamper):
    app, client, engine, _ = draft_app
    case, _ = prepared_case(app)
    run = app.state.library.latest_run(case["id"])
    if tamper == "quote":
        run["results"][0]["supports"][0]["quote"] = "Cita inventada"
    elif tamper == "foreign":
        run["results"][0]["supports"][0]["chunk_id"] = "otra-fuente:1:1:4"
    else:
        run["results"][0]["supports"] *= 2
    app.state.library.save_run(run)
    response = generate(client, case)
    assert response.status_code == 409, response.text
    assert not engine.calls


def test_original_change_rejected_before_model_calls(draft_app):
    app, client, engine, _ = draft_app
    case, source = prepared_case(app)
    path = app.state.library.original(source["id"])
    path.write_bytes(b"Original modificado en la prueba")
    response = generate(client, case)
    assert response.status_code == 422, response.text
    assert not engine.calls


def test_draft_inputs_materialize_only_selected_sources(draft_app, monkeypatch):
    app, _, _, _ = draft_app
    case, _ = prepared_case(app, with_map=False, count=1)
    app.state.library.add("otra.txt", b"Otra norma ficticia no seleccionada.",
                          title="Otra norma", category="institutional_norm", origin="Prueba")
    run = ready_map(app, case)
    selected = {s["source_id"] for s in run["results"][0]["supports"]}
    snapshot = app.state.library.snapshot
    reads = []

    def selected_snapshot(case_id, *, source_ids=None):
        reads.append(source_ids)
        assert source_ids == selected
        return snapshot(case_id, source_ids=source_ids)

    def no_full_scan(*_):
        pytest.fail("La preparación volvió a materializar toda la biblioteca")

    monkeypatch.setattr(app.state.library, "snapshot", selected_snapshot)
    monkeypatch.setattr(app.state.sources, "inputs", no_full_scan)
    _, _, findings, fingerprint = app.state.drafts._inputs(case["id"], case["version"])
    assert reads == [selected]
    assert findings["P1"]["supports"][0]["quote"] == run["results"][0]["supports"][0]["quote"]
    app.state.drafts._ensure_current(case["id"], fingerprint, full=True)
    assert reads == [selected, selected]


def test_final_validation_still_reconciles_citations_after_cached_validation(draft_app):
    app, _, _, _ = draft_app
    case, source = prepared_case(app, count=1)
    fingerprint = app.state.drafts._current(case["id"])[2]
    # External extraction changes must not evade the final citation comparison.
    with app.state.library.connect() as conn:
        conn.execute("UPDATE sources SET pages='[]' WHERE id=?", (source["id"],))
    from pqrs_claro.draft_service import _InputsChanged
    with pytest.raises(_InputsChanged):
        app.state.drafts._ensure_current(case["id"], fingerprint, full=True)


@pytest.mark.parametrize("tamper", [None, "foreign", "quote", "version"])
def test_non_citable_candidates_are_reconciled_before_context(draft_app, tamper):
    app, client, engine, _ = draft_app
    case, _ = prepared_case(app, count=1)
    run = app.state.library.latest_run(case["id"])
    support = run["results"][0]["supports"][0]
    document = {
        **{
            key: support[key]
            for key in ("source_id", "document_id", "version", "title", "filename", "category")
        },
        "selected_as_support": False,
        "chunks": [
            {
                key: support[key]
                for key in ("chunk_id", "page", "line_start", "line_end", "quote", "location_kind")
            }
        ],
    }
    if tamper == "foreign":
        document["source_id"] = "otro-expediente"
    elif tamper == "quote":
        document["chunks"][0]["quote"] = "Cita falsa"
    elif tamper == "version":
        document["version"] = 99
    run["results"][0]["candidate_documents"] = [document]
    app.state.library.save_run(run)
    captured = []
    original_plan = engine.plan

    def capture_plan(request, finding):
        captured.append(deepcopy(finding))
        return original_plan(request, finding)

    engine.plan = capture_plan
    response = generate(client, case)
    if tamper:
        assert response.status_code == 409, response.text
        assert not engine.calls and not captured
    else:
        assert response.status_code == 202, response.text
        assert wait_drafts(app, client, case)["status"] == "ready"
        candidate = captured[0]["candidate_documents"][0]
        assert candidate["selected_as_support"] is True
        assert candidate["chunks"][0]["quote"] == support["quote"]


def test_ready_draft_get_detects_original_corruption_without_losing_saved_text(draft_app):
    app, client, _, _ = draft_app
    case, source = prepared_case(app)
    generate(client, case)
    ready = wait_drafts(app, client, case)
    assert ready["status"] == "ready"
    app.state.library.original(source["id"]).write_bytes(b"Cambio fuera del catalogo")
    stale = client.get(f"/api/cases/{case['id']}/drafts").json()
    assert stale["status"] == "stale" and stale["results"] == ready["results"]


def test_new_source_version_invalidates_completed_draft(draft_app):
    app, client, engine, _ = draft_app
    case, source = prepared_case(app)
    generate(client, case)
    ready = wait_drafts(app, client, case)
    new_source = app.state.library.add(
        "norma.txt",
        b"Nueva version ficticia: cambiaron los requisitos institucionales.",
        title="Norma ficticia",
        category="institutional_norm",
        origin="Prueba aislada",
        document_id=source["document_id"],
    )
    stale = client.get(f"/api/cases/{case['id']}/drafts").json()
    assert stale["status"] == "stale" and stale["results"] == ready["results"]
    assert generate(client, case).status_code == 409
    ready_map(app, case)
    generate(client, case)
    regenerated = wait_drafts(app, client, case)
    assert regenerated["status"] == "ready"
    assert regenerated["results"][0]["supports"][0]["source_id"] == new_source["id"]
    assert set(engine.calls.values()) == {2}


@pytest.mark.parametrize("change", ["review", "original"])
def test_midflight_change_stales_keeps_draft_and_stops_next_calls(draft_app, change):
    app, client, engine, _ = draft_app
    case, source = prepared_case(app)
    engine.block = ("P1", "write")
    assert generate(client, case).status_code == 202
    try:
        assert engine.entered.wait(5)
        running = client.get(f"/api/cases/{case['id']}/drafts").json()
        assert running["status"] == "running"
        assert running["request_states"]["P1"] == "redactar"
        assert generate(client, case).status_code == 409
        if change == "review":
            app.state.library.review(
                source["id"],
                reviewed_by="Prueba",
                review_note="Cambió durante el borrador",
                validity="current",
            )
        else:
            app.state.library.original(source["id"]).write_bytes(b"Bytes distintos")
    finally:
        engine.release.set()
    run = wait_drafts(app, client, case)
    assert run["status"] == "stale" and run["stale"] is True, run
    assert run["results"][0]["draft"]["paragraphs"]
    assert engine.calls[("P1", "plan")] == 1
    assert engine.calls[("P1", "write")] == 1
    assert engine.calls[("P1", "check")] == 0


def test_restart_recovers_interrupted_run_and_checkpoint_without_repeating_steps(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", model="test-model")
    first_engine = FakeDraftEngine(fail_once=("P2", "write"))
    app = create_app(settings, draft_engine=first_engine)
    with TestClient(app) as client:
        case, _ = prepared_case(app)
        generate(client, case)
        first = wait_drafts(app, client, case)
        assert first["status"] == "partial"
        # Simula el registro durable al momento de un corte antes de proyectar el error.
        first.update(status="running", current_request_id="P2", current_step="redactar")
        app.state.drafts.store.save(first)
    second_engine = FakeDraftEngine()
    reopened = create_app(settings, draft_engine=second_engine)
    with TestClient(reopened) as client:
        recovered = client.get(f"/api/cases/{case['id']}/drafts").json()
        assert recovered["status"] == "failed"
        assert recovered["results"] == first["results"]
        assert generate(client, case).status_code == 202
        final = wait_drafts(reopened, client, case)
        assert final["status"] == "ready", final
        assert second_engine.calls == {("P2", "write"): 1, ("P2", "check"): 1}


def test_provider_error_does_not_expose_raw_secret(draft_app):
    app, client, engine, _ = draft_app
    case, _ = prepared_case(app, count=1)

    def bad_plan(*_):
        raise ValueError("secret-key-provider-payload")

    engine.plan = bad_plan
    assert generate(client, case).status_code == 202
    run = wait_drafts(app, client, case)
    assert run["status"] == "failed", run
    assert "secret-key" not in str(run)
