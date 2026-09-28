# ruff: noqa: F811
"""Unchanged source and draft inputs keep their checkpoints after a case edit."""
from copy import deepcopy

from test_draft_service_api import (
    draft_app,  # noqa: F401
    generate,
    prepared_case,
    ready_map,
    wait_drafts,
)
from test_source_service_api import (  # noqa: F401
    make_case,
    pdf_bytes,
    source_app,
    start_search,
    upload_source,
    wait_search,
)


def test_source_checkpoint_survives_unrelated_petition_edit(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case = make_case(client, pdf_bytes)
    upload_source(client)
    start_search(client, case)
    wait_search(app, client, case['id'])
    assert assessor.calls == {'P1': 1, 'P2': 1}
    identification = deepcopy(case['identification'])
    identification['requests'][0]['description'] = 'Solicito requisitos nuevos de inscripción.'
    # Simulate a new confirmed revision in this temporary database only.
    case = app.state.store.update(case['id'], identification=identification)
    start_search(client, case)
    row = wait_search(app, client, case['id'])
    assert row['status'] == 'ready', row
    assert assessor.calls == {'P1': 2, 'P2': 1}


def test_draft_checkpoint_survives_unrelated_petition_edit(draft_app):
    app, client, engine, _ = draft_app
    case, _ = prepared_case(app)
    assert generate(client, case).status_code == 202
    wait_drafts(app, client, case)
    baseline = deepcopy(engine.calls)
    identification = deepcopy(case['identification'])
    identification['requests'][0]['description'] = 'Solicito requisitos nuevos de inscripción.'
    case = app.state.store.update(case['id'], identification=identification)
    ready_map(app, case)
    assert generate(client, case).status_code == 202
    row = wait_drafts(app, client, case)
    assert row['status'] == 'ready', row
    for phase in ('plan', 'write', 'check'):
        assert engine.calls['P1', phase] == baseline['P1', phase] + 1
        assert engine.calls['P2', phase] == baseline['P2', phase]
