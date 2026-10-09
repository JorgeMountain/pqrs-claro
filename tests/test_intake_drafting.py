# ruff: noqa: F811
"""Confirmed decisions reach every drafting phase and participate in reuse keys."""

from copy import deepcopy

from test_draft_service_api import generate, wait_drafts
from test_fiaga_flow import full_flow, information_pdf, prepare_fiaga  # noqa: F401

from pqrs_claro.draft_engine import _api_context


def test_confirmed_context_and_per_request_checkpoint_invalidation(full_flow, information_pdf):
    app, client, _ = full_flow
    engine = app.state.drafts.engine
    seen = {}
    findings_seen = {}
    for phase in ("plan", "write", "check"):
        original = getattr(engine, phase)

        def capture(request, *args, _phase=phase, _original=original):
            seen[request["id"], _phase] = deepcopy(request)
            findings_seen[request["id"], _phase] = deepcopy(args[0])
            return _original(request, *args)

        setattr(engine, phase, capture)

    case, review = prepare_fiaga(full_flow, information_pdf)
    prefix = f"/api/cases/{case['id']}"
    # Use the same full-draft mode for baseline/retries (preparation uses ready-only).
    assert generate(client, case).status_code == 202
    assert wait_drafts(app, client, case)["status"] == "ready"
    baseline = deepcopy(engine.calls)
    old_request = deepcopy(seen["P2", "plan"])
    old_finding = deepcopy(findings_seen["P2", "plan"])
    for phase in ("plan", "write", "check"):
        context = seen["P1", phase]["initial_review"]
        assert context["request"]["decision"]["petition_type"] == "information"
        assert context["reviewed_by"] == review["reviewed_by"]
        assert context["document"]["observations"]
        assert context["is_documentary_evidence"] is False

    # Mutate only P1's confirmed classification/note, keeping P2 and shared inputs.
    body = {
        "revision": review["revision"],
        "reviewed_by": review["reviewed_by"],
        "document": deepcopy(review["document_decision"]),
        "requests": [
            {k: v for k, v in item.items() if k != "reference_days"}
            for item in deepcopy(review["decisions"])
        ],
    }
    body["requests"][0].update(petition_type="consultation", note="Nota humana solo de P1.")
    response = client.put(prefix + "/initial-review/decision", json=body)
    assert response.status_code == 200, response.text
    assert client.get(prefix + "/drafts").json()["stale"]
    assert generate(client, case).status_code == 202
    result = wait_drafts(app, client, case)
    assert result["status"] == "ready", result
    assert seen["P2", "plan"] == old_request
    assert findings_seen["P2", "plan"] == old_finding
    for phase in ("plan", "write", "check"):
        assert engine.calls["P1", phase] == baseline["P1", phase] + 1
        assert engine.calls["P2", phase] == baseline["P2", phase]
        assert seen["P1", phase]["initial_review"]["request"]["decision"]["note"] == (
            "Nota humana solo de P1."
        )

    # The actual OpenAI payload keeps attributed decisions out of citable supports.
    finding = app.state.sources.get(case["id"])["results"][0]
    index = {s["chunk_id"]: s for s in finding["supports"]}
    payload, aliases = _api_context(seen["P1", "plan"], finding, index)
    assert payload["request"]["initial_review"]["request"]["decision"]["petition_type"] == (
        "consultation"
    )
    assert set(aliases) == set(index)
    assert "Nota humana solo de P1." not in str(payload["finding"]["supports"])

    # An unchanged re-run reuses both, while a shared note invalidates both.
    baseline = deepcopy(engine.calls)
    assert generate(client, case).status_code == 202
    assert wait_drafts(app, client, case)["status"] == "ready"
    assert engine.calls == baseline
    review = response.json()
    body["revision"] = review["revision"]
    body["document"]["note"] = "Observación general modificada."
    assert client.put(prefix + "/initial-review/decision", json=body).status_code == 200
    assert generate(client, case).status_code == 202
    assert wait_drafts(app, client, case)["status"] == "ready"
    for request_id in ("P1", "P2"):
        assert engine.calls[request_id, "plan"] == baseline[request_id, "plan"] + 1
