"""Polling for Redacción only sees changes to the case's permitted sources and results."""
# ruff: noqa: F811 (pytest fixtures imported from the scope regression suite)

import json

from test_source_scope_revocation import COLLECTION, env  # noqa: F401


def notice(client, case_id):
    response = client.get(f"/api/cases/{case_id}/source-collections?watch_redaction=true")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    value = response.json()
    assert set(value) == {"collection_ids", "correction_revision", "result_revision"}
    return value


def version(library, previous, payload):
    return library.add(
        previous["filename"], payload.encode(), title=previous["title"],
        origin="Ficticio", category=previous["category"], case_id=previous.get("case_id"),
        collection_id=previous.get("collection_id"), document_id=previous["document_id"],
    )


def test_document_revision_is_isolated_by_case_and_linked_collection(env):
    app, client, case, restricted, public, path, _ = env
    lib, cid = app.state.library, case["id"]
    other = app.state.store.create("Otro.pdf", b"%PDF-1.4 otro")["id"]
    first, second = notice(client, cid), notice(client, other)
    assert first["collection_ids"] == [COLLECTION] and second["collection_ids"] == []
    assert client.get(path + "/source-collections").json() == {"collection_ids": [COLLECTION]}

    private = lib.add("privado.txt", b"Fecha privada inicial.", title="Registro privado",
                      origin="Ficticio", category="case_evidence", case_id=other)
    version(lib, private, "Nueva fecha privada del otro expediente.")
    changed_other = notice(client, other)
    assert changed_other["correction_revision"] != second["correction_revision"]
    assert notice(client, cid) == first

    changed = version(lib, restricted, "Nueva fecha de la colección acotada.")
    current = notice(client, cid)
    assert current["correction_revision"] != first["correction_revision"]
    assert current["result_revision"] == first["result_revision"]
    assert notice(client, other) == changed_other
    assert changed["id"] not in json.dumps(current) and changed["title"] not in json.dumps(current)
    # Duplicate import creates no new version or notification.
    version(lib, changed, "Nueva fecha de la colección acotada.")
    assert notice(client, cid) == current

    shared = version(lib, public, "Reglamento corregido aplicable a ambos expedientes.")
    third = notice(client, cid)
    assert third["correction_revision"] != current["correction_revision"]
    assert notice(client, other)["correction_revision"] != changed_other["correction_revision"]

    with lib.connect() as conn:
        conn.execute("UPDATE sources SET body=json_set(body,'$.extraction_revision',3) "
                     "WHERE id=?", (public["id"],))
        conn.execute("UPDATE sources SET pages=pages WHERE id=?", (shared["id"],))
    assert notice(client, cid) == third

    with lib.connect() as conn:
        conn.execute("UPDATE sources SET body=json_set(body,'$.extraction_revision',2) "
                     "WHERE id=?", (shared["id"],))
        conn.rollback()
    assert notice(client, cid) == third
    with lib.connect() as conn:
        conn.execute("UPDATE sources SET body=json_set(body,'$.extraction_revision',2) "
                     "WHERE id=?", (shared["id"],))
    assert notice(client, cid)["correction_revision"] != third["correction_revision"]
    client.put(path + "/source-collections", json={"collection_ids": []}).raise_for_status()
    reduced = notice(client, cid)
    assert reduced["collection_ids"] == []
    version(lib, changed, "Datos restringidos después de la revocación.")
    assert notice(client, cid) == reduced


def test_notice_survives_instant_recalculation_and_excludes_progress_reads(env, monkeypatch):
    app, client, case, _, _, path, _ = env
    cid = case["id"]
    lib = app.state.library
    original = notice(client, cid)
    other = app.state.store.create("Otro.pdf", b"%PDF-1.4 otro")["id"]
    run = {"id": "otro-run", "case_id": other, "status": "ready"}
    lib.save_run(run)
    app.state.preparation.save({"case_id": other, "version": 1, "status": "ready"})
    assert notice(client, cid) == original
    run = {"id": "test-run", "case_id": cid, "status": "running", "results": []}
    job = {"case_id": cid, "version": case["version"], "status": "running", "stage": "sources"}
    lib.save_run(run)
    app.state.preparation.save(job)
    lib.save_run_progress({**run, "completed_count": 1})
    app.state.preparation.save(job, stage="points")
    assert notice(client, cid) == original
    lib.save_run({**run, "status": "ready"})
    mapped = notice(client, cid)
    assert mapped["result_revision"] != original["result_revision"]
    assert mapped["correction_revision"] == original["correction_revision"]
    app.state.preparation.save(job, status="waiting_review")
    terminal = notice(client, cid)
    assert terminal["result_revision"] != mapped["result_revision"]
    # A subsequent complete cycle can happen while the tab is in the background.
    app.state.preparation.save(job, status="running")
    app.state.preparation.save(job, status="waiting_review")
    again = notice(client, cid)
    assert again["result_revision"] != terminal["result_revision"]
    assert again["correction_revision"] == mapped["correction_revision"]

    def expensive(*args, **kwargs):
        raise AssertionError("A watcher should not materialize cases, results or source content")
    monkeypatch.setattr(app.state.store, "get", expensive)
    monkeypatch.setattr(lib, "latest_run", expensive)
    monkeypatch.setattr(lib, "original", expensive)
    monkeypatch.setattr(lib, "scoped", expensive)
    for _ in range(3):
        assert notice(client, cid) == again
    missing = client.get("/api/cases/unknown/source-collections?watch_redaction=true")
    assert missing.status_code == 404


def test_watch_respects_trashed_case(env):
    app, client, case, _, _, path, _ = env
    app.state.store.set_deleted(case["id"], version=case["version"], lifecycle_revision=0,
                                deleted=True)
    response = client.get(path + "/source-collections?watch_redaction=true")
    assert response.status_code == 409
    assert "correction_revision" not in response.text and COLLECTION not in response.text
