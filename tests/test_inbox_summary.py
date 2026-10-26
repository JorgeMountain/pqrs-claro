# ruff: noqa: F401, F811
import json

import pytest
from test_initial_review import analyze, fiaga, pdf_bytes


def test_pool_exposes_saved_analysis_phase_without_approving_it(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    case, review = analyze(fiaga, pdf_bytes)
    row = next(c for c in client.get('/api/cases').json() if c['id'] == case['id'])
    assert row['initial_review_status'] == review['status'] == 'needs_review'
    assert row['processing'] is False
    assert client.get(f"/api/cases/{case['id']}/initial-review").json()['can_prepare'] is False
    before = engine.calls
    client.get('/api/cases')
    assert engine.calls == before  # Listing and progress never trigger an analysis.


@pytest.mark.parametrize('artifact,stage', [
    ('draft_runs', 2), ('review_requests', 2), ('office_workspace', 3), ('office_runs', 3),
])
def test_legacy_work_survives_listing_without_intake_or_preparation(
    fiaga, pdf_bytes, artifact, stage,
):
    app, client, engine, assessor = fiaga
    store = app.state.store
    case = store.create('anterior.pdf', pdf_bytes)
    case = store.update(case['id'], status='confirmed', request_count=1, identification={
        'subject': 'Anterior', 'requests': [{'id': 'P1', 'label': '1', 'title': 'Anterior',
            'description': 'Texto conservado', 'source_refs': []}],
    })
    cid = case['id']
    payload = json.dumps({'status': 'stale', 'paragraphs': [{'text': 'Respuesta conservada'}]})
    target = (app.state.drafts.store if artifact == 'draft_runs' else
              app.state.offices.store if artifact == 'office_runs' else app.state.reviews.store)
    with target.connect() as conn:
        if artifact == 'review_requests':
            conn.execute('INSERT INTO review_requests VALUES (?,?,?,?)', (cid, 'P1', 1, payload))
        elif artifact == 'office_workspace':
            from pqrs_claro.office_workspace import _table
            _table(conn)
            conn.execute('INSERT INTO office_workspace VALUES (?,?,?)', (cid, 1, payload))
        else:
            conn.execute(f'INSERT INTO {artifact} VALUES (?,?,?)', ('run', cid, payload))
    for _ in range(2):
        row = next(r for r in client.get('/api/cases').json() if r['id'] == cid)
        detail = client.get(f'/api/cases/{cid}').json()
        assert row['saved_stage'] == detail['saved_stage'] == stage
        assert row['initial_review_status'] == 'idle'
        assert row['preparation']['status'] == 'idle'
        assert detail['identification'] == case['identification']
    assert store.get(cid) == case
    with target.connect() as conn:
        saved = conn.execute(f'SELECT body FROM {artifact} WHERE case_id=?', (cid,)).fetchone()
        assert saved[0] == payload
    assert client.get(f'/api/cases/{cid}/original').content == pdf_bytes
    assert client.get(f'/api/cases/{cid}/initial-review').json()['can_prepare'] is False
    response = client.post(f'/api/cases/{cid}/preparation', json={'version': case['version']})
    assert response.status_code == 409
    assert engine.calls == 0 and not assessor.calls


def test_new_cases_do_not_inherit_other_cases_saved_work(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    first = app.state.store.create('anterior.pdf', pdf_bytes)
    second = app.state.store.create('nuevo.pdf', pdf_bytes)
    app.state.drafts.store.save({'id': 'old', 'case_id': first['id'], 'status': 'partial'})
    rows = {r['id']: r for r in client.get('/api/cases').json()}
    assert rows[first['id']]['saved_stage'] == 2
    assert rows[second['id']]['saved_stage'] == 0
    assert rows[second['id']]['status'] == 'uploaded'
    assert engine.calls == 0


def _generated_office(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case = app.state.store.create('cualquier-tema.pdf', pdf_bytes)
    case = app.state.store.update(case['id'], status='confirmed', identification={
        'requests': [{'id': 'P1', 'label': '1', 'title': 'Consulta',
                      'description': 'Pregunta de prueba', 'source_refs': []}],
    })
    cid = case['id']
    row = {'case_id': cid, 'request_id': 'P1', 'status': 'approved', 'stale': False,
           'approval': {'id': 'approval'}, 'updated_at': '2026-10-14T10:00:00+00:00'}
    with app.state.reviews.store.connect() as conn:
        conn.execute('INSERT INTO review_requests VALUES (?,?,?,?)',
                     (cid, 'P1', 1, json.dumps(row)))
        conn.execute('INSERT INTO review_approvals VALUES (?,?,?,?)',
                     ('approval', cid, 'P1', json.dumps({'case_version': case['version']})))
        from pqrs_claro.office_workspace import _table
        _table(conn)
        conn.execute('INSERT INTO office_workspace VALUES (?,?,?)',
                     (cid, 1, json.dumps({'updated_at': '2026-10-14T09:59:00+00:00'})))
    run = {'id': 'export', 'case_id': cid, 'status': 'ready', 'stale': False,
           'created_at': '2026-10-14T10:01:00+00:00'}
    app.state.offices.store.create(run)
    return case, row, run


def test_generated_office_progress_is_durable_read_only_and_compact(fiaga, pdf_bytes, monkeypatch):
    app, client, engine, assessor = fiaga
    case, row, run = _generated_office(fiaga, pdf_bytes)
    def unexpected(*args, **kwargs):
        pytest.fail('La bandeja no debe recalcular fuentes, respuestas ni oficios')
    monkeypatch.setattr(app.state.offices, 'get', unexpected)
    monkeypatch.setattr(app.state.reviews, 'get', unexpected)
    for _ in range(2):
        summary = next(r for r in client.get('/api/cases').json() if r['id'] == case['id'])
        detail = client.get(f"/api/cases/{case['id']}").json()
        assert summary['saved_stage'] == detail['saved_stage'] == 3
        assert summary['office_progress'] == detail['office_progress']
        assert summary['office_progress'] == {'id': 'export', 'status': 'ready'}
        assert summary['management']['state'] != 'closed'
    assert app.state.offices.store.get(case['id'], 'export') == run
    assert app.state.reviews.store.get(case['id'], 'P1') == row
    assert app.state.store.get(case['id']) == case
    assert engine.calls == 0 and not assessor.calls


@pytest.mark.parametrize('change', ['response', 'metadata', 'case_version', 'missing_response'])
def test_saved_export_does_not_complete_changed_content(fiaga, pdf_bytes, change):
    app, client, _, _ = fiaga
    case, row, run = _generated_office(fiaga, pdf_bytes)
    cid = case['id']
    with app.state.reviews.store.connect() as conn:
        if change == 'response':
            row.update(status='editing', updated_at='2026-10-14T11:00:00+00:00')
            conn.execute('UPDATE review_requests SET body=? WHERE case_id=?',
                         (json.dumps(row), cid))
        elif change == 'metadata':
            conn.execute('UPDATE office_workspace SET body=? WHERE case_id=?',
                         (json.dumps({'updated_at': '2026-10-14T11:00:00+00:00'}), cid))
        elif change == 'missing_response':
            conn.execute('DELETE FROM review_requests WHERE case_id=?', (cid,))
    if change == 'case_version':
        app.state.store.update(cid, version=case['version'] + 1)
    summary = next(r for r in client.get('/api/cases').json() if r['id'] == cid)
    assert summary['saved_stage'] == 3
    assert summary['office_progress'] == {'id': 'export', 'status': 'stale'}
    assert app.state.offices.store.get(cid, 'export') == run  # Older output remains intact.


def test_office_progress_reports_latest_attempt_and_does_not_leak_between_cases(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case, _, run = _generated_office(fiaga, pdf_bytes)
    other = app.state.store.create('otro.pdf', pdf_bytes)
    app.state.offices.store.create({**run, 'id': 'retry', 'status': 'failed'})
    rows = {r['id']: r for r in client.get('/api/cases').json()}
    assert rows[case['id']]['office_progress'] == {'id': 'retry', 'status': 'failed'}
    assert rows[other['id']]['office_progress'] is None
