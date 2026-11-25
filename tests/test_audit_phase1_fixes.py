"""Regression tests for Phase 1 audit fixes (startup, polling, proxy, CSRF, validation)."""

from __future__ import annotations

import json
import threading
import zipfile
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from pqrs_claro.app import create_app
from pqrs_claro.case_lifecycle import case_busy
from pqrs_claro.config import Settings
from pqrs_claro.draft_service import DraftService
from pqrs_claro.laya_lab import create_laya_lab_app
from pqrs_claro.models import DomainError
from pqrs_claro.pool_jobs import PoolJobs
from pqrs_claro.pool_service import PoolService
from pqrs_claro.preanalysis import PreanalysisService
from pqrs_claro.recorrido_app import create_recorrido
from pqrs_claro.source_library import read_source
from pqrs_claro.storage import CaseStore


def test_preanalysis_recover_survives_missing_original_pdf(tmp_path):
    store = CaseStore(tmp_path / "data")
    service = PreanalysisService(
        Settings(data_dir=tmp_path / "data"),
        store,
        SimpleNamespace(get=lambda cid: {}),
        SimpleNamespace(active=set(), lock=threading.RLock()),
    )
    record = {
        "case_id": "missing-case",
        "status": "running",
        "revision": 1,
        "sha256": "a" * 64,
        "retained_checks": True,
        "pages": [],
        "checks": {},
        "events": [],
    }
    with store.connect() as db:
        db.execute(
            "INSERT INTO case_preanalysis (case_id, body) VALUES (?, ?)",
            ("missing-case", json.dumps(record)),
        )
    service.recover()
    with store.connect() as db:
        row = db.execute(
            "SELECT body FROM case_preanalysis WHERE case_id=?", ("missing-case",)
        ).fetchone()
    recovered = json.loads(row[0])
    assert recovered["status"] == "error"
    assert recovered["retained_checks"] is False
    assert recovered["revision"] == 2
    service.close()


def test_draft_service_progress_avoids_pdf_hashing_while_running():
    calls = []
    running_run = {
        "id": "r1",
        "case_id": "c1",
        "status": "running",
        "source_run_id": "s1",
        "fingerprint": "fp1",
        "results": [],
    }
    service = DraftService.__new__(DraftService)
    service.store = SimpleNamespace(latest=lambda cid: running_run)
    service.cases = SimpleNamespace(original=lambda cid: calls.append(("case", cid)))
    service.library = SimpleNamespace(
        run_scope_revoked=lambda cid, sid: False,
        original=lambda sid, cid: calls.append(("lib", sid)),
    )
    progress = service.progress("c1")
    assert progress["status"] == "running"
    assert progress["freshness_checked"] is False
    assert calls == []

    service.library = SimpleNamespace(
        run_scope_revoked=lambda cid, sid: True,
        original=lambda sid, cid: calls.append(("lib", sid)),
    )
    revoked = service.progress("c1")
    assert revoked["status"] == "stale" and revoked["stale"] is True
    assert calls == []


def test_pool_jobs_recover_marks_orphaned_running_progress_interrupted(tmp_path):
    store = CaseStore(tmp_path / "data")
    case = store.create("peticion.pdf", b"%PDF-1.4\n%stub\n", receipt={"workflow": "fiaga"})
    pool = PoolService(store)
    pool.enroll(case["id"])
    with store.connect() as db:
        db.execute(
            "UPDATE case_pool SET stage='preparing', revision=2 WHERE case_id=?",
            (case["id"],),
        )
        db.execute(
            "INSERT INTO case_pool_progress (case_id, worker, body) VALUES (?, ?, ?)",
            (case["id"], "dead-worker", json.dumps({"status": "running", "stage": "preparing"})),
        )
    jobs = PoolJobs(pool, SimpleNamespace())
    try:
        jobs.recover()
    finally:
        jobs.close()
    with store.connect() as db:
        worker, body = db.execute(
            "SELECT worker, body FROM case_pool_progress WHERE case_id=?", (case["id"],)
        ).fetchone()
    assert worker is None
    assert json.loads(body)["status"] == "interrupted"


def test_pool_service_caps_attachment_count(tmp_path):
    store = CaseStore(tmp_path / "data")
    pool = PoolService(store)
    uploads = [(f"doc{i}.txt", BytesIO(b"contenido")) for i in range(21)]
    with pytest.raises(ValueError, match="20 archivos"):
        pool._prepare_files(uploads)


def test_recorrido_proxy_forwards_fiaga_actor_blocks_traversal_and_hides_docs():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("x-fiaga-actor")))
        return httpx.Response(200, json={"ok": True})

    app = create_recorrido(transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        res = client.post(
            "/api/cases/c1/test",
            headers={"X-Fiaga-Actor": "admin"},
            json={"x": 1},
        )
        assert res.status_code == 200
        assert seen == [("/api/cases/c1/test", "admin")]
        escaped = client.get("/api/cases/..%2f..%2fanterior")
        assert escaped.status_code == 400


def test_laya_lab_blocks_cross_site_classify_requests():
    app = create_laya_lab_app()
    with TestClient(app) as client:
        r1 = client.post(
            "/api/classify",
            headers={"Origin": "https://attacker.invalid"},
            data={"text": "Solicito copia.", "provider": "laya"},
        )
        assert r1.status_code == 403
        r2 = client.post(
            "/api/classify",
            headers={"Sec-Fetch-Site": "cross-site"},
            data={"text": "Solicito copia.", "provider": "laya"},
        )
        assert r2.status_code == 403


def test_app_hides_openapi_guards_gmail_link_and_tracks_pool_jobs(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", api_key=""))
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 404
        case = app.state.store.create("p.pdf", b"%PDF-1.4\n%stub\n", receipt={"workflow": "fiaga"})
        app.state.pool.enroll(case["id"])
        blocked = client.post(
            "/api/gmail/messages/m1/import",
            json={"mode": "link", "target_case_id": case["id"]},
        )
        assert blocked.status_code == 409
        malformed = client.put(
            "/api/sources/nonexistent/review",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert malformed.status_code == 422
        app.state.pool_jobs.active.add((case["id"], "integration", 1))
        try:
            assert case_busy(case["id"], (app.state.pool_jobs,)) is True
        finally:
            app.state.pool_jobs.active.clear()


def test_corrupted_docx_xml_raises_domain_error_not_syntax_error(tmp_path):
    broken = tmp_path / "broken.docx"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types><broken")
    with pytest.raises(DomainError, match="DOCX"):
        read_source(broken, None)
