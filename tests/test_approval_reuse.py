"""Shared approval checks keep freshness, individual consent and saved snapshots."""
# ruff: noqa: F811 -- imported pytest fixtures.
import os
from copy import deepcopy

import pytest
from test_review_service_api import approve, assess, current, prepare, save
from test_review_service_api import review_app as review_app


def ready_responses(app, client, count=3):
    case, source, _ = prepare(app, client, count=count)
    rows = [assess(app, client, case, current(client, case, f"P{i}"))
            for i in range(1, count+1)]
    return case, source, rows


def observe_inputs(app, monkeypatch):
    calls = []
    original = app.state.drafts._inputs

    def checked(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(app.state.drafts, "_inputs", checked)
    return calls


def test_ten_approvals_share_one_map_check_keep_separate_snapshots(review_app, monkeypatch):
    app, client, engine, _ = review_app
    case, _, rows = ready_responses(app, client, count=10)
    before, provider_calls = deepcopy(app.state.store.get(case["id"])), engine.calls
    calls = observe_inputs(app, monkeypatch)
    saved = [approve(client, case, row) for row in rows]
    assert all(response.status_code == 200 for response in saved)
    assert calls == [case["id"]]
    assert len({response.json()["approval"]["id"] for response in saved}) == 10
    assert engine.calls == provider_calls
    assert app.state.store.get(case["id"]) == before
    assert [response.json()["paragraphs"] for response in saved] == [r["paragraphs"] for r in rows]
    assert client.get(f"/api/cases/{case['id']}/review/approved").status_code == 200


@pytest.mark.parametrize("change", ["source_review", "case_version", "initial_review"])
def test_changed_common_inputs_are_never_reused(review_app, monkeypatch, change):
    app, client, _, _ = review_app
    case, source, rows = ready_responses(app, client)
    calls = observe_inputs(app, monkeypatch)
    first = approve(client, case, rows[0])
    assert first.status_code == 200
    snapshot = app.state.reviews.store.approval(first.json()["approval"]["id"])
    if change == "source_review":
        app.state.library.review(source["id"], reviewed_by="QA", review_note="Nueva revisión",
                                 validity="current")
    elif change == "case_version":
        app.state.store.update(case["id"], status="needs_review")
    else:
        app.state.initial_review.enabled = True
    rejected = approve(client, case, rows[1])
    assert rejected.status_code == 409, rejected.text
    assert app.state.reviews.store.approval(snapshot["id"]) == snapshot
    assert app.state.reviews.store.get(case["id"], "P2")["paragraphs"] == rows[1]["paragraphs"]
    assert len(calls) >= 1


@pytest.mark.parametrize("original_kind", ["source", "case"])
def test_original_bytes_still_checked_even_with_unchanged_catalog_and_timestamp(
    review_app, original_kind,
):
    app, client, _, _ = review_app
    case, source, rows = ready_responses(app, client)
    assert approve(client, case, rows[0]).status_code == 200
    revision = app.state.library.catalog_revision()
    path = (app.state.library.original(source["id"]) if original_kind == "source"
            else app.state.store.original(case["id"]))
    stat, content = path.stat(), path.read_bytes()
    path.write_bytes(b"X"*len(content))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    response = approve(client, case, rows[1])
    assert response.status_code == 422, response.text
    assert app.state.library.catalog_revision() == revision
    assert not app.state.reviews.store.get(case["id"], "P2")["approval"]
    path.write_bytes(content)
    assert approve(client, case, rows[1]).status_code == 200


def test_cached_common_checks_do_not_approve_an_edited_response(review_app):
    app, client, _, _ = review_app
    case, _, rows = ready_responses(app, client)
    assert approve(client, case, rows[0]).status_code == 200
    paragraphs = deepcopy(rows[1]["paragraphs"])
    paragraphs[0]["text"] += " Edición humana posterior."
    assert save(client, case, rows[1], paragraphs=paragraphs).status_code == 200
    assert approve(client, case, rows[1]).status_code == 409
    changed = current(client, case, "P2")
    assert changed["paragraphs"] == paragraphs
    assert changed["approval"] is None


def test_change_during_common_validation_rejects_approval(review_app, monkeypatch):
    app, client, _, _ = review_app
    case, source, rows = ready_responses(app, client)
    original = app.state.drafts._inputs

    def changed(*args):
        result = original(*args)
        app.state.library.review(source["id"], reviewed_by="QA", review_note="Cambio concurrente",
                                 validity="current")
        return result

    monkeypatch.setattr(app.state.drafts, "_inputs", changed)
    assert approve(client, case, rows[0]).status_code == 409
    assert not app.state.reviews.store.get(case["id"], "P1")["approval"]


def test_other_case_cannot_reuse_first_case_validation(review_app, monkeypatch):
    app, client, _, _ = review_app
    first, _, first_rows = ready_responses(app, client, count=1)
    assert approve(client, first, first_rows[0]).status_code == 200
    second, _, second_rows = ready_responses(app, client, count=1)
    calls = observe_inputs(app, monkeypatch)
    assert approve(client, second, second_rows[0]).status_code == 200
    assert calls == [second["id"]]
