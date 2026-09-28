# ruff: noqa: F811, F401
from concurrent.futures import ThreadPoolExecutor

from test_app import pdf_bytes, upload, wait_ready
from test_unified_app import unified

from pqrs_claro.management import ManagementAction, ManagementStore
from pqrs_claro.storage import Conflict


def action(client, cid, revision, kind, actor="gestor-1", **kwargs):
    return client.post(
        f"/api/cases/{cid}/management",
        json=dict(revision=revision, actor_id=actor, action=kind, **kwargs),
    )


def test_receive_take_start_preserves_entire_case(unified, pdf_bytes):
    app, client, identifier, settings = unified
    app.state.service.management = app.state.management
    received = client.post(
        "/api/cases",
        files={"file": ("original.pdf", pdf_bytes, "application/pdf")},
        data={
            "subject": "Diez peticiones en un documento",
            "reference": "RAD-1",
            "received_date": "2026-09-27",
        },
    ).json()
    cid = received["id"]
    listing = client.get("/api/cases").json()[0]
    assert listing["subject"] == "Diez peticiones en un documento"
    assert listing["management"]["state"] == "received"
    assert listing["management"]["owner_id"] is None and identifier.calls == 0
    assert client.post(f"/api/cases/{cid}/analyze").status_code == 409
    assert action(client, cid, 0, "start").status_code == 409
    assert action(client, cid, 0, "claim").status_code == 200
    assert identifier.calls == 0
    assert action(client, cid, 1, "start", actor="gestor-2").status_code == 409
    assert action(client, cid, 1, "start").status_code == 200
    wait_ready(client, cid)
    assert identifier.calls == 1
    assert client.get(f"/api/cases/{cid}/original").content == pdf_bytes
    assert action(client, cid, 2, "start").status_code == 409
    assert (
        action(client, cid, 2, "state", state="pending", note="Esperando anexo").status_code == 200
    )
    assert ManagementStore(app.state.store).get(cid)["state"] == "pending"
    assert len(client.get(f"/api/cases/{cid}/management/history").json()) == 3


def test_two_managers_cannot_take_same_case(unified, pdf_bytes):
    app, client, _, _ = unified
    cid = upload(client, pdf_bytes)["id"]

    def take(actor):
        try:
            app.state.management.change(
                cid, ManagementAction(revision=0, actor_id=actor, action="claim")
            )
            return "ok"
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(take, ["gestor-1", "gestor-2"])) == ["conflict", "ok"]
    assert len(app.state.management.history(cid)) == 1


def test_reassignment_metadata_and_stale_action(unified, pdf_bytes):
    app, client, _, _ = unified
    original = upload(client, pdf_bytes)
    cid = original["id"]
    assert (
        action(
            client, cid, 0, "metadata", subject="Asunto manual", due_date="2020-01-01"
        ).status_code
        == 422
    )
    assert (
        action(
            client,
            cid,
            0,
            "metadata",
            subject="Asunto manual",
            reference="X",
            received_date="2026-09-27",
            due_date="2026-10-01",
        ).status_code
        == 200
    )
    assert (
        action(
            client, cid, 1, "assign", manager_id="gestor-2", note="Distribucion piloto"
        ).status_code
        == 200
    )
    assert action(client, cid, 1, "claim").status_code == 409
    assert (
        action(client, cid, 2, "assign", manager_id="gestor-1", note="Reasignacion").status_code
        == 200
    )
    # Management edits must not invalidate identification/content versions.
    assert app.state.store.get(cid) == original
    assert app.state.management.get(cid)["owner_id"] == "gestor-1"


def test_legacy_cases_keep_analysis_and_trash_rejects_assignment(unified, pdf_bytes):
    app, client, _, _ = unified
    original = upload(client, pdf_bytes)
    cid = original["id"]
    app.state.store.update(
        cid, status="needs_review", identification={"subject": "Anterior", "requests": []}
    )
    assert app.state.management.get(cid)["state"] == "in_progress"
    assert action(client, cid, 0, "claim").status_code == 200
    case = app.state.store.get(cid)
    response = client.request(
        "DELETE",
        f"/api/cases/{cid}",
        json={"version": case["version"], "lifecycle_revision": 0, "management_revision": 1,
              "confirmed": True},
    )
    assert response.status_code == 200
    assert action(client, cid, 1, "assign", manager_id="gestor-2", note="test").status_code == 409
    assert len(client.get("/api/cases?deleted=true").json()) == 1


def test_repeated_manager_and_invalid_receipt(unified, pdf_bytes):
    app, client, _, _ = unified
    one = client.post("/api/managers", json={"name": "Ana"}).json()
    two = client.post("/api/managers", json={"name": " ana "}).json()
    assert one == two
    assert client.post("/api/managers", json={"name": "   "}).status_code == 422
    response = client.post(
        "/api/cases",
        files={"file": ("bad.pdf", pdf_bytes, "application/pdf")},
        data={"received_date": "2026-09-27", "due_date": "2026-09-01"},
    )
    assert response.status_code == 422
    assert not app.state.store.list()
