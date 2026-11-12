from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_app import pdf_bytes, upload  # noqa: F401
from test_unified_app import unified  # noqa: F401

from pqrs_claro.case_purge import purge_case
from pqrs_claro.management import ManagementAction, ManagementStore
from pqrs_claro.storage import CaseStore, Conflict
from pqrs_claro.work_sessions import ExternalWork, WorkEvent, WorkSessions, session_totals


@pytest.fixture
def pilot(tmp_path):
    store = CaseStore(tmp_path)
    management = ManagementStore(store)
    clock = [0]
    tracker = WorkSessions(store, clock_ms=lambda: clock[0] * 1000)
    store.work_sessions = tracker

    def new_case():
        cid = store.create("ejemplo.pdf", b"ficticio")["id"]
        management.change(cid, ManagementAction(revision=0, actor_id="gestor-1", action="claim"))
        return cid

    return tracker, management, clock, new_case


def event(tracker, case, sid, sequence, kind, *, actor="gestor-1", activity=False):
    return tracker.record(case, WorkEvent(
        actor_id=actor, session_id=sid, sequence=sequence, event=kind, activity=activity,
    ))["status"]


def totals(tracker):
    with tracker.store.connect() as db:
        return session_totals(db)


def test_reading_deadline_without_interaction_and_confirm_without_backfill(pilot):
    tracker, _, clock, new = pilot
    case, sid = new(), uuid4()
    assert event(tracker, case, sid, 0, "start") == "active"
    for i in range(1, 9):
        clock[0] = 16 * i
        status = event(tracker, case, sid, i, "heartbeat")
    assert status == "unconfirmed"  # 120 active, 8 unconfirmed inside the same interval
    clock[0] = 138
    assert event(tracker, case, sid, 9, "heartbeat", activity=True) == "unconfirmed"
    clock[0] = 148
    assert event(tracker, case, sid, 10, "confirm") == "active"
    clock[0] = 159
    assert event(tracker, case, sid, 11, "stop") == "ended"
    clock[0] = 160
    assert event(tracker, case, sid, 11, "stop") == "ended"
    assert totals(tracker)[case, "gestor-1"] == dict(
        active_seconds=131, unconfirmed_seconds=28, external_seconds=0, measured=True,
    )


def test_reread_after_ordinary_interaction_extends_estimate_only_when_continuous(pilot):
    tracker, _, clock, new = pilot
    case, sid = new(), uuid4()
    assert event(tracker, case, sid, 0, "start") == "active"
    for i in range(1, 7):
        clock[0] = 22 * i
        assert event(tracker, case, sid, i, "heartbeat", activity=i == 5) == "active"
    clock[0] += 3600
    assert event(tracker, case, sid, 7, "confirm") == "ended"
    assert event(tracker, case, sid, 0, "start") == "ended"
    assert totals(tracker)[case, "gestor-1"]["active_seconds"] == 132


def test_retries_late_requests_and_two_focused_documents_do_not_double_count(pilot):
    tracker, _, clock, new = pilot
    first, second = new(), new()
    a, b = uuid4(), uuid4()
    assert event(tracker, first, a, 0, "start") == "active"
    clock[0] = 5
    event(tracker, first, a, 2, "heartbeat")
    clock[0] = 9
    event(tracker, first, a, 1, "heartbeat")
    clock[0] = 12
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(lambda _: event(tracker, second, b, 0, "start"), range(3))) == [
            "active", "active", "active"
        ]
    clock[0] = 18
    assert event(tracker, first, a, 0, "start") == "ended"
    assert event(tracker, first, a, 4, "stop") == "ended"
    event(tracker, second, b, 1, "stop")
    result = totals(tracker)
    assert result[first, "gestor-1"]["active_seconds"] == 12
    assert result[second, "gestor-1"]["active_seconds"] == 6
    dropped = uuid4()
    event(tracker, first, dropped, 1, "stop")
    assert event(tracker, first, dropped, 0, "start") == "ended"
    with pytest.raises(Conflict):
        event(tracker, second, dropped, 0, "start")


