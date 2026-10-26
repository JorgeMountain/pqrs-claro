# ruff: noqa: F811
"""Direct JEV through the real API/services and temporary SQLite, without network."""

import copy
import hashlib
import json
import threading
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_draft_service_api import FakeDraftEngine
from test_initial_review import decision, wait_intake
from test_intake_selection_reuse import edit
from test_source_service_api import (
    FakeSourceAssessor,
    TwoRequestsIdentifier,
    make_case,
    pdf_bytes,  # noqa: F401
)

from pqrs_claro import app as app_module
from pqrs_claro import intake_service, petition_classification
from pqrs_claro.app import create_app
from pqrs_claro.classification_questions import QUESTIONS
from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.jev_classification import ENDPOINT, MODEL, JevPetitionClassifier


class RecordingIdentifier(TwoRequestsIdentifier):
    def __init__(self):
        self.calls = 0

    def identify(self, pages):
        self.calls += 1
        return super().identify(pages)


class DirectResponses:
    """The provider double records only generated test requests."""

    def __init__(self):
        self.calls = []
        self.failure = None
        self.key = "test-typesafe-key-not-real"
        self.lock = threading.Lock()

    def handle(self, request):
        body = json.loads(request.content)
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer test-typesafe-key-not-real"
        assert body["model"] == MODEL
        assert len(body["state"]["requests"]) == len(body["questions"]) == 1
        rid = body["state"]["requests"][0]["id"]
        assert set(body["questions"]) == {rid}
        with self.lock:
            self.calls.append(body)
        if rid == "P1" and self.failure == "transport":
            raise httpx.ConnectError("fictitious-private-error-text", request=request)
        if rid == "P1" and self.failure == "http":
            return httpx.Response(503, headers={"Retry-After": "0"},
                                  json={"message": "fictitious-private-error-text"})
        choice = "information" if rid == "P1" else "documents"
        return httpx.Response(200, json={
            "model": MODEL,
            "answers": {rid: {
                "type": "choice", "choice": choice, "confidence": .9,
                "probabilities": {label: float(label == choice)
                                  for label in QUESTIONS["petition_type"]["criteria"]},
            }},
            "usage": {"input_tokens": 100, "output_tokens": 10},
        })

    def counts(self):
        return Counter(body["state"]["requests"][0]["id"] for body in self.calls)


@pytest.fixture
def direct_app(tmp_path, monkeypatch):
    provider, identifier = DirectResponses(), RecordingIdentifier()
    fallback_calls = []

    def forbidden_openai(*args, **kwargs):
        fallback_calls.append(True)
        raise AssertionError("JEV classification must not construct an OpenAI classifier")

    def forbidden_network(*args, **kwargs):
        raise AssertionError("This integration test permits only MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden_network)
    monkeypatch.setattr(petition_classification, "OpenAIPetitionClassifier", forbidden_openai)
    monkeypatch.setattr(petition_classification, "JevPetitionClassifier", lambda:
                        JevPetitionClassifier(key=provider.key,
                                              transport=httpx.MockTransport(provider.handle)))
    monkeypatch.setattr(intake_service, "get_jev_key", lambda: provider.key)
    monkeypatch.setattr(app_module, "get_jev_classification_key", lambda: provider.key)
    settings = Settings(data_dir=tmp_path / "generated-cases", api_key="test-openai-not-real",
                        model="gpt-6-luna", initial_review_enabled=True,
                        initial_classification_provider="jev")
    assessor, draft = FakeSourceAssessor(), FakeDraftEngine()
    app = create_app(settings, identifier=identifier, extractor=PDFExtractor(),
                     source_extractor=PDFExtractor(), source_assessor=assessor,
                     draft_engine=draft, interface="recorrido")
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client, settings=settings, provider=provider,
                              identifier=identifier, assessor=assessor,
                              fallback_calls=fallback_calls)
    assert not fallback_calls


def classified_case(env, pdf):
    case = make_case(env.client, pdf, confirm=False)
    row = wait_intake(env.app, env.client, case)
    assert row["status"] == "needs_review", row
    return case, row


def retry(env, case, row):
    response = env.client.post(f"/api/cases/{case['id']}/initial-review/analyze", json={
        "version": case["version"], "revision": row["revision"], "mode": "incremental"})
    assert response.status_code == 202, response.text
    return wait_intake(env.app, env.client, case)


