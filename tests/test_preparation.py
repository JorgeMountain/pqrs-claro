# ruff: noqa: F811
"""Confirmar inicia los grafos una sola vez, conserva resultados y no aprueba."""

import time

from test_draft_service_api import FakeDraftEngine
from test_source_service_api import make_case, pdf_bytes, source_app, upload_source  # noqa: F401


def wait(app, client, case_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if case_id not in app.state.preparation.active:
            # Read after completion: the worker can finish between an HTTP
            # snapshot and the active-set check, leaving that snapshot stale.
            return client.get(f"/api/cases/{case_id}/preparation").json()
        time.sleep(0.03)
    raise AssertionError("La preparación no terminó")


def test_confirm_automatically_prepares_once_without_approval(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    engine = FakeDraftEngine()
    app.state.drafts.engine = engine
    case = make_case(client, pdf_bytes, confirm=False)
    upload_source(client)
    prefix = f"/api/cases/{case['id']}"
    first = client.post(prefix + "/confirm-and-prepare", json={"version": case["version"]})
    assert first.status_code == 202, first.text
    repeated = client.post(prefix + "/confirm-and-prepare", json={"version": case["version"]})
    assert repeated.status_code == 202
    assert repeated.json()["case"]["version"] == first.json()["case"]["version"]
    assert wait(app, client, case["id"])["status"] == "ready"
    rows = client.get(prefix + "/review").json()["requests"]
    assert len(rows) == 2 and all(r["paragraphs"] and r["approval"] is None for r in rows)
    calls = dict(engine.calls), dict(assessor.calls)
    for _ in range(3):
        assert client.get(prefix + "/preparation").json()["status"] == "ready"
    assert calls == (dict(engine.calls), dict(assessor.calls))
    client.post(prefix + "/preparation", json={"version": first.json()["case"]["version"]})
    assert calls == (dict(engine.calls), dict(assessor.calls))
    assert client.get(prefix + "/review").json()["requests"] == rows


def test_missing_sources_retains_confirmation_and_retry_works(source_app, pdf_bytes):
    app, client, _, _ = source_app
    app.state.drafts.engine = FakeDraftEngine()
    case = make_case(client, pdf_bytes, confirm=False)
    prefix = f"/api/cases/{case['id']}"
    response = client.post(prefix + "/confirm-and-prepare", json={"version": case["version"]})
    assert response.status_code == 202
    assert wait(app, client, case["id"])["status"] == "error"
    confirmed = client.get(prefix).json()
    assert confirmed["status"] == "confirmed"
    assert (
        client.post(prefix + "/preparation", json={"version": case["version"]}).status_code == 409
    )
    upload_source(client)
    client.post(prefix + "/preparation", json={"version": confirmed["version"]})
    assert wait(app, client, case["id"])["status"] == "ready"


def test_legacy_confirm_does_not_start_jobs(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case = make_case(client, pdf_bytes)
    assert client.get(f"/api/cases/{case['id']}/preparation").json()["status"] == "idle"
    assert not app.state.preparation.active and not assessor.calls


def test_updating_sources_preserves_saved_text(source_app, pdf_bytes):
    app, client, _, _ = source_app
    engine = FakeDraftEngine()
    app.state.drafts.engine = engine
    case = make_case(client, pdf_bytes, confirm=False)
    upload_source(client)
    prefix = f"/api/cases/{case['id']}"
    confirmed = client.post(
        prefix + "/confirm-and-prepare", json={"version": case["version"]}
    ).json()["case"]
    assert wait(app, client, case["id"])["status"] == "ready"
    row = client.get(prefix + "/review").json()["requests"][0]
    row["paragraphs"][0]["text"] = "Redacción revisada por la persona responsable."
    saved = client.put(
        prefix + f"/review/requests/{row['request_id']}",
        json=dict(
            revision=row["revision"],
            edited_by="Revisora de prueba",
            paragraphs=row["paragraphs"],
            pending_resolutions=[],
        ),
    )
    assert saved.status_code == 200, saved.text
    calls = dict(engine.calls)
    upload_source(client, content="Otra norma de prácticas y decisiones del comité.")
    client.post(prefix + "/preparation", json={"version": confirmed["version"]})
    assert wait(app, client, case["id"])["status"] == "ready"
    updated = client.get(prefix + "/review").json()["requests"][0]
    assert updated["paragraphs"] == row["paragraphs"]
    assert updated["approval"] is None
    assert dict(engine.calls) == calls


def test_recovery_marks_interruption_without_running_again(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case = make_case(client, pdf_bytes)
    service = app.state.preparation
    service.save(dict(case_id=case["id"], version=case["version"],
                      status="running", stage="sources"))
    service.recover()
    result = client.get(f"/api/cases/{case['id']}/preparation").json()
    assert result["status"] == "interrupted"
    assert result["error"] and not result["stale"]
    assert not service.active and not assessor.calls
