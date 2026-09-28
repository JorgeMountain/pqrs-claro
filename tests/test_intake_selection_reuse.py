# ruff: noqa: F811
"""Selection edits reuse paid results; genuine content changes still invalidate."""
import copy

from test_initial_review import fiaga, wait_intake  # noqa: F401
from test_source_service_api import make_case, pdf_bytes, upload_source  # noqa: F401


def setup_case(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    case = make_case(client, pdf_bytes, confirm=False)
    row = wait_intake(app, client, case)
    assert row['status'] == 'needs_review'
    return app, client, engine, case, row


def edit(client, case, identification):
    response = client.put(f"/api/cases/{case['id']}/identification", json={
        'version': case['version'], 'identification': identification,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_discard_and_undo_preserve_reports_without_model_calls(fiaga, pdf_bytes):
    app, client, engine, case, original = setup_case(fiaga, pdf_bytes)
    identification = copy.deepcopy(case['identification'])
    selected = copy.deepcopy(identification)
    selected['requests'].pop()
    calls = engine.calls
    case = edit(client, case, selected)
    row = wait_intake(app, client, case)
    assert engine.calls == calls
    assert row['status'] == 'needs_review' and not row['stale']
    assert not row['can_prepare']
    assert row['report']['document'] == original['report']['document']
    assert row['report']['requests'] == original['report']['requests'][:1]
    # Persisted cache, not a browser-only undo buffer.
    assert app.state.initial_review.saved(case['id'])['selection_basis']
    case = edit(client, case, identification)
    restored = wait_intake(app, client, case)
    assert restored['report'] == original['report']
    assert not restored['stale'] and not restored['can_prepare']
    assert engine.calls == calls


def test_changed_sources_do_not_become_valid_or_trigger_paid_call_on_discard(fiaga, pdf_bytes):
    app, client, engine, case, _ = setup_case(fiaga, pdf_bytes)
    upload_source(client)
    selected = copy.deepcopy(case['identification'])
    selected['requests'].pop()
    calls = engine.calls
    case = edit(client, case, selected)
    row = wait_intake(app, client, case)
    assert engine.calls == calls
    assert row['stale'] and not row['can_prepare']


def test_real_content_edit_still_reanalyzes_and_clears_selection_cache(fiaga, pdf_bytes):
    app, client, engine, case, _ = setup_case(fiaga, pdf_bytes)
    selected = copy.deepcopy(case['identification'])
    selected['requests'].pop()
    case = edit(client, case, selected)
    calls = engine.calls
    selected['requests'][0]['description'] = 'Solicito aclarar los requisitos y los plazos.'
    case = edit(client, case, selected)
    row = wait_intake(app, client, case)
    assert engine.calls == calls + 1
    assert not row.get('selection_basis')
    assert not row['stale']


def test_discard_reconnects_parent_and_undo_reuses_both_reports(fiaga, pdf_bytes):
    app, client, engine, case, _ = setup_case(fiaga, pdf_bytes)
    before = copy.deepcopy(case['identification'])
    before['requests'][1]['parent_id'] = before['requests'][0]['id']
    case = edit(client, case, before)
    original = wait_intake(app, client, case)
    calls = engine.calls
    selected = copy.deepcopy(before)
    selected['requests'] = selected['requests'][1:]
    selected['requests'][0]['parent_id'] = None
    case = edit(client, case, selected)
    row = wait_intake(app, client, case)
    assert not row['stale'] and engine.calls == calls
    case = edit(client, case, before)
    assert wait_intake(app, client, case)['report'] == original['report']
    assert engine.calls == calls


def test_stale_version_cannot_replace_selection(fiaga, pdf_bytes):
    app, client, engine, case, _ = setup_case(fiaga, pdf_bytes)
    selected = copy.deepcopy(case['identification'])
    selected['requests'].pop()
    calls = engine.calls
    edit(client, case, selected)
    response = client.put(f"/api/cases/{case['id']}/identification", json={
        'version': case['version'], 'identification': case['identification'],
    })
    assert response.status_code == 409
    assert engine.calls == calls
