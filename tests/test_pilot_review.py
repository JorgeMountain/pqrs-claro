# ruff: noqa: F811
from copy import deepcopy

from test_fiaga_flow import full_flow, information_pdf  # noqa: F401
from test_initial_review import wait_intake
from test_preparation import wait
from test_source_service_api import make_case, upload_source


def test_pilot_continues_stale_review_without_approving_it(full_flow, information_pdf):
    app, client, _ = full_flow
    case = make_case(client, information_pdf, confirm=False)
    report = wait_intake(app, client, case)
    prefix = f"/api/cases/{case['id']}"
    assert upload_source(client).status_code == 201
    assert client.get(prefix + "/initial-review").json()["stale"]
    before = deepcopy(app.state.initial_review.saved(case["id"]))
    body = dict(version=case["version"], revision=report["revision"], enabled=True)
    assert (
        client.put(prefix + "/initial-review/pilot-mode", json={**body, "version": 999}).status_code
        == 409
    )
    result = client.put(prefix + "/initial-review/pilot-mode", json=body)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["pilot_bypass_active"] and value["can_prepare"] and value["stale"]
    assert value["status"] == before["status"]
    assert value["report"] == before["report"]
    assert value["decisions"] == before["decisions"]
    latest = client.get(prefix).json()
    assert latest["status"] == "confirmed"
    assert (
        client.post(prefix + "/preparation", json={"version": latest["version"]}).status_code == 202
    )
    job = wait(app, client, case["id"])
    assert job["status"] == "ready", job
    assert app.state.drafts.get(case["id"])["results"]
    disabled = client.put(
        prefix + "/initial-review/pilot-mode",
        json={
            "version": latest["version"],
            "revision": value["revision"],
            "enabled": False,
        },
    )
    assert disabled.status_code == 200, disabled.text
    assert not disabled.json()["can_prepare"]
    assert (
        client.post(prefix + "/preparation", json={"version": latest["version"]}).status_code == 409
    )


def test_pilot_permission_expires_if_identification_changes(full_flow, information_pdf):
    app, client, _ = full_flow
    case = make_case(client, information_pdf, confirm=False)
    report = wait_intake(app, client, case)
    prefix = f"/api/cases/{case['id']}"
    assert (
        client.put(
            prefix + "/initial-review/pilot-mode",
            json={
                "version": case["version"],
                "revision": report["revision"],
                "enabled": True,
            },
        ).status_code
        == 200
    )
    saved = app.state.store.get(case["id"])
    changed = deepcopy(saved["identification"])
    changed["requests"][0]["description"] += " Modificación posterior."
    app.state.store.update(case["id"], identification=changed)
    assert not client.get(prefix + "/initial-review").json()["pilot_bypass_active"]
