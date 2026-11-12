"""Management clocks across real SQLite transitions, session records and report routes."""

import csv
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_unified_app import unified  # noqa: F401

from pqrs_claro import management, storage
from pqrs_claro.management import ManagementAction
from pqrs_claro.management_times import management_report


@pytest.fixture
def scenario(unified, monkeypatch):  # noqa: F811
    app, client, _, _ = unified
    store = app.state.store
    start = datetime(2026, 10, 4, 3, tzinfo=timezone.utc)  # 3 de octubre en Bogotá
    clock = [start]
    monkeypatch.setattr(storage, "now", lambda: clock[0].isoformat())
    monkeypatch.setattr(management, "now", lambda: clock[0].isoformat())
    store.work_sessions.clock_ms = lambda: int(clock[0].timestamp() * 1000)
    with store.connect() as db:
        db.execute("UPDATE work_tracking_config SET value=? WHERE key='installed_at'",
                   ((start + timedelta(minutes=5)).isoformat(),))

    def at(minutes, seconds=0):
        clock[0] = start + timedelta(minutes=minutes, seconds=seconds)
        return clock[0]

    return app, client, store, at


def change(app, cid, kind, actor="gestor-1", **fields):
    store = app.state.management
    action = ManagementAction(actor_id=actor, revision=store.get(cid)["revision"],
                              action=kind, **fields)
    store.change(cid, action)


def work(client, cid, actor, at, minute, seconds):
    sid = str(uuid4())
    for seq, event in enumerate(("start", "stop")):
        at(minute, seq * seconds)
        result = client.post(f"/api/cases/{cid}/work-session", json={
            "session_id": sid, "sequence": seq, "event": event, "actor_id": actor,
        })
        assert result.status_code == 200, result.text


def test_real_sessions_transfers_final_closure_and_csv(scenario):
    app, client, store, at = scenario
    case = store.create("demo.pdf", b"x", receipt={"subject": "=2+3", "reference": "R-1"})
    cid = case["id"]
    at(10)
    change(app, cid, "claim")
    at(12)
    change(app, cid, "start")
    work(client, cid, "gestor-1", at, 13, 21)
    at(14)
    change(app, cid, "state", state="pending", note="Esperando anexo")
    at(18)
    change(app, cid, "state", state="in_progress", note="Anexo recibido")
    at(22)
    change(app, cid, "assign", manager_id="gestor-2", note="Relevo")
    at(25)
    assert client.post(f"/api/cases/{cid}/external-work", json={
        "actor_id": "gestor-2", "entry_id": str(uuid4()), "minutes": 2, "reason": "Llamada",
    }).status_code == 200
    work(client, cid, "gestor-2", at, 30, 15)
    at(40)
    change(app, cid, "state", "gestor-2", state="closed", note="Finalizado")
    at(42)
    change(app, cid, "metadata", reference="R-2")
    first = management_report(store, as_of=at(43))["cases"][0]
    assert first["total_seconds"] == 2400
    assert first["closed_by_id"] == "gestor-2"
    at(45)
    change(app, cid, "state", "gestor-2", state="in_progress", note="Reapertura")
    reopened = management_report(store, as_of=at(46))
    assert reopened["cases"][0]["total_seconds"] == 2760
    assert reopened["cases"][0]["closed_at"] is None
    assert all(row["closed_count"] == 0 for row in reopened["managers"])
    at(50)
    change(app, cid, "state", "gestor-2", state="closed", note="Segundo cierre")

    report = client.get("/api/management-times?state=closed&date_to=2026-10-03").json()
    item, = report["cases"]
    assert item["measurement"] == "partial"
    assert item["total_seconds"] == 3000
    assert (item["pool_seconds"], item["pending_seconds"]) == (600, 240)
    assert (item["transfers"], item["active_seconds"], item["external_seconds"]) == (1, 36, 120)
    assert [p["active_seconds"] for p in item["contributors"]] == [21, 15]
    declared, = item["external_entries"]
    assert (declared["manager_name"], declared["minutes"], declared["reason"]) == (
        "Gestor 2", 2, "Llamada"
    )
    first, last = report["managers"]
    assert first["closed_count"] == 0 and first["median_resolution_seconds"] is None
    assert last["closed_count"] == 1 and last["median_resolution_seconds"] == 3000
    assert last["median_active_seconds"] == 15

    result = client.get("/api/management-times?manager_id=gestor-1").json()
    assert result["cases"][0]["active_seconds"] == 36
    assert result["managers"] == [first]
    for view, header in [("cases", "ID expediente"), ("managers", "Gestor")]:
        download = client.get("/api/management-times.csv",
                              params={"view": view, "manager_id": "gestor-1"})
        assert download.status_code == 200
        assert download.headers["content-disposition"].startswith("attachment;")
        assert download.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.DictReader(io.StringIO(download.content.decode("utf-8-sig")),
                                   delimiter=";"))
        assert len(rows) == 1 and header in rows[0]
        if view == "cases":
            assert rows[0]["Asunto"] == "'=2+3"
            assert rows[0]["Alta (Bogotá)"].startswith("2026-10-03T22:00:00")
            assert rows[0]["Activo estimado (s)"] == "36"
    assert client.get("/api/management-times?date_from=2026-10-04").json()["cases"] == []


def test_unmeasured_legacy_external_only_zero_and_trash(scenario):
    app, client, store, at = scenario
    old = store.create("viejo.pdf", b"x")
    store.update(old["id"], status="needs_review")
    new = store.create("actual.pdf", b"x")
    report = management_report(store, as_of=at(8))
    items = {case["case_id"]: case for case in report["cases"]}
    assert items[new["id"]]["pool_seconds"] == 480
    assert items[old["id"]]["pool_seconds"] is None
    assert items[old["id"]]["total_seconds"] == 480
    assert items[old["id"]]["subject"] == "viejo.pdf"
    assert items[old["id"]]["internal_number"] == "PQRS-" + old["id"][:12].upper()
    assert all(case["active_seconds"] is None for case in items.values())
    cid = store.create("externo.pdf", b"x")["id"]
    change(app, cid, "claim")
    assert client.post(f"/api/cases/{cid}/external-work", json={
        "actor_id": "gestor-1", "entry_id": str(uuid4()), "minutes": 5, "reason": "Llamada",
    }).status_code == 200
    result = client.get("/api/management-times?manager_id=gestor-1").json()
    item, = result["cases"]
    assert item["active_seconds"] is None and item["external_seconds"] == 300
    assert item["measurement"] == "unmeasured"
    assert result["managers"][0]["measured_case_count"] == 0
    work(client, cid, "gestor-1", at, 9, 0)
    item, = client.get("/api/management-times?manager_id=gestor-1").json()["cases"]
    assert item["active_seconds"] == 0 and item["measurement"] == "observed"
    store.set_deleted(cid, version=1, lifecycle_revision=0, management_revision=1, deleted=True)
    assert client.get("/api/management-times?manager_id=gestor-1").json()["cases"] == []
    invalid = client.get("/api/management-times?date_from=2026-10-05&date_to=2026-10-03")
    assert invalid.status_code == 422
