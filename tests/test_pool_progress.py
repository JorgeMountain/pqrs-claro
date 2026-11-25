"""Live FIAGA progress and checkpoint recovery with synthetic documents and engines."""

from copy import deepcopy
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_app import wait_ready
from test_draft_service_api import FakeDraftEngine
from test_pool_drafts import engine_and_case  # noqa: F401
from test_pool_recovery import settled
from test_pool_service import setup_pool, snapshot  # noqa: F401
from test_preanalysis import CountingExtractor, FakePreanalysis, approval
from test_source_service_api import (
    FakeSourceAssessor,
    TwoRequestsIdentifier,
    pdf_bytes,  # noqa: F401
    upload_source,
)

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.models import DomainError
from pqrs_claro.pool_progress import observe_progress
from pqrs_claro.pool_service import PoolService
from pqrs_claro.storage import Conflict


def stored_automatic_case(pool, cid):
    # Simulate a previously enrolled case with the former automatic worker still running.
    with pool.store.connect() as db:
        db.execute("UPDATE case_pool SET stage='preparing', "
                   "body=json_set(body,'$.stage','preparing') "
                   "WHERE case_id=?", (cid,))


def test_http_progress_survives_failed_request_and_restart(tmp_path, pdf_bytes):  # noqa: F811
    settings = Settings(data_dir=tmp_path, api_key="", management_enabled=True)
    extractor, checker = CountingExtractor(), FakePreanalysis()
    writer = FakeDraftEngine(block=("P1", "plan"), fail_once=("P2", "write"))
    entered, release = Event(), Event()

    class PausedIdentifier(TwoRequestsIdentifier):
        def identify(self, pages):
            entered.set()
            assert release.wait(10)
            result = super().identify(pages)
            result.requests[1].parent_id = "P1"
            result.warnings.append("Verificar el alcance de la segunda petición.")
            return result

    def application():
        return create_app(settings, extractor=extractor, identifier=PausedIdentifier(),
                          source_assessor=FakeSourceAssessor(), preanalysis_engine=checker,
                          draft_engine=writer)

    app = application()
    with TestClient(app) as client:
        assert upload_source(client).status_code == 201
        upload = client.post("/api/cases", data={"workflow": "fiaga"},
                             files={"file": ("prueba.pdf", pdf_bytes, "application/pdf")})
        assert upload.status_code == 201
        case_id = upload.json()["id"]
        path = f"/api/cases/{case_id}/pool"
        stored_automatic_case(app.state.pool, case_id)
        app.state.pool_jobs.schedule(case_id)
        try:
            assert entered.wait(10)
            reading = client.get(path).json()
            assert reading["reading"]["pages"] == [
                {"number": 1, "method": "native", "needs_review": False}]
            assert set(reading["checks"]) == {"requester", "respect", "integrity"}
            assert reading["checks"]["requester"]["state"] == "attention"
            assert reading["progress"]["steps"]["identification"] == "running"
            assert reading["requests"] == []
            release.set()
            assert writer.entered.wait(10)
            state = client.get(path).json()
            progress = state["progress"]
            assert state["revision"] == 1 and state["stage"] == "preparing"
            assert progress["status"] == "running" and progress["stage"] == "preanalysis"
            assert set(progress["steps"].values()) == {"done"}
            assert [r["id"] for r in progress["requests"]] == ["P1", "P2"]
            first = progress["requests"][0]
            assert first["sources"] == "done" and first["drafting"] == "running"
            assert first["label"] and progress["updated_at"]
            assert state["identification_warnings"] == [
                "Verificar el alcance de la segunda petición."]
            r1, r2 = state["requests"]
            assert r1["label"] == "1" and r2["parent_id"] == "P1"
            assert r1["source_refs"][0]["page"] == 1 and r1["sources"][0]["quote"]
            assert r1["source_status"] and r1["source_summary"]
            assert r1["answer"] == "" and r1["gaps"] == []
            # Independent reader while both request workers have the same case revision.
            persisted = PoolService(app.state.store).get(case_id)
            assert persisted["progress"]["requests"][0] == first and persisted["requests"][0] == r1
        finally:
            release.set()
            writer.release.set()
        failed = settled(client, path)
        assert failed["error"] and failed["progress"]["status"] == "error"
        assert [r["drafting"] for r in failed["progress"]["requests"]] == ["done", "error"]
        assert failed["requests"][0]["answer"] and failed["requests"][1]["answer"] == ""
    with TestClient(application()) as client:
        assert client.get(path).json() == failed
        assert client.post(path + "/start", json={"actor_id": "admin"}).status_code == 409
        decision = {"actor_id": "admin", "revision": failed["revision"]}
        reopened = client.post(path + "/open-review", json=decision)
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["stage"] == "admin_review"
        assert reopened.json()["requests"] == failed["requests"]
        restored = client.get(path.removesuffix("pool") + "preanalysis").json()
        assert restored["checks"] == failed["checks"] and restored["status"] == "ready"
        assert restored["approval"] is None and extractor.calls == checker.calls == 1
        assert writer.calls["P1", "write"] == writer.calls["P2", "write"] == 1
        entered.clear()
        record = client.get(f"/api/cases/{case_id}").json()
        assert not record["identification"]
        body = {**approval(restored, record["management"]["revision"]), "actor_id": "admin"}
        started = client.post(f"/api/cases/{case_id}/preanalysis/start", json=body,
                              headers={"X-Fiaga-Actor": "admin"})
        assert started.status_code == 200, started.text
        identified = wait_ready(client, case_id)
        assert identified["status"] == "needs_review"
        assert len(identified["identification"]["requests"]) == 2
        assert not entered.is_set() and extractor.calls == checker.calls == 1