def test_owner_close_trash_and_purge_are_atomic_boundaries(pilot):
    tracker, management, clock, new = pilot
    case, sid = new(), uuid4()
    with pytest.raises(Conflict):
        event(tracker, case, sid, 0, "start", actor="gestor-2")
    event(tracker, case, sid, 0, "start")

    def change(rev, action, **kwargs):
        management.change(case, ManagementAction(
            actor_id="gestor-1", revision=rev, action=action, note="prueba", **kwargs,
        ))

    clock[0] = 7
    change(1, "assign", manager_id="gestor-2")
    change(2, "assign", manager_id="gestor-1")
    assert event(tracker, case, sid, 1, "heartbeat") == "ended"
    change(3, "start")
    sid = uuid4()
    event(tracker, case, sid, 0, "start")
    clock[0] = 12
    change(4, "state", state="closed")
    with pytest.raises(Conflict):
        event(tracker, case, uuid4(), 0, "start")
    change(5, "state", state="in_progress")
    assert event(tracker, case, sid, 1, "heartbeat") == "ended"
    sid = uuid4()
    event(tracker, case, sid, 0, "start")
    clock[0] = 15
    tracker.store.set_deleted(case, version=1, lifecycle_revision=0, deleted=True,
                              management_revision=6)
    assert event(tracker, case, sid, 1, "heartbeat") == "ended"
    assert totals(tracker)[case, "gestor-1"]["active_seconds"] == 15
    purge_case(tracker.store, case, 1, 1, 6)
    assert (case, "gestor-1") not in totals(tracker)
    with pytest.raises(KeyError):
        event(tracker, case, sid, 1, "stop")


def test_external_is_labeled_separate_and_idempotent(pilot):
    tracker, _, _, new = pilot
    case = new()
    body = ExternalWork(actor_id="gestor-1", entry_id=uuid4(), minutes=10, reason=" Llamada ")
    assert tracker.declare(case, body) == tracker.declare(case, body)
    with pytest.raises(Conflict):
        tracker.declare(case, body.model_copy(update={"minutes": 11}))
    assert totals(tracker)[case, "gestor-1"] == dict(
        active_seconds=0, unconfirmed_seconds=0, external_seconds=600, measured=False,
    )
    event(tracker, case, uuid4(), 0, "start")
    assert totals(tracker)[case, "gestor-1"]["measured"]


def test_distinct_concurrent_session_starts_allow_only_one_later_heartbeat(pilot):
    tracker, _, clock, new = pilot
    case = new()
    sessions = [uuid4(), uuid4()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda sid: event(tracker, case, sid, 0, "start"), sessions))
    clock[0] = 15
    statuses = [event(tracker, case, sid, 1, "heartbeat") for sid in sessions]
    assert sorted(statuses) == ["active", "ended"]
    assert totals(tracker)[case, "gestor-1"]["active_seconds"] == 15


def test_real_api_during_preanalysis_and_server_owns_duration(unified, pdf_bytes):  # noqa: F811
    app, client, _, _ = unified
    cid = upload(client, pdf_bytes)["id"]
    prefix = f"/api/cases/{cid}/"
    start = dict(actor_id="gestor-1", session_id=str(uuid4()), sequence=0, event="start")
    assert client.post(prefix + "work-session", json=start).status_code == 409
    assert client.post(prefix + "management", json=dict(
        actor_id="gestor-1", revision=0, action="claim",
    )).status_code == 200
    assert client.post(prefix + "work-session", json={**start, "seconds": 987}).status_code == 422
    assert client.post(prefix + "work-session", json=start).json()["status"] == "active"
    assert client.post(prefix + "work-session", json={
        **start, "sequence": 1, "event": "stop",
    }).json()["status"] == "ended"
    manual = dict(actor_id=start["actor_id"], entry_id=str(uuid4()), minutes=4,
                  reason="Consulta telefónica")
    for _ in range(2):
        assert client.post(prefix + "external-work", json=manual).status_code == 200
    with app.state.store.connect() as db:
        recorded = session_totals(db)[cid, "gestor-1"]
    assert recorded["external_seconds"] == 240 and recorded["measured"]
    assert app.state.management.get(cid)["revision"] == 1
