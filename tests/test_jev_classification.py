"""Direct classification checks with synthetic inputs and mocked transport only."""

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from pqrs_claro import jev_classification as j
from pqrs_claro.classification_questions import QUESTIONS
from pqrs_claro.models import DomainError


@pytest.fixture
def payload():
    ref = {"page": 1, "line_start": 1, "line_end": 1, "quote": "forged target quote"}
    context_ref = {
        "page": 1,
        "line_start": 2,
        "line_end": 2,
        "quote": "forged context quote",
        "quote_truncated": False,
    }
    entry = {
        "id": "P9",
        "label": "9",
        "title": "Apartado padre",
        "parent_id": None,
        "description": "Contexto de otra intención.",
        "description_truncated": False,
        "source_refs": [context_ref],
        "additional_source_ref_count": 0,
    }
    return {
        "pages": [
            {
                "number": 1,
                "text": "Solicito una copia del acta.\nAntecedentes del apartado.",
                "method": "native",
                "needs_review": False,
            }
        ],
        "identification": {
            "requests": [
                {
                    "id": "P1",
                    "label": "1",
                    "title": "Copia del acta",
                    "description": "Enviar copia.",
                    "source_refs": [ref],
                    "candidates": [{"secret": "must not send"}],
                    "retrieval_context": "must not send",
                    "context": {
                        "version": 1,
                        "target_request_id": "P1",
                        "origin": "same_petition",
                        "subject": "Caso de prueba",
                        "document_date": "2026-10-16",
                        "ancestors": [entry],
                        "children": [],
                        "referenced_requests": [],
                        "preceding_section": [],
                        "preceding_section_basis": None,
                        "unresolved_references": [
                            {
                                "label_number": "8",
                                "reason": "not_identified",
                                "candidate_request_ids": [],
                            }
                        ],
                        "omitted_request_ids": ["P8"],
                        "truncated": True,
                        "candidates": [{"secret": "must not send"}],
                        "cohort": "synthetic",
                    },
                }
            ]
        },
        "candidates": [{"secret": "must not send"}],
        "preanalysis": {"secret": "must not send"},
    }


def response_for(request):
    body = json.loads(request.content)
    return {
        "model": j.MODEL,
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "answers": {
            ident: {
                "type": "choice",
                "choice": "documents",
                "confidence": 0.9,
                "probabilities": {
                    name: float(name == "documents")
                    for name in QUESTIONS["petition_type"]["criteria"]
                },
                "untrusted_extra": "not persisted",
            }
            for ident in body["questions"]
        },
    }


def classifier(handler):
    return j.JevPetitionClassifier(key="private-test-key", transport=httpx.MockTransport(handler))


def test_individual_direct_payload_preserves_context_rehydrates_quotes_and_does_not_mutate(
    payload, monkeypatch
):
    before = copy.deepcopy(payload)
    seen = []
    metrics = []
    monkeypatch.setattr(j, "record_jev_attempt", lambda **event: metrics.append(event))

    def handler(request):
        assert str(request.url) == j.ENDPOINT
        assert request.headers["authorization"] == "Bearer private-test-key"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response_for(request))

    result = classifier(handler).classify(payload)
    assert payload == before
    assert list(result) == ["P1"] and result["P1"]["choice"] == "documents"
    assert set(result["P1"]) == {"choice", "confidence", "probabilities"}
    body = seen[0]
    request = body["state"]["requests"][0]
    assert set(body["state"]) == {"requests"}
    assert body["model"] == "jev-1.14.0" and set(body["questions"]) == {"P1"}
    assert body["questions"]["P1"]["criteria"] == QUESTIONS["petition_type"]["criteria"]
    assert j.SCOPE.format(id="P1") in body["questions"]["P1"]["instructions"]
    assert set(request) == {"id", "label", "title", "description", "source_refs", "context"}
    assert request["source_refs"][0]["quote"] == "Solicito una copia del acta."
    assert (
        request["context"]["ancestors"][0]["source_refs"][0]["quote"]
        == "Antecedentes del apartado."
    )
    assert request["context"]["omitted_request_ids"] == ["P8"]
    assert request["context"]["truncated"] is True
    assert (
        request["context"]["unresolved_references"]
        == before["identification"]["requests"][0]["context"]["unresolved_references"]
    )
    assert "must not send" not in json.dumps(body) and "cohort" not in json.dumps(body)
    assert "alias" not in json.dumps(body) and "experiment" not in json.dumps(body)
    assert len(metrics) == 1 and metrics[0]["status"] == "ok" and metrics[0]["http_status"] == 200
    assert metrics[0]["usage"] == {"input_tokens": 100, "output_tokens": 20}


