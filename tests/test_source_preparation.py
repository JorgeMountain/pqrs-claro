import json
import time

import pytest

from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.source_preparation import SourcePreparation, worker_lock
from pqrs_claro.source_retrieval import RetrievalIndex, retrieve, terms_key


@pytest.fixture
def library(tmp_path):
    return SourceLibrary(tmp_path, None)


def add(library, text="El examen será el 20 de octubre. Matrícula docente 2027.", **kwargs):
    return library.add("norma.txt", text.encode(), title="Calendario académico",
                       category="institutional_norm", origin="Prueba local ficticia", **kwargs)


def drain(library):
    worker = SourcePreparation(library)
    while worker.process_one():
        pass
    return worker


def row(library, source):
    with library.connect() as connection:
        connection.row_factory = __import__("sqlite3").Row
        return dict(connection.execute("SELECT * FROM source_index_jobs WHERE source_id=?",
                                       (source["id"],)).fetchone())


def test_prepared_index_preserves_exact_ranking_scores_and_passages(library):
    add(library)
    add(library, "El docente presenta el informe.\nLa evaluación usa dos pruebas.\n" * 80)
    _, chunks = library.snapshot("case")
    queries = [dict(title=q, description=q, case_id="case") for q in (
        "fecha del examen 2027", "informe del docente", "cuántas pruebas evaluación")]
    expected = [retrieve(q, chunks) for q in queries]
    worker = drain(library)
    prepared = library.prepared_terms(chunks)
    index = RetrievalIndex(chunks, prepared_terms=prepared)
    assert [retrieve(q, chunks, index=index) for q in queries] == expected
    assert index.diagnostics == {"prepared_hits": len(chunks), "computed": 0}
    assert worker.status()["ready"] == 2
    assert worker.status()["prepared_chunks"] == len(chunks)
    # The cache never adds metadata to passages sent to the model.
    assert all("terms" not in c and "payload" not in c for c in chunks)


def test_direct_ocr_and_title_updates_invalidate_atomically(library):
    source = add(library)
    drain(library)
    old_revision = row(library, source)["revision"]
    with library.connect() as connection:
        body, pages = connection.execute("SELECT body,pages FROM sources WHERE id=?",
                                         (source["id"],)).fetchone()
        body, pages = json.loads(body), json.loads(pages)
        body["title"] = "Inscripción nueva"
        pages[0]["text"] = "El examen será en noviembre."
        connection.execute("UPDATE sources SET body=?,pages=? WHERE id=?",
                           (json.dumps(body), json.dumps(pages), source["id"]))
    assert row(library, source)["revision"] == old_revision + 1
    assert row(library, source)["status"] == "queued"
    _, chunks = library.snapshot("case")
    assert library.prepared_terms(chunks) == {}
    before = retrieve(dict(title="noviembre examen"), chunks)
    drain(library)
    index = RetrievalIndex(chunks, prepared_terms=library.prepared_terms(chunks))
    assert retrieve(dict(title="noviembre examen"), chunks, index=index) == before
    assert "noviembre" in library.prepared_terms(chunks)[terms_key(chunks[0])]


@pytest.mark.parametrize("change", ["update", "delete"])
def test_result_cannot_overwrite_newer_or_resurrect_deleted(library, monkeypatch, change):
    from pqrs_claro import source_library

    source = add(library)
    original = source_library.make_chunks

    def concurrent_change(body, pages):
        result = original(body, pages)
        with library.connect() as connection:
            if change == "delete":
                connection.execute("DELETE FROM sources WHERE id=?", (source["id"],))
            else:
                pages[0]["text"] = "Texto posterior distinto"
                connection.execute("UPDATE sources SET pages=? WHERE id=?",
                                   (json.dumps(pages), source["id"]))
        return result

    monkeypatch.setattr(source_library, "make_chunks", concurrent_change)
    assert SourcePreparation(library).process_one()
    with library.connect() as connection:
        jobs = connection.execute("SELECT status,payload FROM source_index_jobs").fetchall()
    assert jobs == ([] if change == "delete" else [("queued", None)])


