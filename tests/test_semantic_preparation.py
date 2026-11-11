import json
import sqlite3
import time

import pytest
from test_source_semantic import CountingModel

from pqrs_claro.semantic_preparation import SemanticPreparation
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.source_preparation import worker_lock
from pqrs_claro.source_semantic import MODEL_FILE, _model_path


def fixture(tmp_path, model=None):
    library = SourceLibrary(tmp_path, None)
    source = library.add('norma.txt', b'El docente presenta su solicitud de certificado.',
                         title='Certificados', category='institutional_norm', origin='Prueba')
    model = model or CountingModel()
    worker = SemanticPreparation(library, model_factory=lambda _: model)
    return library, source, model, worker


def test_scope_persistence_and_cache_reuse(tmp_path):
    library, source, model, worker = fixture(tmp_path)
    library.add('privado.txt', b'Este contenido no pertenece al alcance elegido.',
                title='No encolar', category='institutional_norm', origin='Prueba')
    worker.enqueue([source])
    restarted = SemanticPreparation(library, model_factory=lambda _: model)
    assert restarted.status()['documents'] == {'queued': 1}
    assert restarted.process_one()
    assert restarted.status()['documents'] == {'ready': 1}
    calls = len(model.calls)
    restarted.enqueue([source])
    assert not restarted.process_one()
    assert len(model.calls) == calls
    # A metadata-only revision should reuse text embeddings when unchanged.
    with library.connect() as conn:
        conn.execute('UPDATE sources SET body=body WHERE id=?', (source['id'],))
    restarted.enqueue([source])
    assert restarted.process_one()
    assert len(model.calls) == calls


@pytest.mark.parametrize('change', ['update', 'delete'])
def test_concurrent_source_change_does_not_promote_old_revision(tmp_path, change):
    library, source, _, worker = fixture(tmp_path)

    class MutatingModel(CountingModel):
        def embed(self, texts, batch_size=32):
            with library.connect() as conn:
                if change == 'delete':
                    conn.execute('DELETE FROM sources WHERE id=?', (source['id'],))
                else:
                    conn.execute('UPDATE sources SET body=body WHERE id=?', (source['id'],))
            yield from super().embed(texts, batch_size)

    worker.model_factory = lambda _: MutatingModel()
    worker.enqueue([source])
    assert worker.process_one()
    assert worker.status()['documents'] == {('queued' if change == 'update' else 'removed'): 1}


def test_stop_preserves_cache_and_resume(tmp_path):
    library, source, model, worker = fixture(tmp_path)
    worker.enqueue([source])
    worker.stop_event.set()
    assert worker.process_one()
    assert worker.status()['documents'] == {'queued': 1}
    assert not model.calls
    worker.stop_event.clear()
    assert worker.process_one()
    assert worker.status()['documents'] == {'ready': 1}


def test_second_worker_cannot_recover_active_job(tmp_path):
    _, source, _, worker = fixture(tmp_path)
    worker.enqueue([source])
    with worker.connect() as conn:
        conn.execute("UPDATE jobs SET status='preparing'")
    with worker_lock(worker.db.with_suffix('.lock')) as acquired:
        assert acquired
        worker.start()
        worker.thread.join(timeout=3)
        assert worker.status()['documents'] == {'preparing': 1}
    worker.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and worker.status()['documents'] != {'ready': 1}:
        time.sleep(.01)
    worker.close()
    assert worker.status()['documents'] == {'ready': 1}


def test_unreadable_source_does_not_become_prepared(tmp_path):
    library, source, model, worker = fixture(tmp_path)
    with library.connect() as conn:
        body = json.loads(conn.execute('SELECT body FROM sources WHERE id=?',
                                      (source['id'],)).fetchone()[0])
        body['extraction_status'] = 'error'
        conn.execute('UPDATE sources SET body=? WHERE id=?', (json.dumps(body), source['id']))
    worker.enqueue([source])
    worker.process_one()
    assert worker.status()['documents'] == {'unreadable': 1}
    assert not model.calls


def insert_source(conn, source_id, **changes):
    source = {"id": source_id, "document_id": source_id, "version": 1, "title": source_id,
              "category": "institutional_norm", "case_id": None, "validity": "current",
              **changes}
    conn.execute("INSERT INTO sources VALUES (?,?,?,?,?)",
                 (source_id, source["document_id"], source["version"], json.dumps(source),
                  json.dumps([{"number": 1, "text": "Texto de " + source_id,
                               "method": "native", "needs_review": False}])))