def test_unlink_hides_source_outputs_while_a_request_is_still_drafting(tmp_path, pdf_bytes):  # noqa: F811
    settings = Settings(data_dir=tmp_path, api_key="", source_concurrency=1, draft_concurrency=1)
    writer = FakeDraftEngine(block=("P2", "plan"))
    app = create_app(settings, extractor=CountingExtractor(), identifier=TwoRequestsIdentifier(),
                     source_assessor=FakeSourceAssessor(), preanalysis_engine=FakePreanalysis(),
                     draft_engine=writer)
    with TestClient(app) as client:
        library = app.state.library
        collection = "archivo-comite"
        library.save_collection({"id": collection, "title": "Archivo del comité"})
        quote = "El comité de prácticas remitió el acta reservada del proyecto ZETA."
        source = library.add("reserva.txt", quote.encode(), title="Acta restringida de prácticas",
                             category="institutional_norm", origin="Prueba",
                             collection_id=collection)
        upload = client.post("/api/cases", data={"workflow": "fiaga"},
                             files={"file": ("prueba.pdf", pdf_bytes, "application/pdf")})
        case_id = upload.json()["id"]
        path = f"/api/cases/{case_id}/pool"
        stored_automatic_case(app.state.pool, case_id)
        app.state.pool_jobs.schedule(case_id)
        try:
            assert writer.entered.wait(10)
            before = client.get(path).json()
            first = before["requests"][0]
            assert first["answer"] and first["sources"][0]["quote"] == quote
            library.link_collections(case_id, [])
            revoked = client.get(path)
            filtered = revoked.json()
            assert filtered["scope_revoked"] and filtered["stage"] == "preparing"
            assert filtered["progress"]["updated_at"] == before["progress"]["updated_at"]
            assert filtered["requests"][0]["source_refs"] == first["source_refs"]
            assert filtered["checks"] == before["checks"]
            for row in filtered["requests"]:
                assert not any(row[field] for field in (
                    "sources", "source_summary", "source_status", "answer", "gaps", "paragraphs"))
            assert source["id"] not in revoked.text and quote not in revoked.text
        finally:
            writer.release.set()
        failed = settled(client, path)
        assert failed["error"] and failed["scope_revoked"]
        decision = {"actor_id": "admin", "revision": failed["revision"]}
        admin = client.post(path + "/open-review", json=decision)
        assert admin.status_code == 200 and admin.json()["stage"] == "admin_review"
        assert all(not row["sources"] for row in admin.json()["requests"])


def test_integration_reuses_only_completed_answers(engine_and_case):  # noqa: F811
    _, case, drafts = engine_and_case
    initial = drafts.initial(case["id"])
    tasks = [{
        "id": r["id"], "request_id": r["id"], "department": "Archivo", "instruction": r["text"],
        "contributions": [{"actor_id": "archivo", "note": "", "files": [
            {"id": r["id"], "filename": "acta.txt", "text": "Acta ficticia.", "url": "/test"}]}],
    } for r in initial["requests"]]
    original = drafts.integration_engine.integrate
    calls = []

    def interrupt_second(row, inputs):
        calls.append(row["id"])
        if calls == ["P1", "P2"]:
            raise DomainError("Fallo simulado.")
        return original(row, inputs)

    drafts.integration_engine.integrate = interrupt_second
    events = []
    with observe_progress("integration", lambda p, **_: events.append(deepcopy(p))):
        with pytest.raises(DomainError, match="simulado"):
            drafts.integrate(case["id"], initial, tasks)
    assert [r["integration"] for r in events[-1]["requests"]] == ["done", "error"]
    with observe_progress("integration", lambda p, **_: events.append(deepcopy(p))):
        revised = drafts.integrate(case["id"], initial, tasks)
    assert calls == ["P1", "P2", "P2"]
    assert [r["integration"] for r in events[-1]["requests"]] == ["done", "done"]
    assert all(r["answer"] for r in revised["requests"])


def test_replaced_worker_cannot_publish_or_overwrite_progress(setup_pool):  # noqa: F811
    pool, cid = setup_pool
    stored_automatic_case(pool, cid)
    assert pool.get(cid)["progress"] is None
    record = dict(stage="preanalysis", status="running", steps={}, requests=[])
    partial = ("checks", "", {"respect": {"state": "attention"}})
    pool.record_progress(cid, "preparing", 1, "old", record, begin=True)
    pool.record_progress(cid, "preparing", 1, "old", record, begin=False, output=partial)
    assert pool.get(cid)["checks"] == partial[2]
    pool.record_progress(cid, "preparing", 1, "new", record, begin=True)
    assert pool.get(cid)["checks"] == {}
    with pytest.raises(Conflict):
        pool.record_progress(cid, "preparing", 1, "old", record, begin=False, output=partial)
    with pytest.raises(Conflict):
        pool.set_error(cid, "Fallo obsoleto", revision=1, worker="old")
    with pytest.raises(Conflict):
        pool.set_initial(cid, snapshot(""), revision=1, worker="old")
    assert pool.get(cid)["revision"] == 1
    pool.record_progress(cid, "preparing", 1, "new", record, begin=False, output=partial)
    completed = pool.set_initial(cid, snapshot(""), revision=1, worker="new")
    assert completed["progress"]["status"] == "done"
    with pool.store.connect() as db:
        assert not db.execute("SELECT 1 FROM case_pool_work_results").fetchone()
        db.execute("DELETE FROM cases WHERE id=?", (cid,))
        assert not db.execute("SELECT 1 FROM case_pool_progress WHERE case_id=?", (cid,)).fetchone()
