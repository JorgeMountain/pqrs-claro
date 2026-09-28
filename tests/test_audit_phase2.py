"""Audit phase 2 regressions: temporary stores and fake engines only."""

# ruff: noqa: F811, F401
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from test_app import upload
from test_initial_review import decision, fiaga, wait_intake
from test_management import action
from test_source_service_api import make_case, pdf_bytes, upload_source
from test_unified_app import unified

from pqrs_claro.management import ManagementStore, receipt_date
from pqrs_claro.storage import Conflict, now


def test_gmail_receipt_uses_original_bogota_date_and_preserves_manual_override():
    case = {
        "id": "date-test",
        "created_at": "2026-09-28T01:00:00+00:00",
        "status": "uploaded",
        "origin": {"kind": "gmail", "email_received_at": "2026-09-17T02:00:00Z"},
    }
    assert ManagementStore.default(case)["received_date"] == "2026-09-16"
    case["receipt"] = {"received_date": "2026-09-15"}
    assert receipt_date(case) == "2026-09-15"
    case.pop("receipt")
    case["origin"]["email_received_at"] = "invalid"
    assert receipt_date(case) == "2026-09-27"


def test_old_untouched_receipt_is_repaired_but_metadata_override_survives(unified, pdf_bytes):
    app, client, _, _ = unified
    c = app.state.store.create(
        "ficticio.pdf",
        pdf_bytes,
        origin={"kind": "gmail", "email_received_at": "2026-09-17T02:00:00Z"},
    )
    original = app.state.management.get(c["id"])
    original.pop("received_date_source")
    original["received_date"] = c["created_at"][:10]
    with app.state.store.connect() as db:
        db.execute("INSERT INTO case_management VALUES (?,?)", (c["id"], json.dumps(original)))
    assert app.state.management.get(c["id"])["received_date"] == "2026-09-16"
    assert action(client, c["id"], 0, "metadata", received_date="2026-09-14").status_code == 200
    assert app.state.management.get(c["id"])["received_date"] == "2026-09-14"


