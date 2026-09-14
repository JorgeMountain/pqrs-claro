from copy import deepcopy

from test_office_service_api import inputs, metadata, office_app, preview
from test_review_service_api import approve, assess, current, prepare

def test_valid_previous_analysis_remains_current_but_changes_and_errors_do_not(
    office_app, monkeypatch
):
    from pqrs_claro import source_service

    app, client, _, _ = office_app
    monkeypatch.setattr(source_service, "SOURCE_ANALYSIS_VERSION", 14)
    case, _, _ = prepare(app, client)
    row = assess(app, client, case, current(client, case))
    run = app.state.library.latest_run(case["id"])
    monkeypatch.setattr(source_service, "SOURCE_ANALYSIS_VERSION", 15)
    assert not app.state.sources.get(case["id"])["stale"]
    assert current(client, case)["assessment"] == row["assessment"]
    assert app.state.library.latest_run(case["id"])["fingerprint"] == run["fingerprint"]
    original_catalog = app.state.sources.catalog
    with monkeypatch.context() as changed:
        changed.setattr(
            app.state.sources, "catalog", lambda cid: original_catalog(cid) + [{"changed": True}]
        )
        assert app.state.sources.get(case["id"])["stale"]
    run["results"][0]["evidence_states"] = ["analysis_error"]
    app.state.library.save_run(run)
    assert app.state.sources.get(case["id"])["stale"]


def endpoint(case):
    return f"/api/cases/{case['id']}/office/workspace"


def body(work):
    return {
        "revision": work["revision"],
        "metadata": work["metadata"],
        "edited_by": "Responsable de prueba",
        "attachment_source_ids": work["attachment_source_ids"],
        "requests": [
            {k: row[k] for k in ("request_id", "revision", "paragraphs")}
            for row in work["requests"]
        ],
    }


def test_working_document_before_approval_and_export_fidelity(office_app):
    app, client, _, _ = office_app
    case, _, _ = prepare(app, client)
    response = client.get(endpoint(case))
    assert response.status_code == 200, response.text
    work = response.json()
    assert work["revision"] == 0
    assert work["blocks"] and current(client, case)["approval"] is None
    data = deepcopy(body(work))
    data["metadata"] = {
        **work["metadata"],
        **metadata(),
        "introduction": "Introducción editada para el caso ficticio.",
    }
    data["requests"][0]["paragraphs"][0]["text"] += " Texto editado para la prueba."
    saved = client.put(endpoint(case), json=data)
    assert saved.status_code == 200, saved.text
    saved = saved.json()
    assert client.get(endpoint(case)).json()["metadata"] == saved["metadata"]
    row = current(client, case)
    assert row["paragraphs"] == saved["requests"][0]["paragraphs"] and row["approval"] is None
    checked = assess(app, client, case, row)
    assert approve(client, case, checked).status_code == 200
    final = preview(client, case, inputs(client, case, metadata=saved["metadata"]))
    working = client.get(endpoint(case)).json()
    assert [(b["kind"], b["text"]) for b in working["blocks"]] == [
        (b["kind"], b["text"]) for b in final["document"]["blocks"]
    ]


def test_atomic_conflict_does_not_save_other_text_or_metadata(office_app):
    app, client, _, _ = office_app
    case, _, _ = prepare(app, client, count=2)
    work = client.get(endpoint(case)).json()
    data = deepcopy(body(work))
    data["metadata"]["subject"] = "No debe guardarse"
    data["requests"][0]["paragraphs"][0]["text"] += " No debe guardarse."
    data["requests"][1]["revision"] += 1
    result = client.put(endpoint(case), json=data)
    assert result.status_code == 409, result.text
    after = client.get(endpoint(case)).json()
    assert after["revision"] == work["revision"]
    assert after["metadata"] == work["metadata"]
    assert after["requests"] == work["requests"]


def test_only_changed_response_loses_approval_and_workspace_has_cas(office_app):
    app, client, _, _ = office_app
    case, _, _ = prepare(app, client, count=2)
    for rid in ("P1", "P2"):
        assert (
            approve(client, case, assess(app, client, case, current(client, case, rid))).status_code
            == 200
        )
    work = client.get(endpoint(case)).json()
    data = deepcopy(body(work))
    data["requests"][0]["paragraphs"][0]["text"] += " Ajuste humano."
    saved = client.put(endpoint(case), json=data)
    assert saved.status_code == 200, saved.text
    assert current(client, case, "P1")["approval"] is None
    assert current(client, case, "P2")["approval"] == work["requests"][1]["approval"]
    assert client.put(endpoint(case), json=data).status_code == 409
    empty = deepcopy(body(saved.json()))
    empty["requests"][0]["paragraphs"][0]["text"] = ""
    assert client.put(endpoint(case), json=empty).status_code == 422
