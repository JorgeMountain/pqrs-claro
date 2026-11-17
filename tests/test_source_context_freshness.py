"""Original text changes must invalidate old scope even without reidentification."""

from test_draft_service_api import draft_app as _draft_app
from test_draft_service_api import prepared_case

draft_app = _draft_app


def test_changed_original_scope_invalidates_map_without_changing_question(draft_app):
    app, _, _, _ = draft_app
    case, _ = prepared_case(app, count=1)
    assert not app.state.sources.get(case["id"])["stale"]
    changed = [
        {
            "number": 1,
            "text": "Ámbito: personal técnico temporal.\nSolicito los requisitos institucionales.",
            "method": "native",
        }
    ]
    updated = app.state.store.update(case["id"], pages=changed)
    assert updated["identification"] == case["identification"]
    assert app.state.sources.get(case["id"])["stale"]


def test_old_reader_cannot_be_treated_as_rechecked_under_new_policy(draft_app):
    app, _, _, _ = draft_app
    case, _ = prepared_case(app, count=1)
    run = app.state.library.latest_run(case["id"])
    run["reader_policy"]["reader_version"] -= 1
    app.state.library.save_run(run)
    current = app.state.sources.get(case["id"])
    assert current["stale"] and current["status"] == "stale"
