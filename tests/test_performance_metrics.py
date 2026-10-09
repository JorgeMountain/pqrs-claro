import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from pqrs_claro.performance_metrics import (
    _request_hook,
    metrics_http_client,
    metrics_path,
    operation,
    provider_call,
    read_metrics,
    submit_context,
)


def folder(root, identity="case"):
    (root / "files" / identity).mkdir(parents=True)


def reply(**kwargs):
    return SimpleNamespace(status="completed", model="test-model", usage={
        "input_tokens": 1000, "output_tokens": 200,
        "input_tokens_details": {"cached_tokens": 400},
        "output_tokens_details": {"reasoning_tokens": 50},
    })


def test_usage_is_recorded_without_content_or_credentials(tmp_path):
    folder(tmp_path)
    with operation("draft", root=tmp_path, case_id="case"):
        provider_call("draft.write", reply, input="PRIVATE REQUEST", api_key="secret",
                      model="test-model")
    data = read_metrics(tmp_path, "case")
    assert data["provider_calls"] == 1
    assert data["recorded_input_tokens"] == 1000
    assert data["recorded_output_tokens"] == 200  # reasoning is already included
    assert data["estimated_cost_usd"] is None
    raw = json.dumps(data)
    assert "PRIVATE REQUEST" not in raw and "secret" not in raw
    assert data["events"][0]["cached_input_tokens"] == 400


def test_errors_missing_usage_and_missing_prices_are_not_zero_cost(tmp_path):
    folder(tmp_path)

    def broken(**kwargs):
        raise RuntimeError("secret prompt from upstream")

    with operation("sources", root=tmp_path, case_id="case"):
        with pytest.raises(RuntimeError):
            provider_call("sources.assess", broken, model="test-model")
        provider_call("sources.assess", lambda **_: SimpleNamespace(status="incomplete"))
    data = read_metrics(tmp_path, "case")
    assert data["calls_without_usage"] == 2
    assert data["estimated_cost_usd"] is None
    assert data["events"][0]["error_type"] == "RuntimeError"
    assert "secret prompt" not in json.dumps(data)


def test_configured_estimate_separates_cached_input_and_does_not_double_count_reasoning(tmp_path):
    folder(tmp_path)
    (tmp_path / "metrics-pricing.json").write_text(json.dumps({"test-model": {
        "input_per_million_usd": 2, "cached_input_per_million_usd": 0.5,
        "output_per_million_usd": 8,
    }}))
    with operation("draft", root=tmp_path, case_id="case"):
        provider_call("draft.write", reply)
    data = read_metrics(tmp_path, "case")
    assert data["estimated_cost_usd"] == pytest.approx(0.003)
    assert data["priced_calls"] == 1


def test_parallel_cases_and_requests_have_separate_contexts(tmp_path):
    for case in ("one", "two"):
        folder(tmp_path, case)

    def request(identity):
        with operation("draft.request", request_id=identity):
            provider_call("draft.write", reply)

    def run(case):
        with operation("draft", root=tmp_path, case_id=case):
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [submit_context(pool, request, f"{case}-{i}") for i in range(6)]
                for future in futures:
                    future.result()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ("one", "two")))
    for case in ("one", "two"):
        data = read_metrics(tmp_path, case)
        assert data["provider_calls"] == 6
        assert all(e["request_id"].startswith(case)
                   for e in data["events"] if e["kind"] == "provider")


def test_metrics_failure_does_not_change_provider_result(tmp_path, monkeypatch):
    folder(tmp_path)
    import pqrs_claro.performance_metrics as module

    def unavailable(*args, **kwargs):
        raise OSError()

    monkeypatch.setattr(module.sqlite3, "connect", unavailable)
    with operation("draft", root=tmp_path, case_id="case"):
        assert provider_call("draft.write", reply).status == "completed"


def test_metrics_do_not_recreate_deleted_case_or_accept_path_traversal(tmp_path):
    with operation("draft", root=tmp_path, case_id="absent"):
        provider_call("draft.write", reply)
    assert not (tmp_path / "files").exists()
    with pytest.raises(ValueError):
        metrics_path(tmp_path, "../outside")
    assert read_metrics(tmp_path, "absent")["estimated_cost_usd"] is None


def test_real_sdk_retry_transport_is_counted_without_network(tmp_path):
    folder(tmp_path)
    attempts = []

    def respond(request):
        attempts.append(True)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "1"},
                                  json={"error": {"message": "retry"}})
        return httpx.Response(200, json={
            "id": "resp-test", "object": "response", "created_at": 1,
            "model": "test-model", "status": "completed", "output": [],
            "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13,
                      "input_tokens_details": {"cached_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 0}},
        })

    client = OpenAI(api_key="test-only", max_retries=1,
                    http_client=metrics_http_client(transport=httpx.MockTransport(respond)))
    try:
        with operation("draft", root=tmp_path, case_id="case"):
            provider_call("draft.write", client.responses.create, model="test-model", input="test")
    finally:
        client.close()
    data = read_metrics(tmp_path, "case")
    assert len(attempts) == 2
    assert data["observed_http_retries"] == 1
    assert data["calls_without_attempt_count"] == 0


def test_provider_call_outside_case_does_not_create_metrics(tmp_path):
    assert provider_call("draft.write", reply).status == "completed"
    assert not list(tmp_path.iterdir())


def test_redirect_is_not_counted_as_an_sdk_retry(tmp_path):
    folder(tmp_path)

    def redirected(**kwargs):
        for retry in ("0", "0", "1"):
            _request_hook(SimpleNamespace(headers={"x-stainless-retry-count": retry}))
        return reply()

    with operation("draft", root=tmp_path, case_id="case"):
        provider_call("draft.write", redirected)
    data = read_metrics(tmp_path, "case")
    assert data["events"][0]["http_attempts"] == 3
    assert data["observed_http_retries"] == 1