def test_automatic_direct_jev_preserves_extraction_citations_and_human_gate(direct_app, pdf_bytes):
    env = direct_app
    case, row = classified_case(env, pdf_bytes)
    prefix = f"/api/cases/{case['id']}"
    assert env.identifier.calls == 1
    assert env.provider.counts() == {"P1": 1, "P2": 1}
    assert case["status"] == "needs_review" and case["confirmed_at"] is None
    assert row["classification_provider"] == "jev" and row["classification_model"] == MODEL
    assert not row["can_prepare"] and row["decisions"] is None and not row["stale"]
    assert row["analysis_scope"] == "petition_types_v1"
    assert row["consulted_sources"] == [] and row["scope"]["library_search"] == "not_requested"
    assert [r["petition_type"] for r in row["report"]["requests"]] == ["information", "documents"]
    for original, result in zip(
        case["identification"]["requests"], row["report"]["requests"], strict=True
    ):
        assert result["classification_model"] == MODEL
        assert result["classification_confidence"] == .9
        assert set(result["classification_probabilities"]) == set(
            QUESTIONS["petition_type"]["criteria"])
        assert result["draft"] is None
        check = next(c for c in result["checks"] if c["key"] == "classification")
        assert check["original_refs"] == original["source_refs"]
        sent = next(b["state"]["requests"][0] for b in env.provider.calls
                    if b["state"]["requests"][0]["id"] == original["id"])
        assert sent["source_refs"] == original["source_refs"]
        assert sent["context"]["target_request_id"] == original["id"]
    assert env.client.get(prefix).json()["identification"] == case["identification"]
    assert env.app.state.store.original(case["id"]).read_bytes() == pdf_bytes
    assert hashlib.sha256(pdf_bytes).hexdigest() == case["sha256"]
    with env.app.state.store.connect() as connection:
        saved = json.loads(connection.execute(
            "SELECT body FROM intake_reviews WHERE case_id=?", (case["id"],)).fetchone()[0])
    assert saved["report"] == row["report"]
    blocked = env.client.post(prefix + "/preparation", json={"version": case["version"]})
    assert blocked.status_code == 409
    rejected = decision(row)
    rejected["document"]["reviewed"] = False
    assert env.client.put(prefix + "/initial-review/decision", json=rejected).status_code == 422
    response = env.client.put(prefix + "/initial-review/decision", json=decision(row))
    assert response.status_code == 200, response.text
    assert response.json()["can_prepare"] and response.json()["status"] == "approved"
    assert env.client.get(prefix).json()["status"] == "confirmed"
    assert env.identifier.calls == 1 and len(env.provider.calls) == 2
    assert not env.assessor.calls and not env.app.state.preparation.active
    assert env.app.state.library.latest_run(case["id"]) is None
    events = env.client.get(prefix + "/performance").json()["events"]
    calls = [event for event in events if event["kind"] == "provider"]
    assert len(calls) == 2 and {event["request_id"] for event in calls} == {"P1", "P2"}
    assert all(event["provider"] == "typesafe" and event["model"] == MODEL
               and event["http_attempts"] == 1 and event["status"] == "ok" for event in calls)


def test_noop_reuses_both_and_edit_only_reclassifies_independent_request(direct_app, pdf_bytes):
    env = direct_app
    case, first = classified_case(env, pdf_bytes)
    reused = retry(env, case, first)
    assert reused["revision"] == first["revision"] and reused["report"] == first["report"]
    assert len(env.provider.calls) == 2
    changed = copy.deepcopy(case["identification"])
    changed["requests"][0]["description"] = (
        "Solicito informar los requisitos actualizados de prácticas.")
    case = edit(env.client, case, changed)
    row = wait_intake(env.app, env.client, case)
    assert row["status"] == "needs_review" and not row["stale"]
    assert env.provider.counts() == {"P1": 2, "P2": 1}
    assert row["timings"]["evaluated_requests"] == row["timings"]["reused_requests"] == 1
    assert row["report"]["requests"][1] == first["report"]["requests"][1]
    assert env.client.get(f"/api/cases/{case['id']}").json()["identification"] == changed
    assert env.identifier.calls == 1 and not row["can_prepare"]