def test_discovery_respects_owner_collections_latest_revision_and_restart(tmp_path):
    library = SourceLibrary(tmp_path, None)
    model = CountingModel()
    worker = SemanticPreparation(library, model_factory=lambda _: model)
    with library.connect() as conn:
        insert_source(conn, "global")
        insert_source(conn, "own", category="case_evidence", case_id="A")
        insert_source(conn, "hist", category="historical_response", collection_id="X")
        insert_source(conn, "wrong", case_id="B", collection_id="X")
        insert_source(conn, "no-link", category="historical_petition")
        insert_source(conn, "arch", category="archive_only")
        insert_source(conn, "annulled", validity="superseded")
        insert_source(conn, "pending", extraction_status="error")
        insert_source(conn, "old", document_id="lineage")
        insert_source(conn, "new", document_id="lineage", version=2, extraction_status="partial")
        conn.execute("INSERT INTO case_source_collections VALUES ('A','X')")
    # A missing local model must not consume or seed the queue.
    offline = SemanticPreparation(library)
    offline.sync_catalog()
    assert not offline.status()["documents"] and not offline.process_one()
    onnx = _model_path(offline.cache_dir) / MODEL_FILE
    onnx.parent.mkdir(parents=True)
    onnx.touch()
    offline.sync_catalog()
    assert not offline.status()["documents"] and not offline.process_one()
    worker.sync_catalog()
    with worker.connect() as conn:
        queued = {r[0] for r in conn.execute("SELECT source_id FROM jobs")}
        assert queued == {"global", "own", "hist", "new"}

    worker.enqueue([{"id": "hist"}])
    with library.connect() as conn:
        conn.execute("DELETE FROM case_source_collections")
    # Revoked after discovery, before the job was claimed, without a catalog rescan.
    assert worker.process_one()
    assert not model.calls and worker.status()["documents"]["inactive"] == 1

    with library.connect() as conn:
        conn.execute("INSERT INTO case_source_collections VALUES ('B','X')")
        conn.execute("UPDATE sources SET body=json_set(body,'$.extraction_status','ready') "
                     "WHERE id='pending'")
    restarted = SemanticPreparation(library, model_factory=lambda _: model)
    restarted.sync_catalog()
    assert restarted.status()["documents"] == {"queued": 6}
    while restarted.process_one():
        pass
    assert restarted.status()["documents"] == {"ready": 6}

    with library.connect() as conn:
        conn.execute("UPDATE sources SET pages=? WHERE id='pending'",
                     (json.dumps([{"number": 1, "text": "OCR corregido.",
                                   "method": "ocr", "needs_review": True}]),))
        insert_source(conn, "newest", document_id="lineage", version=3)
    restarted.sync_catalog()
    assert restarted.status()["documents"] == {"inactive": 1, "queued": 2, "ready": 4}


def test_priority_avoids_starvation_and_unchanged_errors_do_not_retry(tmp_path):
    library = SourceLibrary(tmp_path, None)
    model = CountingModel()
    worker = SemanticPreparation(library, model_factory=lambda _: model)
    with library.connect() as conn:
        for i in range(7):
            insert_source(conn, str(i))
    worker.sync_catalog()
    explicit = [{"id": str(i)} for i in range(1, 7)]
    worker.enqueue(explicit)
    with worker.connect() as conn:
        conn.execute("UPDATE jobs SET status='error' WHERE source_id='1'")
    worker.enqueue(explicit)
    processed = []
    for _ in range(5):
        assert worker.process_one()
        with worker.connect() as conn:
            done = {r[0] for r in conn.execute("SELECT source_id FROM jobs WHERE status='ready'")}
        processed.append((done - set(processed)).pop())
    assert "0" not in processed[:4] and processed[4] == "0"
    with library.connect() as conn:
        insert_source(conn, "extra")
    worker.sync_catalog()
    assert worker.status()["documents"] == {"ready": 5, "queued": 2, "error": 1}


def test_reconcile_avoids_catalog_scan_when_unchanged(tmp_path, monkeypatch):
    library, _, _, worker = fixture(tmp_path)
    from contextlib import contextmanager
    reads = []
    original = library.connect

    @contextmanager
    def traced():
        with original() as conn:
            conn.set_trace_callback(reads.append)
            yield conn

    monkeypatch.setattr(library, "connect", traced)
    worker.sync_catalog()
    assert any("JOIN source_index_jobs" in sql for sql in reads)
    reads.clear()
    worker.sync_catalog()
    assert any("SELECT revision FROM source_catalog_revision" in sql for sql in reads)
    assert not any("FROM sources" in sql for sql in reads)


