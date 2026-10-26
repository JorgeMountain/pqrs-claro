# ruff: noqa: F811
"""Collective reading is durable, version-bound and never approves or closes checks."""

from copy import deepcopy

import pytest
from test_review_service_api import current, prepare, review_app, save, url  # noqa: F401

from pqrs_claro.response_reading import reading_state
from pqrs_claro.review_store import ReviewStore
from pqrs_claro.storage import Conflict


def confirm(client, case, state, **changes):
    body = dict(content_hash=state["content_hash"], reviewed_by="Gestora de prueba", confirmed=True)
    body.update(changes)
    return client.post(url(case, "/reading-confirmation"), json=body)


def test_collective_reading_persists_without_approval_or_resolving_pending(review_app):
    app, client, engine, settings = review_app
    case, _, _ = prepare(
        app,
        client,
        count=2,
        pending=[{"kind": "fact", "description": "Confirmar un hecho concreto pendiente."}],
    )
    before = client.get(url(case)).json()
    state = before["reading_confirmation"]
    assert state["eligible"] and not state["confirmed"]
    result = confirm(client, case, state)
    assert result.status_code == 200, result.text
    after = result.json()
    assert after["reading_confirmation"]["confirmed"]
    assert after["requests"] == before["requests"]
    assert after["approved_count"] == 0 and engine.calls == 0
    persisted = ReviewStore(settings.data_dir).reading(case["id"])
    assert persisted["reviewed_by"] == "Gestora de prueba"
    assert (
        confirm(client, case, state).json()["reading_confirmation"] == after["reading_confirmation"]
    )
    with app.state.reviews.store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM response_readings").fetchone()[0] == 1


def test_edit_requires_new_confirmation_and_rejects_an_old_screen(review_app):
    app, client, _, _ = review_app
    case, _, _ = prepare(app, client, count=2)
    state = client.get(url(case)).json()["reading_confirmation"]
    assert confirm(client, case, state).status_code == 200
    row = current(client, case)
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] += " Texto actualizado."
    assert save(client, case, row, paragraphs=paragraphs).status_code == 200
    changed = client.get(url(case)).json()["reading_confirmation"]
    assert not changed["confirmed"] and changed["changed_since_confirmation"]
    assert changed["eligible"]
    assert confirm(client, case, state).status_code == 409
    assert confirm(client, case, changed).json()["reading_confirmation"]["confirmed"]


def test_confirmation_requires_true_and_all_current_responses(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    state = client.get(url(case)).json()["reading_confirmation"]
    for value in (False, "true", 1):
        assert confirm(client, case, state, confirmed=value).status_code == 422
    assert confirm(client, case, state, reviewed_by=" ").status_code == 422
    assert save(client, case, row, paragraphs=[]).status_code == 200
    assert confirm(client, case, state).status_code == 409


def test_snapshot_changes_for_citations_and_scope_not_status_or_polling():
    case = {
        "id": "c",
        "version": 2,
        "status": "confirmed",
        "identification": {"requests": [{"id": "P1"}]},
    }
    row = {
        "request_id": "P1",
        "status": "ready",
        "paragraphs": [{"text": "Texto.", "cited_chunk_ids": ["S1"], "cited_fact_ids": []}],
        "available_supports": [{"chunk_id": "S1", "quote": "Texto de respaldo."}],
    }
    base = reading_state(case, [row])
    saved = {**base, "reviewed_by": "Prueba", "reviewed_at": "2026-10-14"}
    updated = deepcopy(row)
    updated.update(revision=10, status="approved", assessment={"status": "passed"})
    assert reading_state(case, [updated], saved)["confirmed"]
    updated["available_supports"][0]["quote"] = "Otra fuente."
    assert not reading_state(case, [updated], saved)["confirmed"]
    assert not reading_state({**case, "version": 3}, [row], saved)["confirmed"]
    assert not reading_state(case, [{**row, "stale": True}], saved)["eligible"]
    assert not reading_state(case, [], saved)["eligible"]


def test_storage_rejects_concurrent_edit(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    state = client.get(url(case)).json()["reading_confirmation"]
    with pytest.raises(Conflict):
        app.state.reviews.store.save_reading(
            {"case_id": case["id"], "content_hash": state["content_hash"]},
            {row["request_id"]: row["revision"] - 1},
        )
