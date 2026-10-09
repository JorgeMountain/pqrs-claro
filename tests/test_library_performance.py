"""Scope is applied before Python materializes large institutional collections."""

import json
from contextlib import contextmanager

import pytest

from pqrs_claro import source_library
from pqrs_claro.source_library import SourceLibrary


def seed(library, key, **changes):
    body = dict(id=key, document_id=key, version=1, case_id=None,
                category="institutional_norm", validity="current", collection_id=None,
                extraction_status="ready")
    body.update(changes)
    with library.connect() as conn:
        conn.execute("INSERT INTO sources VALUES (?,?,?,?,?)",
                     (key, body["document_id"], body["version"], json.dumps(body), "[]"))
    return body


@pytest.mark.parametrize("case_id", ["one", "two", "unlinked"])
@pytest.mark.parametrize("evidence_only", [False, True])
def test_sql_scope_matches_previous_catalog_and_evidence_rules(tmp_path, case_id, evidence_only):
    library = SourceLibrary(tmp_path, None)
    library.save_collection({"id": "selected"})
    library.save_collection({"id": "other"})
    library.link_collections("one", ["selected"])
    library.link_collections("two", ["other"])
    seed(library, "global")
    seed(library, "local", case_id="one")
    seed(library, "linked", collection_id="selected")
    seed(library, "excluded", collection_id="other")
    seed(library, "old", document_id="versioned")
    seed(library, "new", document_id="versioned", version=2, collection_id="other")
    seed(library, "obsolete", validity="superseded")
    seed(library, "previous", category="previous_response")
    seed(library, "archive", category="archive_only")
    seed(library, "pending", extraction_status="pending")
    seed(library, "partial", extraction_status="partial")
    seed(library, "unknown", extraction_status=None)
    linked = set(library.linked_collections(case_id))
    expected = [s for s in library.list(case_id) if s["is_latest"]
                and s["validity"] != "superseded" and s["category"] != "previous_response"
                and (not s.get("collection_id") or s["collection_id"] in linked)
                and (not evidence_only or (s["category"] != "archive_only"
                     and s.get("extraction_status", "ready") in {"ready", "partial"}))]
    assert library.scoped(case_id, evidence_only=evidence_only) == expected


def test_scope_avoids_decoding_unselected_metadata_and_pages(tmp_path, monkeypatch):
    library = SourceLibrary(tmp_path, None)
    for number in range(60):
        seed(library, str(number), collection_id="unselected", notes="x" * 3000)
    source = library.add("selected.txt", b"Fictional source with exact original text.",
                         title="Selected", category="institutional_norm", origin="Test")
    statements, decoded = [], []
    connect = library.connect
    loads = json.loads

    @contextmanager
    def traced():
        with connect() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    def decode(value, *args, **kwargs):
        decoded.append(len(value))
        return loads(value, *args, **kwargs)

    monkeypatch.setattr(library, "connect", traced)
    monkeypatch.setattr(source_library.json, "loads", decode)
    sources, chunks = library.snapshot("one")
    assert [s["id"] for s in sources] == [source["id"]]
    assert chunks[0]["quote"] == "Fictional source with exact original text."
    assert len(decoded) == 2  # Only selected metadata and selected pages.
    page_queries = [q for q in statements if "SELECT id,pages" in q]
    assert len(page_queries) == 1 and "WHERE id IN" in page_queries[0]
    with connect() as conn:
        plan = conn.execute("EXPLAIN QUERY PLAN " + next(
            q for q in statements if q.startswith("SELECT s.body")
        )).fetchall()
    assert any("sources_collection_scope" in row[3] for row in plan)


def test_scope_observes_external_updates_and_unlink_immediately(tmp_path):
    library = SourceLibrary(tmp_path, None)
    library.save_collection({"id": "selected"})
    library.link_collections("one", ["selected"])
    body = seed(library, "source", collection_id="selected", extraction_status="pending")
    assert not library.eligible("one")
    body["extraction_status"] = "ready"
    with library.connect() as conn:
        conn.execute("UPDATE sources SET body=? WHERE id=?", (json.dumps(body), body["id"]))
    assert library.eligible("one")[0]["id"] == body["id"]
    library.link_collections("one", [])
    assert not library.eligible("one")