@pytest.mark.parametrize("extra_revision", [False, True])
def test_reimported_id_with_reset_revision_rebuilds(tmp_path, extra_revision):
    library, original, model, worker = fixture(tmp_path)
    sid = original["id"]
    if extra_revision:
        with library.connect() as conn:
            conn.execute("UPDATE sources SET body=body WHERE id=?", (sid,))
    worker.sync_catalog()
    assert worker.process_one()
    with library.connect() as conn:
        conn.execute("DELETE FROM sources WHERE id=?", (sid,))
        insert_source(conn, sid, title="Documento reemplazado")
    worker.sync_catalog()
    assert worker.status()["documents"] == {"queued": 1}
    assert worker.process_one()
    assert any("Documento reemplazado" in text for text in model.calls)


def test_old_discovery_cannot_mask_newer_interactive_ocr_job(tmp_path, monkeypatch):
    from contextlib import contextmanager

    library, source, model, worker = fixture(tmp_path)
    sid = source["id"]
    worker.sync_catalog()
    with library.connect() as conn:
        conn.execute("UPDATE sources SET body=json_set(body,'$.extraction_status','error') "
                     "WHERE id=?", (sid,))
    other = SemanticPreparation(library, model_factory=lambda _: model)
    original = worker.connect

    @contextmanager
    def interleaved():
        # The scan has already observed an unreadable source. OCR and an
        # interactive enqueue commit before it can update the job database.
        with library.connect() as conn:
            conn.execute("UPDATE sources SET body=json_set(body,'$.extraction_status','ready') "
                         "WHERE id=?", (sid,))
        other.enqueue([source])
        with original() as conn:
            yield conn

    with monkeypatch.context() as patch:
        patch.setattr(worker, "connect", interleaved)
        worker.sync_catalog()
    worker.sync_catalog()
    assert worker.status()["documents"] == {"queued": 1}
    assert worker.process_one() and worker.status()["documents"] == {"ready": 1}


def test_deleting_link_during_inference_stops_before_next_batch(tmp_path):
    library = SourceLibrary(tmp_path, None)
    with library.connect() as conn:
        insert_source(conn, "series", category="historical_response", collection_id="X")
        conn.execute("INSERT INTO case_source_collections VALUES ('A','X')")
        pages = [{"number": i, "text": f"Medición de la muestra {i}.",
                  "method": "native", "needs_review": False} for i in range(1, 21)]
        conn.execute("UPDATE sources SET pages=? WHERE id='series'", (json.dumps(pages),))

    class Revoke(CountingModel):
        def embed(self, texts, batch_size=32):
            with library.connect() as conn:
                conn.execute("DELETE FROM case_source_collections")
            yield from super().embed(texts, batch_size)

    model = Revoke()
    worker = SemanticPreparation(library, model_factory=lambda _: model)
    worker.sync_catalog()
    assert worker.process_one()
    assert 0 < len(model.calls) < len(pages)
    assert worker.status()["documents"] == {"inactive": 1}
    assert worker.status()["prepared_fragments"] == 0


def test_legacy_error_remains_terminal_and_ready_jobs_reuse_embeddings(tmp_path):
    library, source, model, worker = fixture(tmp_path)
    worker.sync_catalog()
    assert worker.process_one()
    old_calls = list(model.calls)
    with library.connect() as conn:
        insert_source(conn, "failed")
    with worker.connect() as conn:
        conn.execute("UPDATE jobs SET generation=0")
        conn.execute("INSERT INTO jobs(source_id,model_key,revision,status,error) "
                     "VALUES ('failed',?,1,'error','prior-error')", (worker.model_key,))
    restarted = SemanticPreparation(library, model_factory=lambda _: model)
    restarted.sync_catalog()
    assert restarted.status()["documents"] == {"error": 1, "queued": 1}
    assert restarted.process_one()
    assert not restarted.process_one() and model.calls == old_calls
    with worker.connect() as conn:
        error = conn.execute("SELECT error FROM jobs WHERE source_id='failed'").fetchone()
        assert error == ("prior-error",)


def test_transient_catalog_read_failure_requeues_job(tmp_path, monkeypatch):
    library, _, model, worker = fixture(tmp_path)
    worker.sync_catalog()

    def busy():
        raise sqlite3.OperationalError("database is busy")

    with monkeypatch.context() as patch:
        patch.setattr(library, "catalog_revision", busy)
        assert worker.process_one()
        assert not model.calls
        assert worker.status()["documents"] == {"queued": 1}
    assert worker.process_one() and worker.status()["documents"] == {"ready": 1}
