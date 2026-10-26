# ruff: noqa: F811
"""Measure request evaluations with the real API and a deterministic fake engine."""
import copy
from dataclasses import replace

import pytest
from test_initial_review import decision, fiaga, wait_intake  # noqa: F401
from test_intake_selection_reuse import edit, setup_case
from test_source_service_api import pdf_bytes, upload_source  # noqa: F401


@pytest.mark.parametrize('field,value,expected', [
    ('description', 'Solicito copia del reglamento actualizado.', 1),
    ('title', 'Copia del reglamento', 1),
    ('label', 'Primera petición', 0),
])
def test_only_changed_petition_is_assessed(fiaga, pdf_bytes, field, value, expected):
    app, client, engine, case, original = setup_case(fiaga, pdf_bytes)
    assert len(engine.payload['identification']['requests']) == 2
    calls = engine.calls
    changed = copy.deepcopy(case['identification'])
    changed['requests'][0][field] = value
    case = edit(client, case, changed)
    row = wait_intake(app, client, case)
    assert row['status'] == 'needs_review' and not row['stale']
    assert not row['can_prepare'] and row['decisions'] is None
    assert engine.calls == calls + expected
    if expected:
        assert [r['id'] for r in engine.payload['identification']['requests']] == ['P1']
    assert row['report']['requests'][1] == original['report']['requests'][1]
    assert row['timings']['evaluated_requests'] == expected
    assert row['timings']['reused_requests'] == 2 - expected
    assert row['timings']['total_seconds'] >= 0
    assert client.put(f"/api/cases/{case['id']}/initial-review/decision",
                      json=decision(original)).status_code == 409


def start(client, case, row, mode='incremental'):
    result = client.post(f"/api/cases/{case['id']}/initial-review/analyze", json={
        'version': case['version'], 'revision': row['revision'], 'mode': mode})
    assert result.status_code == 202, result.text


@pytest.mark.parametrize('change', ['sources', 'model'])
def test_global_dependency_invalidates_all(fiaga, pdf_bytes, change):
    app, client, engine, case, row = setup_case(fiaga, pdf_bytes)
    calls, revision = engine.calls, row['revision']
    if change == 'sources':
        upload_source(client)
    else:
        service = app.state.initial_review
        service.settings = replace(service.settings, model='another-fake')
    start(client, case, row)
    row = wait_intake(app, client, case)
    if change == 'sources':
        assert engine.calls == calls and row['revision'] == revision
        assert not row['stale']
        return
    assert engine.calls == calls + 1
    assert not row['stale'] and row['timings']['evaluated_requests'] == 2
    assert len(engine.payload['identification']['requests']) == 2


def test_error_retry_keeps_unaffected_result(fiaga, pdf_bytes):
    app, client, engine, case, original = setup_case(fiaga, pdf_bytes)
    assess = engine.assess
    attempts = []

    def fail(payload):
        attempts.append([r['id'] for r in payload['identification']['requests']])
        raise ValueError('Simulated failure')

    engine.assess = fail
    changed = copy.deepcopy(case['identification'])
    changed['requests'][0]['description'] = 'Solicito copia actualizada.'
    case = edit(client, case, changed)
    failed = wait_intake(app, client, case)
    assert failed['status'] == 'error' and not failed['can_prepare']
    assert attempts == [['P1']]
    engine.assess = assess
    start(client, case, failed)
    row = wait_intake(app, client, case)
    assert [r['id'] for r in engine.payload['identification']['requests']] == ['P1']
    assert row['report']['requests'][1] == original['report']['requests'][1]
    assert not row['stale']


def test_full_is_explicit_and_incremental_noop_preserves_revision(fiaga, pdf_bytes):
    app, client, engine, case, original = setup_case(fiaga, pdf_bytes)
    calls = engine.calls
    start(client, case, original)
    row = wait_intake(app, client, case)
    assert engine.calls == calls and row['revision'] == original['revision']
    start(client, case, row, 'full')
    row = wait_intake(app, client, case)
    assert engine.calls == calls + 1 and row['timings']['evaluated_requests'] == 2


def test_parent_change_invalidates_descendant(fiaga, pdf_bytes):
    app, client, engine, case, _ = setup_case(fiaga, pdf_bytes)
    changed = copy.deepcopy(case['identification'])
    changed['requests'][1]['parent_id'] = 'P1'
    case = edit(client, case, changed)
    wait_intake(app, client, case)
    assert len(engine.payload['identification']['requests']) == 2
    changed['requests'][0]['description'] = 'Solicito aclarar todos los requisitos.'
    case = edit(client, case, changed)
    row = wait_intake(app, client, case)
    assert row['timings']['evaluated_requests'] == 2


def test_referenced_petition_change_invalidates_dependent(fiaga, pdf_bytes):
    app, client, engine, case, _ = setup_case(fiaga, pdf_bytes)
    changed = copy.deepcopy(case['identification'])
    changed['requests'][1]['description'] = 'Solicito copia de lo indicado en el punto primero.'
    case = edit(client, case, changed)
    wait_intake(app, client, case)
    changed['requests'][0]['description'] = 'Solicito requisitos de inscripción.'
    case = edit(client, case, changed)
    row = wait_intake(app, client, case)
    assert row['timings']['evaluated_requests'] == 2


def test_valid_legacy_report_upgrades_without_reassessing_others(fiaga, pdf_bytes):
    app, client, engine, case, _ = setup_case(fiaga, pdf_bytes)
    service = app.state.initial_review
    service.save(service.saved(case['id']), analysis_cache=None)
    changed = copy.deepcopy(case['identification'])
    changed['requests'][0]['title'] = 'Título corregido'
    case = edit(client, case, changed)
    row = wait_intake(app, client, case)
    assert row['timings']['evaluated_requests'] == 1
    assert [r['id'] for r in engine.payload['identification']['requests']] == ['P1']