def test_existing_context_quote_truncation_is_explicit_and_target_remains_complete(payload):
    long_line = "X" * (j.MAX_QUOTE_CHARACTERS + 70)
    payload["pages"][0]["text"] = long_line + "\n" + long_line
    entry = payload["identification"]["requests"][0]["context"]["ancestors"][0]
    entry["source_refs"][0]["quote_truncated"] = True
    projected = j.classification_requests(payload)[0]
    assert projected["source_refs"][0]["quote"] == long_line
    context_ref = projected["context"]["ancestors"][0]["source_refs"][0]
    assert (
        context_ref["quote"] == long_line[: j.MAX_QUOTE_CHARACTERS]
        and context_ref["quote_truncated"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.update(model="jev-latest"),
        lambda raw: raw["answers"].clear(),
        lambda raw: raw["answers"].update(P99=copy.deepcopy(raw["answers"]["P1"])),
        lambda raw: raw["answers"]["P1"].update(type="text"),
        lambda raw: raw["answers"]["P1"].update(choice="invented"),
        lambda raw: raw["answers"]["P1"]["probabilities"].pop("claim"),
        lambda raw: raw["answers"]["P1"]["probabilities"].update(documents=True),
        lambda raw: raw["answers"]["P1"]["probabilities"].update(documents=-0.1),
        lambda raw: raw["answers"]["P1"]["probabilities"].update(documents=0.5),
        lambda raw: raw["answers"]["P1"].update(confidence="nan"),
    ],
)
def test_invalid_output_has_no_retry_and_exposes_no_provider_body(payload, monkeypatch, mutation):
    seen = []
    events = []
    monkeypatch.setattr(j, "record_jev_attempt", lambda **event: events.append(event))

    def handler(request):
        seen.append(request)
        raw = response_for(request)
        mutation(raw)
        raw["private"] = "private-test-key"
        return httpx.Response(200, json=raw)

    with pytest.raises(DomainError, match="incompleta o inválida") as exc:
        classifier(handler).classify(payload)
    assert len(seen) == 1 and "private-test-key" not in str(exc.value)
    assert events[0]["status"] == "invalid_response" and events[0]["usage"]["input_tokens"] == 100


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_nonfinite_and_boolean_probabilities_rejected(value):
    with pytest.raises(ValueError):
        j._probability(value)


@pytest.mark.parametrize("status", [401, 402, 403, 404, 302])
def test_nontransient_http_errors_are_visible_without_retry_or_redirect(payload, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="private-test-key", headers={"Location": "https://api.openai.com"}
        )

    with pytest.raises(DomainError, match=f"HTTP {status}") as exc:
        classifier(handler).classify(payload)
    assert len(calls) == 1 and "private-test-key" not in str(exc.value)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_one_transient_retry_uses_same_payload_and_bounded_retry_after(
    payload, monkeypatch, status
):
    calls = []
    waits = []
    events = []
    monkeypatch.setattr(j.time, "sleep", waits.append)
    monkeypatch.setattr(j, "record_jev_attempt", lambda **event: events.append(event))

    def handler(request):
        calls.append(request.content)
        if len(calls) == 1:
            return httpx.Response(status, headers={"Retry-After": "86400"})
        return httpx.Response(200, json=response_for(request))

    assert classifier(handler).classify(payload)["P1"]["choice"] == "documents"
    assert len(calls) == 2 and calls[0] == calls[1]
    assert waits == [j.MAX_RETRY_AFTER_SECONDS]
    assert [e["retry"] for e in events] == [False, True]
    assert [e["status"] for e in events] == ["http_error", "ok"]


def test_transport_error_stops_after_two_attempts_without_luna(payload, monkeypatch):
    import openai

    calls = []
    events = []
    waits = []
    monkeypatch.setattr(j.time, "sleep", waits.append)
    monkeypatch.setattr(j, "record_jev_attempt", lambda **event: events.append(event))
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: pytest.fail("Luna fallback forbidden"))

    def handler(request):
        calls.append(request.content)
        raise httpx.ConnectError("private-test-key", request=request)

    with pytest.raises(DomainError, match="siguen guardadas") as exc:
        classifier(handler).classify(payload)
    assert len(calls) == 2 and calls[0] == calls[1] and waits == [1.0]
    assert "private-test-key" not in str(exc.value)
    assert all(event["usage"] is None and event["http_status"] is None for event in events)
    assert all(event["error_type"] == "ConnectError" for event in events)


