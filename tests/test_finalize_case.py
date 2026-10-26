"""Cerrar y consultar conserva el expediente y los archivos; proveedores ficticios."""
# ruff: noqa: F811 -- pytest fixture imported intentionally.

from copy import deepcopy

import pytest
from test_initial_review import analyze, decision, fiaga  # noqa: F401
from test_management import action
from test_office_service_api import (
    approved_case,
    generate,
    inputs,
    office_app,  # noqa: F401
    url,
    wait_office,
)
from test_office_workspace import body as workspace_body
from test_source_service_api import pdf_bytes  # noqa: F401

from pqrs_claro.storage import Conflict


def test_finalize_preserves_saved_content_exports_and_reopening(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client, count=2)
    cid = case["id"]
    generation_input = inputs(client, case)
    run = wait_office(app, client, case, generate(client, case, generation_input))
    assert run["status"] == "ready"
    claimed = action(client, cid, 0, "claim")
    assert claimed.status_code == 200, claimed.text
    management = claimed.json()
    # Enforce the same closed-case protection as the managed local app.
    app.state.store.management = app.state.management
    saved = deepcopy(app.state.store.get(cid))
    reviews = client.get(f"/api/cases/{cid}/review").json()
    work = client.get(url(case, "/workspace")).json()
    files = {kind: client.get(url(case, f"/runs/{run['id']}/files/{kind}")).content
             for kind in ("docx", "pdf")}
    original = client.get(f"/api/cases/{cid}/original").content
    runs = deepcopy(app.state.offices.store.list(cid))
    calls = renderer.calls

    # Another manager cannot close it, and rejection changes no saved content.
    assert action(client, cid, management["revision"], "state", actor="gestor-2",
                  state="closed", note="Cierre de prueba").status_code == 409
    closed = action(client, cid, management["revision"], "state", state="closed",
                    note="Finalizado desde Borrador con el oficio revisado y generado.")
    assert closed.status_code == 200, closed.text
    listing = next(row for row in client.get("/api/cases").json() if row["id"] == cid)
    assert listing["management"]["state"] == "closed"
    assert listing["office_progress"]["status"] == "ready"
    assert app.state.store.get(cid) == saved
    assert client.get(f"/api/cases/{cid}/review").json() == reviews
    assert client.get(url(case, "/workspace")).json() == work
    assert app.state.offices.store.list(cid) == runs
    assert client.get(f"/api/cases/{cid}/original").content == original
    for kind, content in files.items():
        response = client.get(url(case, f"/runs/{run['id']}/files/{kind}"))
        assert response.status_code == 200, response.text
        assert response.content == content
    assert client.get(url(case, f"/runs/{run['id']}/pages/1")).status_code == 200
    assert client.post(url(case, "/preview"), json=generation_input).status_code == 200
    assert client.post(url(case, "/generate"), json={
        **generation_input, "preview_hash": run["preview_hash"]
    }).status_code == 409
    assert client.put(url(case, "/workspace"), json=workspace_body(work)).status_code == 409
    assert renderer.calls == calls
    history = client.get(f"/api/cases/{cid}/management/history").json()
    assert history[0]["after"]["state"] == "closed"
    assert history[0]["actor_id"] == "gestor-1"

    # Reopening uses the existing management flow, without reanalysis or export.
    reopened = action(client, cid, closed.json()["revision"], "state",
                      state="in_progress", note="Corrección posterior de prueba")
    assert reopened.status_code == 200, reopened.text
    assert app.state.store.get(cid) == saved
    assert client.get(f"/api/cases/{cid}/review").json() == reviews
    assert app.state.offices.store.list(cid) == runs
    assert renderer.calls == calls


def test_closed_keeps_confirmed_initial_decision_readable_but_blocks_work(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    cid = case["id"]
    assert client.put(f"/api/cases/{cid}/initial-review/decision",
                      json=decision(row)).status_code == 200
    app.state.store.management = app.state.management
    claimed = action(client, cid, 0, "claim").json()
    assert action(client, cid, claimed["revision"], "state", state="closed",
                  note="Cierre de prueba").status_code == 200
    before = app.state.initial_review.saved(cid)
    assert not app.state.initial_review.get(cid)["can_prepare"]
    app.state.initial_review.assert_allowed(cid, read_only=True)
    with pytest.raises(Conflict, match="finalizado"):
        app.state.initial_review.assert_allowed(cid)
    assert app.state.initial_review.saved(cid) == before
