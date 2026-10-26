import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from pqrs_claro import performance_metrics as metrics


def case_folder(root, case_id="case"):
    (root / "files" / case_id).mkdir(parents=True)


def events(root, case_id="case"):
    return [event for event in metrics.read_metrics(root, case_id)["events"]
            if event["kind"] == "provider"]


def record(**kwargs):
    metrics.record_jev_attempt(model="jev-1.14.0", seconds=0.12345678,
                               status="ok", **kwargs)


def test_jev_attempt_keeps_only_usage_and_inherits_request_context(tmp_path):
    case_folder(tmp_path)
    with metrics.operation("identification", root=tmp_path, case_id="case"):
        with metrics.operation("identification.classify", request_id="request-1"):
            record(http_status=200, usage={
                "input_tokens": 1000, "output_tokens": 20,
                "input": "PRIVATE PROMPT", "answer": "PRIVATE RESPONSE",
                "api_key": "secret-token", "url": "https://private.invalid/",
            })
    data = metrics.read_metrics(tmp_path, "case")
    event, = events(tmp_path)
    assert event["provider"] == "typesafe"
    assert event["model"] == "jev-1.14.0"
    assert event["operation"] == "identification.classify"
    assert event["request_id"] == "request-1"
    assert event["stage"] == "identification"
    assert event["seconds"] == 0.123457
    assert event["status"] == "ok" and event["http_status"] == 200
    assert event["http_attempts"] == 1 and event["http_retries"] == 0
    assert event["input_tokens"] == 1000 and event["output_tokens"] == 20
    assert event["cached_input_tokens"] is None
    assert event["reasoning_tokens"] is None
    assert data["instrumented_providers"] == ["openai", "typesafe"]
    raw = json.dumps(data)
    assert all(value not in raw for value in (
        "PRIVATE PROMPT", "PRIVATE RESPONSE", "secret-token", "https://private.invalid/"))


def test_jev_retry_preserves_failed_attempt_and_unknown_cost(tmp_path):
    case_folder(tmp_path)
    with metrics.operation("identification", root=tmp_path, case_id="case",
                           request_id="request-1"):
        metrics.record_jev_attempt(model="jev-1.14.0", seconds=0.05,
                                   status="transport_error", error_type="ConnectError")
        record(retry=True, http_status=200, usage={"input_tokens": 10, "output_tokens": 1})
    data = metrics.read_metrics(tmp_path, "case")
    first, second = events(tmp_path)
    assert first["error_type"] == "ConnectError" and first["http_status"] is None
    assert first["input_tokens"] is None and first["output_tokens"] is None
    assert second["error_type"] is None
    assert [event["http_attempts"] for event in (first, second)] == [1, 1]
    assert [event["http_retries"] for event in (first, second)] == [0, 1]
    assert data["provider_calls"] == 2 and data["observed_http_retries"] == 1
    assert data["calls_without_usage"] == 1
    assert data["estimated_cost_usd"] is None


@pytest.mark.parametrize("status, code", [("http_error", 429), ("invalid_response", 200)])
def test_jev_http_or_schema_failure_records_only_error_metadata(tmp_path, status, code):
    case_folder(tmp_path)
    with metrics.operation("identification", root=tmp_path, case_id="case"):
        metrics.record_jev_attempt(model="jev-1.14.0", seconds=0.1, status=status,
                                   http_status=code, error_type="ValueError")
    event, = events(tmp_path)
    assert event["status"] == status and event["http_status"] == code
    assert event["error_type"] == "ValueError"
    assert event["input_tokens"] is None


@pytest.mark.parametrize("cached_rate, expected", [(1, 0.00104), (0.25, None)])
def test_jev_missing_cache_is_priced_only_if_cached_and_regular_rates_match(
        tmp_path, cached_rate, expected):
    case_folder(tmp_path)
    (tmp_path / "metrics-pricing.json").write_text(json.dumps({"jev-1.14.0": {
        "input_per_million_usd": 1, "cached_input_per_million_usd": cached_rate,
        "output_per_million_usd": 2,
    }}), encoding="utf-8")
    with metrics.operation("identification", root=tmp_path, case_id="case"):
        record(usage={"input_tokens": 1000, "output_tokens": 20})
    data = metrics.read_metrics(tmp_path, "case")
    assert events(tmp_path)[0]["cached_input_tokens"] is None
    if expected is None:
        assert data["estimated_cost_usd"] is None
    else:
        assert data["estimated_cost_usd"] == pytest.approx(expected)


def test_jev_invalid_usage_and_free_form_error_text_are_not_persisted(tmp_path):
    case_folder(tmp_path)
    with metrics.operation("identification", root=tmp_path, case_id="case"):
        metrics.record_jev_attempt(model="https://private.invalid/", seconds=0.1,
                                   status="PRIVATE RESPONSE", error_type="secret prompt text",
                                   http_status=True, usage={
                                       "input_tokens": True, "output_tokens": "12",
                                       "input_tokens_details": {"cached_tokens": -1},
                                   })
    event, = events(tmp_path)
    assert event["model"] is None and event["error_type"] is None
    assert event["status"] == "unknown" and event["http_status"] is None
    assert all(event[key] is None for key in (
        "input_tokens", "output_tokens", "cached_input_tokens"))
    raw = json.dumps(event)
    assert all(value not in raw for value in (
        "https://private.invalid/", "PRIVATE RESPONSE", "secret prompt text"))


def test_jev_metrics_failure_does_not_interrupt_processing(tmp_path, monkeypatch):
    case_folder(tmp_path)

    def unavailable(*args, **kwargs):
        raise OSError("private provider response")

    monkeypatch.setattr(metrics.sqlite3, "connect", unavailable)
    with metrics.operation("identification", root=tmp_path, case_id="case"):
        assert record(usage={"input_tokens": 1, "output_tokens": 1}) is None


def test_jev_parallel_requests_keep_separate_contexts(tmp_path):
    case_folder(tmp_path)

    def classify(ident):
        with metrics.operation("identification.classify", request_id=ident):
            record(usage={"input_tokens": 1, "output_tokens": 1})

    with metrics.operation("identification", root=tmp_path, case_id="case"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [metrics.submit_context(pool, classify, ident) for ident in ("one", "two")]
            for future in futures:
                future.result()
    assert {event["request_id"] for event in events(tmp_path)} == {"one", "two"}


def test_jev_without_scope_or_deleted_case_does_not_create_metrics(tmp_path):
    record(usage={"input_tokens": 1, "output_tokens": 1})
    with metrics.operation("identification", root=tmp_path, case_id="missing"):
        record(usage={"input_tokens": 1, "output_tokens": 1})
    assert not list(tmp_path.iterdir())