@pytest.mark.parametrize("failure", ["transport", "http"])
def test_failed_edit_preserves_identification_and_retries_only_pending_without_openai(
    direct_app, pdf_bytes, failure
):
    env = direct_app
    case, first = classified_case(env, pdf_bytes)
    env.provider.failure = failure
    changed = copy.deepcopy(case["identification"])
    changed["requests"][0]["title"] = "Requisitos actualizados de prácticas"
    case = edit(env.client, case, changed)
    failed = wait_intake(env.app, env.client, case)
    assert failed["status"] == "error" and not failed["can_prepare"]
    assert "fictitious-private-error-text" not in failed["error"]
    assert env.provider.counts() == {"P1": 3, "P2": 1}  # one initial + two failed attempts
    assert env.client.get(f"/api/cases/{case['id']}").json()["identification"] == changed
    assert env.identifier.calls == 1 and not env.fallback_calls
    cache = env.app.state.initial_review.saved(case["id"])["analysis_cache"]
    assert cache["entries"]["P2"]["report"] == first["report"]["requests"][1]
    env.provider.failure = None
    recovered = retry(env, case, failed)
    assert recovered["status"] == "needs_review" and not recovered["stale"]
    assert env.provider.counts() == {"P1": 4, "P2": 1}
    assert recovered["report"]["requests"][1] == first["report"]["requests"][1]
    assert not recovered["can_prepare"] and recovered["decisions"] is None
    metrics = env.client.get(f"/api/cases/{case['id']}/performance").json()
    errors = [e for e in metrics["events"] if e.get("provider") == "typesafe"
              and e["status"] in {"transport_error", "http_error"}]
    assert len(errors) == 2 and sum(e["http_retries"] for e in errors) == 1
    assert all(e["input_tokens"] is None and e["output_tokens"] is None for e in errors)
    assert metrics["estimated_cost_usd"] is None and metrics["calls_without_usage"] == 2
    assert "fictitious-private-error-text" not in json.dumps(metrics)


@pytest.mark.parametrize("change", ["provider", "model", "version", "context"])
def test_config_change_marks_saved_result_stale_without_rewriting_it(
    direct_app, pdf_bytes, monkeypatch, change
):
    env = direct_app
    case, row = classified_case(env, pdf_bytes)
    prefix = f"/api/cases/{case['id']}/initial-review"
    assert env.client.put(prefix + "/decision", json=decision(row)).json()["can_prepare"]
    service = env.app.state.initial_review
    saved = copy.deepcopy(service.saved(case["id"]))
    if change == "provider":
        service.settings = replace(service.settings, initial_classification_provider="openai")
    else:
        key = {"model": "JEV_MODEL", "version": "JEV_CLASSIFICATION_VERSION",
               "context": "CONTEXT_VERSION"}[change]
        value = "jev-test-other" if change == "model" else getattr(intake_service, key) + 1
        monkeypatch.setattr(intake_service, key, value)
    stale = env.client.get(prefix).json()
    assert stale["stale"] and not stale["can_prepare"]
    assert stale["next_analysis"]["pending"] == ["P1", "P2"]
    assert stale["report"] == saved["report"]
    assert all(r["classification_model"] == MODEL for r in stale["report"]["requests"])
    assert service.saved(case["id"]) == saved
    assert len(env.provider.calls) == 2 and not env.fallback_calls


def test_api_config_exposes_direct_model_and_readiness_without_secret(direct_app):
    env = direct_app
    result = env.client.get("/api/config").json()
    assert result["initial_review_enabled"] and result["automatic_initial_review"]
    assert result["initial_classification_provider"] == "jev"
    assert result["initial_classification_model"] == MODEL
    assert result["initial_classification_ready"] is True
    assert result["model"] == "gpt-6-luna" and result["ready"] is True
    assert env.provider.key not in json.dumps(result)
    env.provider.key = ""
    result = env.client.get("/api/config").json()
    assert result["initial_classification_ready"] is False and result["ready"] is True
    assert not env.provider.calls


def test_missing_direct_key_keeps_identified_petitions_and_sends_nothing(direct_app, pdf_bytes):
    env = direct_app
    env.provider.key = ""
    case = make_case(env.client, pdf_bytes, confirm=False)
    failed = wait_intake(env.app, env.client, case)
    assert failed["status"] == "error" and not failed["can_prepare"]
    persisted = env.client.get(f"/api/cases/{case['id']}").json()
    assert persisted["identification"] == case["identification"]
    assert not env.provider.calls and not env.fallback_calls and env.identifier.calls == 1
