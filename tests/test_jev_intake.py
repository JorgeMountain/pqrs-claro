# ruff: noqa: F811
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_initial_review import FakeIntake, decision, wait_intake
from test_source_service_api import TwoRequestsIdentifier, make_case, pdf_bytes  # noqa: F401

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.intake_engine import CONTEXT_INSTRUCTIONS, context_schema, numbered_payload
from pqrs_claro.intake_models import IntakeContextAssessment
from pqrs_claro.jev_intake import (
    MAX_CONCURRENT_BATCHES,
    TYPE_NAMES,
    JevIntakeEngine,
    JevPetitionClassifier,
)
from pqrs_claro.models import DomainError


class FakeContext(FakeIntake):
    def assess(self, payload):
        report = super().assess(payload)
        for row in report["requests"]:
            del row["petition_type"]
            row["checks"] = [c for c in row["checks"] if c["key"] == "repetition"]
        return report


def reply(request):
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "answers": {
                key: {
                    "type": "choice",
                    "choice": "information" if key != "P2" else "documents",
                    "confidence": 0.9,
                    "probabilities": {
                        name: float(name == ("information" if key != "P2" else "documents"))
                        for name in TYPE_NAMES
                    },
                    "untrusted_extra": "Do not persist this text",
                }
                for key in body["questions"]
            }
        },
    )


@pytest.fixture
def payload():
    return {
        "pages": [
            {
                "number": 1,
                "text": "Informar los requisitos.\nEnviar copia del acta.",
                "method": "native",
                "needs_review": False,
            }
        ],
        "identification": {
            "requests": [
                {
                    "id": f"P{i}",
                    "title": title,
                    "description": title,
                    "source_refs": [
                        {"page": 1, "line_start": i, "line_end": i, "quote": "not trusted"}
                    ],
                }
                for i, title in enumerate(["Requisitos", "Acta"], 1)
            ]
        },
        "candidates": [],
    }


def test_only_jev_assigns_types_and_original_excerpts_are_rehydrated(payload):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer private-test-key"
        assert request.url.host == "ai-gateway.vercel.sh"
        return reply(request)

    context = FakeContext()
    engine = JevIntakeEngine(
        Settings(api_key="test"),
        context_engine=context,
        classifier=JevPetitionClassifier(
            key="private-test-key", transport=httpx.MockTransport(handler)
        ),
    )
    report = engine.assess(payload).model_dump(mode="json")
    assert [r["petition_type"] for r in report["requests"]] == ["information", "documents"]
    assert all(r["classification_model"] == "typesafe-ai/jev" for r in report["requests"])
    assert set(seen[0]["questions"]) == {"P1", "P2"}
    assert seen[0]["state"]["requests"][0]["original_excerpts"] == ["Informar los requisitos."]
    assert context.calls == 1
    assert "private-test-key" not in json.dumps(report)
    assert "untrusted_extra" not in json.dumps(report)
    schema = IntakeContextAssessment.model_json_schema()
    assert "petition_type" not in schema["$defs"]["ContextRequestIntake"]["properties"]
    assert schema["$defs"]["RepetitionCheck"]["properties"]["key"]["const"] == "repetition"
    assert "Clasifica por intención" not in CONTEXT_INSTRUCTIONS