def test_scope_unlink_and_content_mutation_cannot_reuse_unauthorized_or_old_counts(library):
    public = add(library)
    library.save_collection({"id": "private"})
    add(library, "secretoextranjero matrícula", collection_id="private")
    drain(library)
    _, chunks = library.snapshot("case")
    assert {c["source_id"] for c in chunks} == {public["id"]}
    prepared = library.prepared_terms(chunks)
    assert not any("secretoextranjero" in c for c in prepared.values())
    chunks[0]["quote"] = "contenido cambiado pendiente"
    index = RetrievalIndex(chunks, prepared_terms=prepared)
    assert index.statistics(chunks) == RetrievalIndex(chunks).statistics(chunks)
    assert index.diagnostics["computed"] == 1


def test_corrupted_cache_falls_back_without_changing_results(library):
    source = add(library)
    drain(library)
    with library.connect() as connection:
        connection.execute("UPDATE source_index_jobs SET payload='{}' WHERE source_id=?",
                           (source["id"],))
    _, chunks = library.snapshot("case")
    assert library.prepared_terms(chunks) == {}
    query = dict(title="fecha examen")
    assert retrieve(query, chunks, index=RetrievalIndex(
        chunks, prepared_terms=library.prepared_terms(chunks))) == retrieve(query, chunks)


def test_algorithm_upgrade_queues_old_index_without_changing_original(library):
    source = add(library)
    drain(library)
    before = library.get(source["id"])
    with library.connect() as connection:
        connection.execute("UPDATE source_index_jobs SET algorithm='old-version'")
    reopened = SourceLibrary(library.db.parent, None)
    assert row(reopened, source)["status"] == "queued"
    assert row(reopened, source)["payload"] is None
    assert reopened.get(source["id"]) == before
    assert drain(reopened).status()["ready"] == 1


def test_new_upload_is_prepared_before_historical_backfill(library):
    old = add(library)
    with library.connect() as connection:
        connection.execute("UPDATE source_index_jobs SET priority=0")
    new = add(library)
    worker = SourcePreparation(library)
    assert worker.process_one()
    assert row(library, new)["status"] == "ready"
    assert row(library, old)["status"] == "queued"


def test_unreadable_is_not_ready_and_does_not_run_ocr(library):
    source = add(library)
    with library.connect() as connection:
        connection.execute("UPDATE sources SET pages='[]' WHERE id=?", (source["id"],))
    worker = drain(library)
    assert worker.status()["unreadable"] == 1
    assert worker.status()["ready"] == 0


def test_interruption_and_reopen_resume_pending_work_without_changing_source(library):
    source = add(library)
    worker = SourcePreparation(library)
    worker.stop_event.set()
    worker.process_one()
    assert row(library, source)["status"] == "queued"
    before = library.get(source["id"])
    with library.connect() as connection:
        connection.execute("UPDATE source_index_jobs SET status='preparing',token='interrupted'")
    restarted = SourcePreparation(library)
    restarted.start()
    try:
        deadline = time.monotonic() + 5
        while restarted.status()["ready"] != 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert restarted.status()["ready"] == 1
    finally:
        restarted.close()
    assert library.get(source["id"]) == before
    reopened = SourceLibrary(library.db.parent, None)
    assert SourcePreparation(reopened).status()["ready"] == 1


def test_os_lock_prevents_two_workers_recovering_each_others_jobs(tmp_path):
    path = tmp_path / "index.lock"
    with worker_lock(path) as acquired:
        assert acquired
        with worker_lock(path) as second:
            assert not second
    with worker_lock(path) as recovered:
        assert recovered


def test_failed_document_does_not_block_others_or_retry_forever(library, monkeypatch):
    import pqrs_claro.source_preparation as module

    add(library, "ERROR FICTICIO")
    add(library)
    original = module.tokenize

    def broken(text):
        if "ERROR FICTICIO" in text:
            raise ValueError("Fallo de prueba")
        return original(text)

    monkeypatch.setattr(module, "tokenize", broken)
    worker = drain(library)
    assert worker.status()["error"] == 1
    assert worker.status()["ready"] == 1
    assert not worker.process_one()


def test_trigger_invalidation_rolls_back_with_the_source_transaction(library):
    source = add(library)
    drain(library)
    revision = row(library, source)["revision"]
    with pytest.raises(RuntimeError), library.connect() as connection:
        connection.execute("UPDATE sources SET pages='[]' WHERE id=?", (source["id"],))
        raise RuntimeError("rollback")
    assert row(library, source)["revision"] == revision
    assert row(library, source)["status"] == "ready"
