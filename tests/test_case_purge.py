"""Permanent deletion is explicit, isolated, retryable and permits a fresh import."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_app import analyze, upload
from test_case_lifecycle import action
from test_gmail import connect, ingest, mail_app  # noqa: F401
from test_unified_app import pdf_bytes, unified  # noqa: F401

from pqrs_claro import case_purge


def trash(client, case):
    path = "/api/cases/" + case["id"]
    assert client.request("DELETE", path, json=action(case)).status_code == 200
    return path


def test_guardrails(unified, pdf_bytes):  # noqa: F811
    app, client, _, _ = unified
    case = upload(client, pdf_bytes)
    path = "/api/cases/" + case["id"]
    assert client.request("DELETE", path + "/permanent", json=action(case)).status_code == 409
    trash(client, case)
    for body, status in (
        (action(case, 1, False), 422),
        (action(case, 1, "true"), 422),
        (action(case), 409),
        ({**action(case, 1), "version": 9}, 409),
    ):
        assert client.request("DELETE", path + "/permanent", json=body).status_code == status
    assert (
        client.request(
            "DELETE",
            path + "/permanent",
            json=action(case, 1),
            headers={"origin": "https://outside.example"},
        ).status_code
        == 403
    )
    app.state.preparation.active.add(case["id"])
    try:
        assert (
            client.request("DELETE", path + "/permanent", json=action(case, 1)).status_code == 409
        )
    finally:
        app.state.preparation.active.remove(case["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(
                lambda _: client.request(
                    "DELETE", path + "/permanent", json=action(case, 1)
                ).status_code,
                range(2),
            )
        )
    assert statuses.count(200) == 1 and set(statuses) <= {200, 404, 409}
    assert client.get(path).status_code == 404
    assert client.post(path + "/restore", json=action(case, 1)).status_code == 404


def test_cleanup_is_scoped_and_removes_checkpoint_history(unified, pdf_bytes):  # noqa: F811
    app, client, _, settings = unified
    case = analyze(client, upload(client, pdf_bytes))
    other = upload(client, pdf_bytes)
    cid = case["id"]
    library = app.state.library
    private = library.add(
        "private.txt",
        b"Private evidence",
        title="Private",
        origin="QA",
        category="case_evidence",
        case_id=cid,
    )
    shared = library.add(
        "shared.txt", b"Shared evidence", title="Shared", origin="QA", category="institutional_norm"
    )
    library.review(
        private["id"], case_id=cid, reviewed_by="QA", review_note="Checked", validity="current"
    )
    root = settings.data_dir
    folder = root / "oficios" / cid / "run"
    folder.mkdir(parents=True)
    (folder / "oficio.pdf").write_bytes(b"export")
    # All case-keyed persistence families, including lazily created editor state.
    families = {
        "expedientes.sqlite": ("revisions", "preparations"),
        "biblioteca.sqlite": ("source_runs", "evidence_receipts"),
        "borradores.sqlite": ("draft_runs",),
        "revisiones.sqlite": (
            "review_requests",
            "review_history",
            "review_approvals",
            "response_proposals",
            "office_workspace",
        ),
        "oficios.sqlite": ("office_runs",),
    }
    for name, names in families.items():
        with sqlite3.connect(root / name) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS office_workspace "
                "(case_id TEXT PRIMARY KEY, revision INTEGER, body TEXT)"
            ) if name == "revisiones.sqlite" else None
            for table in names:
                columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
                for target in (cid, other["id"]):
                    values = [
                        target
                        if col in {"case_id", "id"}
                        else 99
                        if col in {"version", "revision"}
                        else "{}"
                        for col in columns
                    ]
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' for _ in values)})",
                        values,
                    )
    for name in (
        "checkpoints.sqlite",
        "source_checkpoints.sqlite",
        "draft_checkpoints.sqlite",
        "review_checkpoints.sqlite",
    ):
        with sqlite3.connect(root / name) as conn:
            if name == "checkpoints.sqlite":
                # Real identification checkpoints were produced above.
                assert conn.execute(
                    "SELECT count(*) FROM checkpoints WHERE thread_id=?", (cid,)
                ).fetchone()[0]
                continue
            for table in ("checkpoints", "writes"):
                conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (thread_id TEXT)")
                prefix = "review:" if name == "review_checkpoints.sqlite" else ""
                conn.executemany(
                    f"INSERT INTO {table} VALUES (?)",
                    [(prefix + target + ":request:run",) for target in (cid, other["id"])],
                )
    path = trash(client, case)
    result = client.request("DELETE", path + "/permanent", json=action(case, 1))
    assert result.status_code == 200, result.text
    assert not (root / "files" / cid).exists() and not (root / "oficios" / cid).exists()
    assert not (root / "library" / private["id"]).exists()
    with pytest.raises(KeyError):
        library.get(private["id"], cid)
    assert library.original(shared["id"]).read_bytes() == b"Shared evidence"
    assert client.get("/api/cases/" + other["id"] + "/original").content == pdf_bytes
    for name, names in families.items():
        with sqlite3.connect(root / name) as conn:
            for table in names:
                assert (
                    conn.execute(
                        f"SELECT count(*) FROM {table} WHERE case_id=?", (cid,)
                    ).fetchone()[0]
                    == 0
                )
                assert (
                    conn.execute(
                        f"SELECT count(*) FROM {table} WHERE case_id=?", (other["id"],)
                    ).fetchone()[0]
                    == 1
                )
    for name in root.glob("*checkpoints.sqlite"):
        with sqlite3.connect(name) as conn:
            for table in ("checkpoints", "writes"):
                assert not any(cid in r[0] for r in conn.execute(f"SELECT thread_id FROM {table}"))
                if name.name != "checkpoints.sqlite":
                    assert any(
                        other["id"] in r[0] for r in conn.execute(f"SELECT thread_id FROM {table}")
                    )


def test_partial_failure_can_only_be_retried(unified, pdf_bytes, monkeypatch):  # noqa: F811
    app, client, _, _ = unified
    case = upload(client, pdf_bytes)
    path = trash(client, case)
    cleanup = case_purge.purge_checkpoints
    monkeypatch.setattr(
        case_purge, "purge_checkpoints", lambda *args: (_ for _ in ()).throw(OSError("locked"))
    )
    assert client.request("DELETE", path + "/permanent", json=action(case, 1)).status_code == 409
    assert client.post(path + "/restore", json=action(case, 1)).status_code == 409
    assert len(app.state.store.list(deleted=True)) == 1
    monkeypatch.setattr(case_purge, "purge_checkpoints", cleanup)
    assert client.request("DELETE", path + "/permanent", json=action(case, 1)).status_code == 200
    assert app.state.store.list(deleted=True) == []


@pytest.mark.parametrize("mid,mode", [("m1", "pdf"), ("m2", "body")])
def test_mail_reimport_starts_fresh_and_stays_idempotent(mail_app, mid, mode):  # noqa: F811
    app, client, _, google, _ = mail_app
    connect(client)
    cid = ingest(client, mid, mode).json()["case_id"]
    assert ingest(client, "m3", "link", target_case_id=cid).status_code == 200
    case = client.get("/api/cases/" + cid).json()
    path = trash(client, case)
    assert client.request("DELETE", path + "/permanent", json=action(case, 1)).status_code == 200
    for mail_id in (mid, "m3"):
        detail = client.get(f"/api/gmail/messages/{mail_id}?account=prueba@example.org").json()
        assert detail["case_id"] is None and not detail["related_cases"]
        assert (
            client.get("/api/gmail/originals/" + detail["key"]).content == google.messages[mail_id]
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ingest(client, mid, mode).json(), range(2)))
    assert len({r["case_id"] for r in results}) == 1
    assert sum(r["duplicate"] for r in results) == 1
    new_id = results[0]["case_id"]
    assert new_id != cid
    fresh = client.get("/api/cases/" + new_id).json()
    assert fresh["status"] == "uploaded" and fresh["version"] == 1
    assert fresh["pages"] == [] and fresh["identification"] is None
    assert len(app.state.store.list()) == 1
    assert all(r.method == "GET" or r.url.path == "/token" for r in google.calls)


def test_cannot_remove_outside_storage(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    with pytest.raises(ValueError):
        case_purge.remove_folder(tmp_path, "files", "../outside")
    assert (outside / "keep.txt").read_text() == "keep"


def test_purge_releases_import_interrupted_before_receipt(mail_app, monkeypatch):  # noqa: F811
    app, client, _, _, _ = mail_app
    connect(client)
    save = app.state.gmail.save
    client.get("/api/gmail/messages/m1?account=prueba@example.org")
    monkeypatch.setattr(
        app.state.gmail, "save", lambda row: (_ for _ in ()).throw(RuntimeError("interrupted"))
    )
    with pytest.raises(RuntimeError):
        ingest(client)
    monkeypatch.setattr(app.state.gmail, "save", save)
    case = app.state.store.get(app.state.store.list()[0]["id"])
    path = trash(client, case)
    assert client.request("DELETE", path + "/permanent", json=action(case, 1)).status_code == 200
    result = ingest(client)
    assert result.status_code == 200 and result.json()["case_id"] != case["id"]
    assert not result.json()["duplicate"]


def test_shared_verifications_keep_other_case_backing(unified, pdf_bytes):  # noqa: F811
    app, client, _, settings = unified
    case = upload(client, pdf_bytes)
    other = upload(client, pdf_bytes)
    with sqlite3.connect(settings.data_dir / "comprobaciones.sqlite") as conn:
        for vid in ("private", "reused"):
            conn.execute(
                "INSERT INTO verifications VALUES (?,?,?,?,?,?)",
                (vid, case["id"], None, "human_review", vid, "{}"),
            )
            conn.execute(
                "INSERT INTO verification_events VALUES (?,?,?,?)", (vid, "verification", vid, "{}")
            )
        conn.execute(
            "INSERT INTO verification_applications VALUES (?,?,?,?)",
            ("local", case["id"], "private", "{}"),
        )
        conn.execute(
            "INSERT INTO verification_applications VALUES (?,?,?,?)",
            ("external", other["id"], "reused", "{}"),
        )
        conn.execute(
            "INSERT INTO verification_events VALUES (?,?,?,?)",
            ("local-app", "application", "local", "{}"),
        )
    path = trash(client, case)
    assert client.request("DELETE", path + "/permanent", json=action(case, 1)).status_code == 200
    with sqlite3.connect(settings.data_dir / "comprobaciones.sqlite") as conn:
        assert conn.execute("SELECT id FROM verifications").fetchall() == [("reused",)]
        assert conn.execute("SELECT id FROM verification_events").fetchall() == [("reused",)]
        assert conn.execute("SELECT id FROM verification_applications").fetchall() == [
            ("external",)
        ]
