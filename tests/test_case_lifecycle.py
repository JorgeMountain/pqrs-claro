"""Trash is reversible, versioned and never races running work or erases sources."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_app import analyze, upload
from test_office_service_api import (  # noqa: F401
    approved_case,
    generate,
    inputs,
    office_app,
    wait_office,
)
from test_unified_app import pdf_bytes, unified  # noqa: F401

from pqrs_claro.storage import CaseStore, Conflict


def action(case, revision=0, confirmed=True):
    return dict(version=case['version'], lifecycle_revision=revision, confirmed=confirmed)


def test_delete_restore_preserves_original_and_identification(unified, pdf_bytes):  # noqa: F811
    app, client, _, settings = unified
    case = analyze(client, upload(client, pdf_bytes))
    path = '/api/cases/' + case['id']
    original = client.get(path).json()
    listing = client.get('/api/cases').json()[0]
    assert listing['subject'] == 'Copia del acta'
    assert listing['origin_kind'] == 'pdf' and not listing['processing']
    assert client.request('DELETE', path, json=action(case)).status_code == 200
    assert client.get('/api/cases').json() == []
    trashed = client.get('/api/cases?deleted=true').json()[0]
    assert trashed['deleted_at'] and trashed['lifecycle_revision'] == 1
    for tail in ('', '/original', '/pages/1.png'):
        assert client.get(path + tail).status_code == 409
    with pytest.raises(Conflict):
        app.state.store.update(case['id'], status='uploaded')
    assert client.post(path + '/analyze').status_code == 409
    reopened = CaseStore(settings.data_dir)
    assert reopened.list() == [] and len(reopened.list(deleted=True)) == 1
    response = client.post(path + '/restore', json=action(case, 1))
    assert response.status_code == 200, response.text
    assert client.get(path).json() == original
    assert client.get(path + '/original').content == pdf_bytes
    assert client.get('/api/cases?deleted=true').json() == []
    with reopened.connect() as conn:
        events = conn.execute(
            'SELECT action FROM case_lifecycle_events ORDER BY revision').fetchall()
        assert events == [('deleted',), ('restored',)]


def test_confirmation_versions_origin_and_simultaneous_delete(unified, pdf_bytes):  # noqa: F811
    _, client, _, _ = unified
    case = upload(client, pdf_bytes)
    path = '/api/cases/' + case['id']
    assert client.request('DELETE', path, json=action(case, confirmed=False)).status_code == 422
    assert client.request('DELETE', path, json=action(case, confirmed='true')).status_code == 422
    assert client.request('DELETE', path, json={**action(case), 'version': 42}).status_code == 409
    assert client.request('DELETE', path, json=action(case),
                          headers={'origin': 'https://outside.example'}).status_code == 403
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.request(
            'DELETE', path, json=action(case)).status_code, range(2)))
    assert sorted(statuses) == [200, 409]
    assert client.post(path + '/restore', json=action(case)).status_code == 409
    assert client.post(path + '/restore', json=action(case, 1)).status_code == 200
    assert client.request('DELETE', path, json=action(case)).status_code == 409
    assert client.request('DELETE', path, json=action(case, 2)).status_code == 200


@pytest.mark.parametrize('service_name,tuple_key', [
    ('service', False), ('preparation', False), ('sources', False), ('drafts', False),
    ('reviews', True), ('proposals', True), ('offices', False),
])
def test_running_work_blocks_delete(unified, pdf_bytes, service_name, tuple_key):  # noqa: F811
    app, client, _, _ = unified
    case = upload(client, pdf_bytes)
    service = getattr(app.state, service_name)
    key = (case['id'], 'P1') if tuple_key else case['id']
    with service.lock:
        if isinstance(service.active, dict):
            service.active[key] = 'job'
        else:
            service.active.add(key)
    try:
        assert client.get('/api/cases').json()[0]['processing']
        result = client.request('DELETE', '/api/cases/' + case['id'], json=action(case))
        assert result.status_code == 409 and 'procesándose' in result.json()['detail']
        assert not client.get('/api/cases?deleted=true').json()
    finally:
        with service.lock:
            if isinstance(service.active, dict):
                del service.active[key]
            else:
                service.active.discard(key)


@pytest.mark.parametrize('office_app', ['recorrido'], indirect=True)
def test_restore_keeps_approvals_sources_and_export_bytes(office_app):  # noqa: F811
    app, client, _, _ = office_app
    case, source = approved_case(app, client)
    prefix = '/api/cases/' + case['id']
    run = wait_office(app, client, case, generate(client, case, inputs(client, case)))
    assert run['status'] == 'ready'
    rows = client.get(prefix + '/review').json()
    download = prefix + '/office/runs/' + run['id'] + '/files/pdf'
    original = client.get(download).content
    assert client.request('DELETE', prefix, json=action(case)).status_code == 200
    assert client.get(download).status_code == 409
    assert app.state.library.get(source['id'])
    assert client.post(prefix + '/restore', json=action(case, 1)).status_code == 200
    assert client.get(prefix + '/review').json() == rows
    assert client.get(download).content == original
