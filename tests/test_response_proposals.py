# ruff: noqa: F811
"""Propuestas aisladas, revisión optimista y aplicación exclusivamente explícita."""

import threading
import time
from copy import deepcopy

from test_review_service_api import current, fact, prepare, review_app, save  # noqa: F401


class FakeProposalEngine:
    def __init__(self, blocked=False, invalid=False):
        self.calls = 0
        self.blocked, self.invalid = blocked, invalid
        self.entered, self.release = threading.Event(), threading.Event()

    def propose(self, row):
        self.calls += 1
        self.entered.set()
        if self.blocked:
            assert self.release.wait(10)
        paragraphs = deepcopy(row["paragraphs"])
        paragraphs[0]["text"] += " Ajuste propuesto sobre las decisiones registradas."
        if self.invalid:
            paragraphs[0]["cited_chunk_ids"] = ["referencia-inventada"]
        return dict(summary="Ajuste ficticio para probar la comparación.", paragraphs=paragraphs)


def endpoint(case, request_id="P1"):
    return f"/api/cases/{case['id']}/review/requests/{request_id}/proposals"


def wait(app, client, case):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (case["id"], "P1") not in app.state.proposals.active:
            return client.get(endpoint(case)).json()
        time.sleep(0.02)
    raise AssertionError("La propuesta no terminó")


def test_proposal_does_not_edit_until_explicit_apply_and_preserves_decisions(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(
        app,
        client,
        count=2,
        pending=[dict(kind="clarification", description="Comprobar el alcance de la información.")],
    )
    row = fact(client, case, row).json()
    row = save(
        client,
        case,
        row,
        resolutions=[
            dict(
                pending_id=row["pending"][0]["id"],
                action="not_applicable",
                note="Este alcance no fue solicitado.",
                cited_chunk_ids=[],
                cited_fact_ids=[],
            )
        ],
    ).json()
    other = current(client, case, "P2")
    engine = app.state.proposals.engine = FakeProposalEngine()
    assert client.get(endpoint(case)).json()["status"] == "idle"
    assert not engine.calls
    response = client.post(endpoint(case), json={"revision": row["revision"]})
    assert response.status_code == 202, response.text
    job = wait(app, client, case)
    assert job["status"] == "ready", job
    assert current(client, case) == row
    for _ in range(2):
        assert client.get(endpoint(case)).json()["id"] == job["id"]
    assert client.post(endpoint(case), json={"revision": row["revision"]}).json()["id"] == job["id"]
    assert engine.calls == 1
    applied = client.post(
        endpoint(case) + f"/{job['id']}/apply",
        json={"revision": row["revision"], "edited_by": "Revisora"},
    )
    assert applied.status_code == 200, applied.text
    value = applied.json()
    assert value["paragraphs"][0]["text"] == job["proposal"]["paragraphs"][0]["text"]
    assert value["pending"] == row["pending"] and value["facts"] == row["facts"]
    assert value["approval"] is None and value["assessment"] is None
    assert current(client, case, "P2") == other
    assert (
        client.post(
            endpoint(case) + f"/{job['id']}/apply",
            json={"revision": row["revision"], "edited_by": "Revisora"},
        ).status_code
        == 409
    )


def test_dismiss_and_recovery_do_not_rewrite_or_call_model(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    engine = app.state.proposals.engine = FakeProposalEngine()
    client.post(endpoint(case), json={"revision": row["revision"]})
    job = wait(app, client, case)
    assert client.post(endpoint(case) + f"/{job['id']}/dismiss").status_code == 200
    assert current(client, case) == row
    app.state.proposals.save(job, status="running")
    app.state.proposals.recover()
    assert client.get(endpoint(case)).json()["status"] == "interrupted"
    assert engine.calls == 1 and current(client, case) == row


def test_edit_while_generating_discards_stale_proposal(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    engine = app.state.proposals.engine = FakeProposalEngine(blocked=True)
    client.post(endpoint(case), json={"revision": row["revision"]})
    assert engine.entered.wait(5)
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] += " Cambio humano mientras la IA trabaja."
    try:
        assert save(client, case, row, paragraphs=paragraphs).status_code == 200
    finally:
        engine.release.set()
    job = wait(app, client, case)
    assert job["status"] == "error" and job["stale"]
    assert current(client, case)["paragraphs"] == paragraphs


def test_stale_ready_proposal_and_cross_case_application_are_rejected(review_app):
    app, client, _, _ = review_app
    case, source, row = prepare(app, client)
    app.state.proposals.engine = FakeProposalEngine()
    client.post(endpoint(case), json={"revision": row["revision"]})
    job = wait(app, client, case)
    app.state.library.review(
        source["id"],
        reviewed_by="Responsable",
        review_note="Cambio de vigencia",
        validity="current",
    )
    assert client.get(endpoint(case)).json()["stale"]
    assert (
        client.post(
            endpoint(case) + f"/{job['id']}/apply",
            json={"revision": row["revision"], "edited_by": "Revisora"},
        ).status_code
        == 409
    )
    other, _, _ = prepare(app, client)
    assert (
        client.post(
            endpoint(other) + f"/{job['id']}/apply",
            json={"revision": row["revision"], "edited_by": "Revisora"},
        ).status_code
        == 404
    )


def test_invented_references_are_not_accepted(review_app):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    app.state.proposals.engine = FakeProposalEngine(invalid=True)
    client.post(endpoint(case), json={"revision": row["revision"]})
    assert wait(app, client, case)["status"] == "error"
    assert current(client, case) == row
