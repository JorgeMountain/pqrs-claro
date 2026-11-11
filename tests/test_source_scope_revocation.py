"""Case HTTP reads must respect a withdrawn collection before any new search."""

import json
import threading

import pytest
from fastapi.testclient import TestClient
from test_history_import import confirmed_case
from test_source_service_api import start_search, wait_search

from pqrs_claro import source_service
from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.source_library import make_chunks

COLLECTION = "coleccion-retirable"
QUOTE = "El comité de prácticas autorizó la plaza ZETA en el acta restringida."
TITLE = "Acta restringida de prácticas ZETA"
PENDING = "Falta confirmar la decisión concreta del comité."


class Reader:
    def __init__(self):
        self.calls = []

    def assess(self, request, candidates):
        self.calls.append(request["id"])
        supports = [{**item, "role": "rule", "reason": "Texto del documento de prueba"}
                    for item in candidates]
        restricted = any(item.get("collection_id") == COLLECTION for item in supports)
        missing = [] if restricted else [{"kind": "clarification", "description": PENDING}]
        return dict(request_id=request["id"], status="references_found", supports=supports,
                    summary=QUOTE if restricted else "El reglamento solo indica el procedimiento.",
                    missing=missing, warnings=[])


@pytest.fixture(params=["workspace", "recorrido"])
def env(tmp_path, request):
    reader = Reader()
    app = create_app(Settings(data_dir=tmp_path, model="lector-local", source_concurrency=1),
                     source_assessor=reader, interface=request.param)
    with TestClient(app) as client:
        case = confirmed_case(app)
        library = app.state.library
        library.save_collection({"id": COLLECTION, "title": "Colección de prueba"})
        restricted = library.add(
            "acta-zeta.txt", QUOTE.encode(), title=TITLE, category="historical_attachment",
            origin="Ficticio", collection_id=COLLECTION)
        common = library.add(
            "reglamento.txt", b"El comite de practicas decide sobre la plaza.",
            title="Reglamento del comité de prácticas", category="institutional_norm",
            origin="Ficticio")
        path = f"/api/cases/{case['id']}"
        assert client.put(path + "/source-collections",
                          json={"collection_ids": [COLLECTION]}).status_code == 200
        yield app, client, case, restricted, common, path, reader


def assert_hidden(client, path, source, *, status="stale"):
    for params in ({}, {"compact": True}):
        response = client.get(path + "/sources", params=params)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == status and body["stale"] and body["scope_revoked"]
        assert body["results"] == body["shared_checks"] == []
        assert body["source_count"] == 1
        serialized = json.dumps(body, ensure_ascii=False)
        for value in (QUOTE, TITLE, COLLECTION, source["id"], source["document_id"],
                      source["sha256"]):
            assert value not in serialized


def test_scope_poll_respects_case_lifecycle(env):
    app, client, case, _, _, path, _ = env
    route = path + "/source-collections"
    assert client.get(route).json() == {"collection_ids": [COLLECTION]}
    assert client.get("/api/cases/unknown/source-collections").status_code == 404
    app.state.store.set_deleted(case["id"], version=case["version"], lifecycle_revision=0,
                                deleted=True)
    response = client.get(route)
    assert response.status_code == 409 and COLLECTION not in response.text