def test_two_503_responses_stop_without_third_request(payload, monkeypatch):
    calls = []
    monkeypatch.setattr(j.time, "sleep", lambda _: None)

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(DomainError, match="HTTP 503"):
        classifier(handler).classify(payload)
    assert len(calls) == 2


def test_duplicate_ids_bad_reference_and_oversized_context_fail_before_network(payload):
    def forbidden(request):
        pytest.fail("No API attempt allowed")

    bad = copy.deepcopy(payload)
    bad["identification"]["requests"] *= 2
    with pytest.raises(DomainError, match="identificadores únicos"):
        classifier(forbidden).classify(bad)
    bad = copy.deepcopy(payload)
    bad["identification"]["requests"][0]["source_refs"][0]["line_end"] = 10
    with pytest.raises(DomainError, match="rango de líneas"):
        classifier(forbidden).classify(bad)
    bad = copy.deepcopy(payload)
    bad["identification"]["requests"][0]["context"]["subject"] = "á" * j.MAX_REQUEST_BYTES
    with pytest.raises(DomainError, match="No se ha recortado ni enviado"):
        classifier(forbidden).classify(bad)


def test_workers_are_bounded_propagate_context_and_return_input_order(payload):
    source = payload["identification"]["requests"][0]
    payload["identification"]["requests"] = [
        {**copy.deepcopy(source), "id": f"P{i}"} for i in range(1, 6)
    ]
    lock = threading.Lock()
    release = threading.Event()
    full = threading.Event()
    marker = ContextVar("classification_test_marker", default=None)
    active = peak = 0
    calls = []

    def handler(request):
        nonlocal active, peak
        assert marker.get() == "copied"
        body = json.loads(request.content)
        assert len(body["questions"]) == len(body["state"]["requests"]) == 1
        with lock:
            calls.extend(body["questions"])
            active += 1
            peak = max(peak, active)
            if active == 2:
                full.set()
        try:
            assert release.wait(5)
            return httpx.Response(200, json=response_for(request))
        finally:
            with lock:
                active -= 1

    def run():
        marker.set("copied")
        return classifier(handler).classify(payload)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        try:
            assert full.wait(5)
        finally:
            release.set()
        decisions = future.result(timeout=5)
    assert peak == 2 and list(decisions) == [f"P{i}" for i in range(1, 6)]
    assert sorted(calls) == [f"P{i}" for i in range(1, 6)]


def test_retry_after_http_date_and_invalid_values_are_bounded():
    future = format_datetime(datetime.now(timezone.utc) + timedelta(days=1))
    assert j.retry_delay(future) == j.MAX_RETRY_AFTER_SECONDS
    assert j.retry_delay("-4") == 0 and j.retry_delay("0") == 0
    assert j.retry_delay("nan") == j.retry_delay("invalid") == j.retry_delay(None) == 1


def test_key_sources_are_typesafe_only_and_relative_paths_use_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "ROOT", tmp_path)
    for name in ("TYPESAFE_API_KEY", "PQRS_CLARO_JEV_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway-only")
    (tmp_path / ".env.jev.local").write_text("AI_GATEWAY_API_KEY=gateway-only\n", encoding="utf-8")
    assert j.get_key() == ""
    (tmp_path / ".env.jev.local").write_text("TYPESAFE_API_KEY=default-local\n", encoding="utf-8")
    assert j.get_key() == "default-local"
    (tmp_path / "selected.env").write_text("TYPESAFE_API_KEY=selected-local\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("PQRS_CLARO_JEV_KEY_FILE=selected.env\n", encoding="utf-8")
    assert j.get_key() == "selected-local"
    (tmp_path / "override.env").write_text("TYPESAFE_API_KEY=override-local\n", encoding="utf-8")
    monkeypatch.setenv("PQRS_CLARO_JEV_KEY_FILE", "override.env")
    assert j.get_key() == "override-local"
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-key")
    assert j.get_key() == "environment-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", "PEGA_AQUI_TU_CLAVE")
    assert j.get_key() == ""


def test_missing_direct_key_has_actionable_error_without_network(payload):
    engine = j.JevPetitionClassifier(
        key="", transport=httpx.MockTransport(lambda _: pytest.fail("No API"))
    )
    with pytest.raises(DomainError, match="TYPESAFE_API_KEY"):
        engine.classify(payload)