def test_stale_tab_cannot_delete_restore_or_purge_newly_managed_case(unified, pdf_bytes):
    app, client, _, _ = unified
    c = upload(client, pdf_bytes)
    cid = c["id"]
    path = f"/api/cases/{cid}"
    stale = {
        "version": c["version"],
        "lifecycle_revision": 0,
        "management_revision": 0,
        "confirmed": True,
    }
    assert action(client, cid, 0, "claim", actor="gestor-2").status_code == 200
    assert client.request("DELETE", path, json=stale).status_code == 409
    assert app.state.store.original(cid).read_bytes() == pdf_bytes
    current = {**stale, "management_revision": 1}
    assert client.request("DELETE", path, json=current).status_code == 200
    assert (
        client.post(path + "/restore", json={**stale, "lifecycle_revision": 1}).status_code == 409
    )
    assert (
        client.request(
            "DELETE", path + "/permanent", json={**stale, "lifecycle_revision": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(path + "/restore", json={**current, "lifecycle_revision": 1}).status_code == 200
    )


def managed_case(fiaga, pdf):
    app, client, engine, assessor = fiaga
    c = make_case(client, pdf, confirm=False)
    row = wait_intake(app, client, c)
    app.state.store.management = app.state.management
    app.state.service.management = app.state.management
    assert action(client, c["id"], 0, "claim").status_code == 200
    return c, row


def test_closed_case_blocks_new_ai_and_reopens_explicitly(fiaga, pdf_bytes):
    app, client, engine, assessor = fiaga
    c, row = managed_case(fiaga, pdf_bytes)
    cid = c["id"]
    base = f"/api/cases/{cid}"
    assert (
        action(client, cid, 1, "state", state="closed", note="Cierre ficticio").status_code == 200
    )
    before = engine.calls
    for suffix, body in [
        ("/initial-review/analyze", {"version": c["version"], "revision": row["revision"]}),
        ("/preparation", {"version": c["version"]}),
        ("/sources/search", {"version": c["version"]}),
    ]:
        response = client.post(base + suffix, json=body)
        assert response.status_code == 409, response.text
    for service, args in [
        (app.state.drafts, (cid, c["version"])),
        (app.state.reviews, (cid, c["version"])),
        (app.state.proposals, (cid, "P1", 1)),
    ]:
        with pytest.raises(Conflict, match="finalizado"):
            service.start(*args)
    assert client.put(base + "/initial-review/decision", json=decision(row)).status_code == 409
    assert client.get(base + "/initial-review").json()["can_prepare"] is False
    assert client.get(base + "/original").status_code == 200
    assert engine.calls == before and not assessor.calls
    assert (
        action(client, cid, 2, "state", state="in_progress", note="Reabrir ficticio").status_code
        == 200
    )
    assert (
        client.post(
            base + "/initial-review/analyze",
            json={"version": c["version"], "revision": row["revision"]},
        ).status_code
        == 202
    )
    wait_intake(app, client, c)
    assert engine.calls == before + 1


def test_cannot_close_during_initial_review(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    c, row = managed_case(fiaga, pdf_bytes)
    cid = c["id"]
    engine.block = True
    try:
        assert (
            client.post(
                f"/api/cases/{cid}/initial-review/analyze",
                json={"version": c["version"], "revision": row["revision"]},
            ).status_code
            == 202
        )
        assert engine.entered.wait(5)
        assert (
            action(client, cid, 1, "state", state="closed", note="Cierre ficticio").status_code
            == 409
        )
        assert app.state.management.get(cid)["revision"] == 1
    finally:
        engine.release.set()
    wait_intake(app, client, c)
    assert action(client, cid, 1, "state", state="closed", note="Terminó").status_code == 200


@pytest.mark.parametrize(
    "worker", ["preparation", "sources", "drafts", "reviews", "offices", "proposals"]
)
def test_close_checks_every_active_worker(unified, pdf_bytes, worker):
    app, client, _, _ = unified
    c = upload(client, pdf_bytes)
    cid = c["id"]
    app.state.store.update(cid, status="needs_review", identification={"requests": []})
    assert action(client, cid, 0, "claim").status_code == 200
    service = getattr(app.state, worker)
    key = (cid, "P1") if worker in {"reviews", "proposals"} else cid
    if isinstance(service.active, dict):
        service.active[key] = True
    else:
        service.active.add(key)
    try:
        assert (
            action(client, cid, 1, "state", state="closed", note="Cierre ficticio").status_code
            == 409
        )
    finally:
        if isinstance(service.active, dict):
            service.active.pop(key)
        else:
            service.active.remove(key)
    assert app.state.management.get(cid)["state"] == "in_progress"


def test_legacy_source_search_respects_specialist_route(fiaga, pdf_bytes):
    app, client, _, assessor = fiaga
    upload_source(client)
    c = make_case(client, pdf_bytes, confirm=False)
    row = wait_intake(app, client, c)
    body = decision(row)
    body["document"]["route"] = "specialist"
    base = f"/api/cases/{c['id']}"
    assert client.put(base + "/initial-review/decision", json=body).status_code == 200
    current = client.get(base).json()
    assert (
        client.post(base + "/sources/search", json={"version": current["version"]}).status_code
        == 409
    )
    assert not assessor.calls and not app.state.sources.active


def test_legacy_demo_fails_before_creating_case(unified):
    app, client, _, _ = unified
    app.state.service.management = app.state.management
    before = len(app.state.store.list())
    assert client.post("/api/cases/demo").status_code == 409
    assert len(app.state.store.list()) == before


def test_last_activity_includes_intake_preparation_and_office(unified, pdf_bytes):
    app, client, _, _ = unified
    c = upload(client, pdf_bytes)
    cid = c["id"]
    t = datetime.now(timezone.utc) + timedelta(seconds=1)

    def stamp(i):
        return (t + timedelta(seconds=i)).isoformat()

    with app.state.store.connect() as db:
        db.execute(
            "INSERT INTO intake_reviews VALUES (?,?)",
            (cid, json.dumps({"case_id": cid, "updated_at": stamp(1)})),
        )
    assert client.get("/api/cases").json()[0]["last_activity"] == stamp(1)
    app.state.preparation.save({"case_id": cid, "version": c["version"], "status": "idle"})
    with app.state.store.connect() as db:
        db.execute(
            "UPDATE preparations SET body=? WHERE case_id=?",
            (json.dumps({"case_id": cid, "updated_at": stamp(2)}), cid),
        )
    assert client.get("/api/cases").json()[0]["last_activity"] == stamp(2)
    app.state.offices.store.create(
        {"id": "qa-office", "case_id": cid, "created_at": stamp(3), "completed_at": stamp(4)}
    )
    assert client.get("/api/cases").json()[0]["last_activity"] == stamp(4)


def test_closed_case_blocks_office_edit_and_generation(fiaga, pdf_bytes):
    from pqrs_claro.office_workspace import save_workspace

    app, client, _, _ = fiaga
    case, _ = managed_case(fiaga, pdf_bytes)
    cid = case["id"]
    assert (
        action(client, cid, 1, "state", state="closed", note="Cierre ficticio").status_code == 200
    )
    with pytest.raises(Conflict, match="finalizado"):
        save_workspace(app.state.offices, cid, None)
    with pytest.raises(Conflict, match="finalizado"):
        app.state.offices.generate(cid, {})
