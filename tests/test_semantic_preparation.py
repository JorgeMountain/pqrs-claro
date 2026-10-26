import json
import time

import pytest
from test_source_semantic import CountingModel

from pqrs_claro.semantic_preparation import SemanticPreparation
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.source_preparation import worker_lock


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