@pytest.mark.parametrize(
    "failure", ["unauthorized", "unavailable", "missing", "nan", "invalid_choice"]
)
def test_cloud_failures_do_not_fall_back_to_openai(payload, failure):
    def handler(request):
        if failure == "unauthorized":
            return httpx.Response(401, text="private-test-key")
        if failure == "unavailable":
            return httpx.Response(503, text="private-test-key")
        data = reply(request).json()
        if failure == "missing":
            del data["answers"]["P2"]
        elif failure == "nan":
            data["answers"]["P1"]["confidence"] = "nan"
        else:
            data["answers"]["P1"]["choice"] = "arbitrary"
        return httpx.Response(200, json=data)

    context = FakeContext()
    engine = JevIntakeEngine(
        Settings(),
        context_engine=context,
        classifier=JevPetitionClassifier(key="test", transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DomainError) as exc:
        engine.assess(payload)
    assert "private-test-key" not in str(exc.value)
    assert context.calls == 1  # Independent context runs, but never replaces JEV types.
    if failure == "unavailable":
        assert "temporalmente" in str(exc.value)
        assert "saldo" not in str(exc.value)


def test_large_request_rejected_without_truncation_or_network(payload):
    payload["identification"]["requests"][0]["description"] = "x" * 25000

    def handler(request):
        pytest.fail("No oversized content should be sent")

    classifier = JevPetitionClassifier(key="test", transport=httpx.MockTransport(handler))
    with pytest.raises(DomainError, match="no se ha recortado"):
        classifier.classify(payload)


def test_batches_cover_every_request(payload):
    source = payload["identification"]["requests"][0]
    payload["identification"]["requests"] = [
        {**copy.deepcopy(source), "id": f"P{i}"} for i in range(1, 10)
    ]
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        # Reproduce the observed provider failure without relying on live availability.
        if len(body["questions"]) > 2:
            return httpx.Response(503, json={"error": {"type": "service_unavailable_error"}})
        return reply(request)

    classifier = JevPetitionClassifier(key="test", transport=httpx.MockTransport(handler))
    result = classifier.classify(payload)
    assert set(result) == {f"P{i}" for i in range(1, 10)}
    assert len(calls) >= 2
    keys = [key for body in calls for key in body["questions"]]
    assert len(keys) == len(set(keys)) == 9
    assert set(keys) == {f"P{i}" for i in range(1, 10)}


def test_context_cannot_invent_source_ids(payload):
    schema = context_schema(payload).model_json_schema()
    assert schema["$defs"]["SourcedDocumentCheck"]["properties"]["chunk_ids"]["maxItems"] == 0
    payload["candidates"] = [{"chunk_id": "real-1"}, {"chunk_id": "real-2"}]
    schema = context_schema(payload).model_json_schema()
    for name in ("SourcedDocumentCheck", "SourcedRepetitionCheck"):
        assert schema["$defs"][name]["properties"]["chunk_ids"]["items"]["enum"] == [
            "real-1",
            "real-2",
        ]


def test_document_and_classification_run_concurrently(payload):
    barrier = threading.Barrier(2)

    class Context(FakeContext):
        def assess(self, payload):
            barrier.wait(timeout=5)
            return super().assess(payload)

    def handler(request):
        barrier.wait(timeout=5)
        return reply(request)

    engine = JevIntakeEngine(
        Settings(),
        context_engine=Context(),
        classifier=JevPetitionClassifier(key="test", transport=httpx.MockTransport(handler)),
    )
    assert len(engine.assess(payload).requests) == 2


def test_context_references_are_bounded_by_each_real_page(payload):
    from pydantic import ValidationError

    payload["pages"].append({
        "number": 2, "text": "Una línea", "method": "native", "needs_review": False,
    })
    schema = context_schema(payload)
    report = FakeContext().assess(payload)
    schema.model_validate(report)
    for ref in (
        {"page": 1, "line_start": 1, "line_end": 3},
        {"page": 2, "line_start": 1, "line_end": 2},
        {"page": 3, "line_start": 1, "line_end": 1},
    ):
        report["document"]["checks"][0]["original_refs"] = [ref]
        with pytest.raises(ValidationError):
            schema.model_validate(report)
    numbered = numbered_payload(payload)
    assert numbered["pages"][0]["lines"][1] == {"number": 2, "text": "Enviar copia del acta."}
    assert "text" in payload["pages"][0]  # JEV still receives the unmodified original.


def test_batch_concurrency_is_bounded_and_covers_all_petitions(payload):
    source = payload["identification"]["requests"][0]
    payload["identification"]["requests"] = [
        {**copy.deepcopy(source), "id": f"P{i}"} for i in range(1, 11)
    ]
    lock, release, full = threading.Lock(), threading.Event(), threading.Event()
    active = peak = 0

    def handler(request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == MAX_CONCURRENT_BATCHES:
                full.set()
        try:
            assert release.wait(5)
            return reply(request)
        finally:
            with lock:
                active -= 1

    classifier = JevPetitionClassifier(key="test", transport=httpx.MockTransport(handler))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(classifier.classify, payload)
        try:
            assert full.wait(5), "Independent batches must overlap"
        finally:
            release.set()
        result = future.result(timeout=5)
    assert peak == MAX_CONCURRENT_BATCHES
    assert list(result) == [f"P{i}" for i in range(1, 11)]


def test_provider_503_splits_only_the_failed_pair_without_losing_content(payload):
    source = payload["identification"]["requests"][0]
    payload["identification"]["requests"] = [
        {**copy.deepcopy(source), "id": f"P{i}"} for i in range(1, 5)
    ]
    seen = []

    def handler(request):
        body = json.loads(request.content)
        ids = tuple(body["questions"])
        seen.append(ids)
        if ids == ("P3", "P4"):
            return httpx.Response(503)
        assert all(r["original_excerpts"] == ["Informar los requisitos."]
                   for r in body["state"]["requests"])
        return reply(request)

    classifier = JevPetitionClassifier(key="test", transport=httpx.MockTransport(handler))
    result = classifier.classify(payload)
    assert set(result) == {"P1", "P2", "P3", "P4"}
    assert seen.count(("P1", "P2")) == 1
    assert seen.count(("P3", "P4")) == seen.count(("P3",)) == seen.count(("P4",)) == 1


def test_real_service_uses_jev_persists_metadata_and_invalidates_old_provider(
    tmp_path, monkeypatch, pdf_bytes
):
    context = FakeContext()
    classifier = JevPetitionClassifier(key="test", transport=httpx.MockTransport(reply))
    monkeypatch.setattr("pqrs_claro.jev_intake.OpenAIIntakeEngine", lambda *a, **k: context)
    monkeypatch.setattr("pqrs_claro.petition_classification.JevPetitionClassifier",
                        lambda: classifier)
    monkeypatch.setattr("pqrs_claro.intake_service.get_jev_key", lambda: "test")
    settings = Settings(
        data_dir=tmp_path,
        api_key="fake",
        model="fake",
        initial_review_enabled=True,
        initial_classification_provider="jev",
    )
    app = create_app(settings, identifier=TwoRequestsIdentifier())
    with TestClient(app) as client:
        case = make_case(client, pdf_bytes)
        prefix = f"/api/cases/{case['id']}/initial-review"
        row = wait_intake(app, client, case)
        assert row["status"] == "needs_review", row
        assert row["classification_provider"] == "jev"
        assert context.calls == 0  # Classification never starts a general OpenAI review.
        assert row["analysis_scope"] == "petition_types_v1"
        assert row["scope"]["library_search"] == "not_requested"
        assert not row["can_prepare"]
        assert row["report"]["requests"][1]["petition_type"] == "documents"
        assert row["report"]["requests"][0]["checks"][1]["original_refs"][0]["quote"]
        assert client.put(prefix + "/decision", json=decision(row)).status_code == 200
        assert client.get(prefix).json()["can_prepare"]
        app.state.initial_review.settings = replace(
            settings, initial_classification_provider="openai"
        )
        assert client.get(prefix).json()["stale"]
        assert not client.get(prefix).json()["can_prepare"]


def test_free_tier_restriction_explains_required_action_without_echoing_body(payload):
    def blocked(request):
        return httpx.Response(403, json={'error': {
            'type': 'no_providers_available',
            'message': 'Free tier users do not have access to this model. secret-untrusted-extra',
        }})

    classifier = JevPetitionClassifier(key='test', transport=httpx.MockTransport(blocked))
    with pytest.raises(DomainError, match='créditos gratuitos') as exc:
        classifier.classify(payload)
    assert 'secret-untrusted-extra' not in str(exc.value)