def test_unlink_hides_quote_and_related_reads_until_scoped_search_finishes(env):
    app, client, case, restricted, common, path, _ = env
    receipt = client.post("/api/evidence", data={
        "case_id": case["id"], "version": case["version"], "request_id": "P1", "shared": True,
        "category": "historical_attachment", "title": TITLE, "origin": QUOTE,
    }, files={"file": ("acta-zeta.txt", QUOTE.encode(), "text/plain")})
    assert receipt.status_code == 201 and receipt.json()["source_id"] == restricted["id"]
    original = wait_search(app, client, case["id"])
    assert original["status"] == "ready" and QUOTE in original["results"][0]["summary"]
    assert {s["source_id"] for s in original["results"][0]["supports"]} == {
        restricted["id"], common["id"]}
    detail = client.get(f"/api/sources/{restricted['id']}", params={"case_id": case["id"]}).json()
    chunk = make_chunks(detail["source"], detail["pages"])[0]
    passage = {k: chunk[k] for k in ("page", "line_start", "line_end", "chunk_id", "quote")}
    record = client.post(path + "/verifications", json={
        "version": case["version"], "fact": QUOTE, "basis": QUOTE, "recorded_by": "Prueba",
        "source_id": restricted["id"], "passage": passage, "request_ids": ["P1"],
    })
    assert record.status_code == 201, record.text
    app.state.verifications.apply(case["id"], record.json()["id"], case["version"],
                                  request_ids=["P1"], check_key="ficticio", basis=QUOTE,
                                  recorded_by="Revisor ficticio")
    assert client.get(path + "/verifications").json()["records"][0]["passage"]["quote"] == QUOTE
    assert client.get(path + "/evidence").json()["receipts"][0]["origin"] == QUOTE
    assert client.put(path + "/source-collections", json={"collection_ids": []}).status_code == 200

    assert_hidden(client, path, restricted)
    assert client.get(path + "/verifications").json() == {"records": [], "applications": []}
    evidence = client.get(path + "/evidence").json()
    assert evidence["receipts"] == [] and evidence["mapping"]["results"] == []
    sources = client.get("/api/sources", params={"case_id": case["id"]}).json()["sources"]
    assert [item["id"] for item in sources] == [common["id"]]
    for suffix in ("", "/versions", "/original", "/pages/1.png"):
        assert client.get(f"/api/sources/{restricted['id']}{suffix}",
                          params={"case_id": case["id"]}).status_code == 404
    start_search(client, case)
    fresh = wait_search(app, client, case["id"])
    assert fresh["status"] == "ready" and fresh["id"] != original["id"] and not fresh["stale"]
    result = fresh["results"][0]
    assert {s["source_id"] for s in result["supports"]} == {common["id"]}
    assert any(item["description"] == PENDING for item in result["missing"])
    assert QUOTE not in json.dumps(fresh, ensure_ascii=False)
    assert app.state.library.run_scope_revoked(case["id"], original["id"])
    assert not app.state.library.run_scope_revoked(case["id"], fresh["id"])
    assert app.state.verifications.get(record.json()["id"])["passage"]["quote"] == QUOTE


def test_legacy_run_uses_immutable_snapshot_in_compact_and_full_reads(env):
    app, client, case, restricted, _, path, _ = env
    start_search(client, case)
    run = wait_search(app, client, case["id"])
    with app.state.library.connect() as db:
        db.execute("UPDATE source_runs SET body=json_remove(body,'$.allowed_collection_ids') "
                   "WHERE id=?", (run["id"],))
        db.execute("DELETE FROM source_run_progress WHERE run_id=?", (run["id"],))
    assert client.get(path + "/sources", params={"compact": True}).json()["status"] == "ready"
    assert client.put(path + "/source-collections", json={"collection_ids": []}).status_code == 200
    assert_hidden(client, path, restricted)
    # Unread catalog entries could affect an audit without supplying indexed text.
    with app.state.library.connect() as db:
        db.execute("UPDATE source_runs SET body=json_set(body,'$.source_snapshot',json('[]')) "
                   "WHERE id=?", (run["id"],))
    assert_hidden(client, path, restricted)


def test_revoke_between_retrieval_and_reader_hides_partial_results(env, monkeypatch):
    app, client, case, restricted, _, path, reader = env
    identification = case["identification"]
    identification["requests"].append({**identification["requests"][0], "id": "P2"})
    case = app.state.store.update(case["id"], identification=identification, request_count=2)
    retrieve = source_service.retrieve
    entered, release = threading.Event(), threading.Event()

    def blocked_retrieve(request, chunks, **kwargs):
        candidates = retrieve(request, chunks, **kwargs)
        if request["id"] == "P2":
            entered.set()
            assert release.wait(10)
        return candidates

    monkeypatch.setattr(source_service, "retrieve", blocked_retrieve)
    try:
        start_search(client, case)
        assert entered.wait(10)
        partial = client.get(path + "/sources", params={"compact": True}).json()
        assert partial["status"] == "running" and partial["results"][0]["summary"] == QUOTE
        assert client.put(path + "/source-collections",
                          json={"collection_ids": []}).status_code == 200
        assert_hidden(client, path, restricted, status="running")
    finally:
        release.set()
    wait_search(app, client, case["id"])
    assert_hidden(client, path, restricted)
    assert reader.calls == ["P1"]


def test_catalog_audit_uses_permissions_captured_before_queuing(env, monkeypatch):
    app, client, case, _, _, path, _ = env
    other = "coleccion-agregada-despues"
    library = app.state.library
    library.save_collection({"id": other, "title": "Otra colección ficticia"})
    later = library.add("anexo.txt", b"Acta de practicas incorporada posteriormente.",
                        title="Acta posterior", category="historical_attachment",
                        origin="Ficticio", collection_id=other)
    audit = source_service.catalog_audit
    audited_ids = set()

    def capture(request, finding, catalog, **kwargs):
        audited_ids.update(source["id"] for source in catalog)
        return audit(request, finding, catalog, **kwargs)

    monkeypatch.setattr(source_service, "catalog_audit", capture)
    release = threading.Event()
    app.state.sources.pool.submit(release.wait, 10)
    try:
        start_search(client, case)
        assert client.put(path + "/source-collections",
                          json={"collection_ids": [COLLECTION, other]}).status_code == 200
    finally:
        release.set()
    expanded = wait_search(app, client, case["id"])
    assert expanded["status"] == "stale" and expanded["results"]
    assert audited_ids and later["id"] not in audited_ids
    assert client.put(path + "/source-collections",
                      json={"collection_ids": [COLLECTION]}).status_code == 200
    original_scope = client.get(path + "/sources").json()
    assert original_scope["status"] == "ready" and later["id"] not in json.dumps(original_scope)


def test_initial_review_hides_legacy_report_and_history_but_keeps_classification(env):
    app, client, case, restricted, _, path, _ = env
    intake = app.state.initial_review
    citation = {"source_id": restricted["id"], "title": TITLE, "quote": QUOTE}
    report = {"document": {"checks": [{"summary": QUOTE, "sources": [citation]}]},
              "requests": [], "warnings": [QUOTE]}
    row = intake.save(intake.saved(case["id"]), status="approved", policy_version=1,
                      fingerprint="huella-antigua", report=report, decisions=[{"reason": QUOTE}],
                      scope={"linked_collections": [COLLECTION], "catalog": [restricted]},
                      consulted_sources=[citation], selection_basis={"report": report})
    # An earlier format has just the cited source versions.
    intake.save(row, scope={}, consulted_sources=[])
    prefix = path + "/initial-review"
    assert client.get(prefix).json()["report"] == report
    assert client.put(path + "/source-collections", json={"collection_ids": []}).status_code == 200
    for suffix in ("", "?compact=true", "/history"):
        response = client.get(prefix + suffix)
        assert response.status_code == 200
        data = response.json()
        entries = data["events"] if suffix == "/history" else [data]
        assert all(item["scope_revoked"] and item["stale"] and item["report"] is None
                   for item in entries)
        for value in (QUOTE, TITLE, COLLECTION, restricted["id"], restricted["sha256"]):
            assert value not in json.dumps(data, ensure_ascii=False)
    assert intake.saved(case["id"])["report"] == report
    classification = {"document": {"checks": []}, "requests": [], "warnings": []}
    current_scope = "petition_types_v1"
    intake.save(intake.saved(case["id"]), analysis_scope=current_scope,
                scope={"mode": current_scope, "linked_collections": [], "catalog": []},
                fingerprint=intake.fingerprint(case["id"], scope=current_scope), policy_version=2,
                consulted_sources=[], selection_basis=None, decisions=None, report=classification)
    current = client.get(prefix).json()
    assert current["report"] == classification and not current["stale"]
    history = client.get(prefix + "/history").json()["events"]
    assert [event["report"] for event in history] == [None, None, classification]
