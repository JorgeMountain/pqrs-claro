"""Local, content-free performance and provider usage events, scoped to a case.

No prompts, replies, credentials, URLs or exception messages are persisted.
Unknown usage/pricing remains null. Metrics must never stop case processing.
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import math
import re
import sqlite3
from contextlib import closing, contextmanager
from contextvars import ContextVar, copy_context
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from time import perf_counter
from uuid import uuid4

_scope = ContextVar("pqrs_metrics_scope", default=None)
_attempts = ContextVar("pqrs_metrics_attempts", default=None)
logger = logging.getLogger(__name__)


def metrics_path(root, case_id):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", case_id):
        raise ValueError("Identificador de expediente inválido")
    base = (Path(root) / "files").resolve()
    folder = (base / case_id).resolve()
    if folder.parent != base:
        raise ValueError("Carpeta de métricas fuera del expediente")
    return folder / "performance.sqlite"


def _save(scope, event):
    if scope is None:
        return
    try:
        path = metrics_path(scope["root"], scope["case_id"])
        # A deleted case must not be recreated by telemetry.
        if not path.parent.is_dir():
            return
        with closing(sqlite3.connect(path, timeout=2)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events "
                "(id INTEGER PRIMARY KEY, body TEXT NOT NULL)"
            )
            connection.execute("INSERT INTO events(body) VALUES (?)", (json.dumps({
                "at": datetime.now(timezone.utc).isoformat(),
                "run_id": scope["run_id"], "stage": scope["stage"],
                "request_id": scope.get("request_id"), **event,
            }),))
    except Exception:
        # Deliberately omit exception text: provider messages can contain input.
        logger.warning("No se pudo guardar una medición de rendimiento (%s).", event["kind"])


@contextmanager
def operation(name, *, root=None, case_id=None, request_id=None):
    parent = _scope.get()
    scope = dict(parent) if parent else None
    if root is not None and case_id is not None:
        scope = dict(root=Path(root), case_id=case_id, run_id=uuid4().hex, stage=name)
    if scope is not None and request_id is not None:
        scope["request_id"] = request_id
    token = _scope.set(scope)
    started = perf_counter()
    status = "returned"
    try:
        yield
    except BaseException:
        status = "raised"
        raise
    finally:
        _save(scope, {"kind": "local", "operation": name, "status": status,
                      "seconds": round(perf_counter() - started, 6)})
        _scope.reset(token)


def track_case(stage, argument):
    """Establish context inside workers, not in the launching HTTP request."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(self, *args, **kwargs):
            settings = getattr(self, "settings", None)
            if settings is None:
                return function(self, *args, **kwargs)
            item = signature.bind(self, *args, **kwargs).arguments[argument]
            case_id = item if isinstance(item, str) else item.get("case_id", item.get("id"))
            request_id = item.get("request_id") if isinstance(item, dict) else None
            with operation(stage, root=settings.data_dir, case_id=case_id,
                           request_id=request_id):
                return function(self, *args, **kwargs)
        return wrapped
    return decorate


def submit_context(pool, function, *args, **kwargs):
    """Each concurrent task owns a distinct Context; never share Context.run."""
    return pool.submit(copy_context().run, function, *args, **kwargs)


def _request_hook(request):
    counter = _attempts.get()
    if counter is not None:
        counter["count"] += 1
        # Redirects are HTTP requests too, but are not SDK retries.
        retry_count = request.headers.get("x-stainless-retry-count", "")
        if retry_count.isdigit():
            counter["retries"] = max(counter["retries"] or 0, int(retry_count))


def metrics_http_client(**kwargs):
    from openai import DefaultHttpxClient
    return DefaultHttpxClient(event_hooks={"request": [_request_hook]}, **kwargs)


def _get(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def provider_call(name, function, **kwargs):
    scope = _scope.get()
    if scope is None:
        return function(**kwargs)
    started = perf_counter()
    counter = {"count": 0, "retries": None}
    token = _attempts.set(counter)
    response = None
    error_type = None
    try:
        response = function(**kwargs)
        return response
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        usage = _get(response, "usage")
        _save(scope, {
            "kind": "provider", "provider": "openai", "operation": name,
            "model": _get(response, "model") or kwargs.get("model"),
            "status": "error" if error_type else (_get(response, "status") or "returned"),
            "error_type": error_type,
            "seconds": round(perf_counter() - started, 6),
            "http_attempts": counter["count"] or None,
            "http_retries": counter["retries"],
            "input_tokens": _count(_get(usage, "input_tokens")),
            "output_tokens": _count(_get(usage, "output_tokens")),
            "cached_input_tokens": _count(_get(
                _get(usage, "input_tokens_details"), "cached_tokens")),
            "reasoning_tokens": _count(_get(
                _get(usage, "output_tokens_details"), "reasoning_tokens")),
        })
        _attempts.reset(token)


def record_jev_attempt(*, model, seconds, status, error_type=None, usage=None,
                       retry=False, http_status=None):
    """Record one TypeSafe HTTP attempt in the current case/request context.

    Call once per attempt, including failed attempts and retries. Only explicit
    numeric usage is retained; absent usage/cache stays unknown. The caller
    supplies an exception class name, never its message or the HTTP body.
    """
    scope = _scope.get()
    if scope is None:
        return
    try:
        if (not isinstance(seconds, (int, float)) or isinstance(seconds, bool)
                or not math.isfinite(seconds) or seconds < 0):
            return
        # Do not allow free-form status/error strings to become content logs.
        safe_status = status if status in {
            "ok", "http_error", "transport_error", "invalid_response",
        } else "unknown"
        safe_error = (error_type if isinstance(error_type, str) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,127}", error_type) else None)
        safe_model = (model if isinstance(model, str) and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model) else None)
        code = _count(http_status)
        _save(scope, {
            "kind": "provider", "provider": "typesafe",
            "operation": "identification.classify", "model": safe_model,
            "status": safe_status, "error_type": safe_error,
            "http_status": code if code is not None and 100 <= code <= 599 else None,
            "seconds": round(seconds, 6), "http_attempts": 1,
            "http_retries": 1 if retry is True or type(retry) is int and retry == 1 else 0,
            "input_tokens": _count(_get(usage, "input_tokens")),
            "output_tokens": _count(_get(usage, "output_tokens")),
            "cached_input_tokens": _count(_get(
                _get(usage, "input_tokens_details"), "cached_tokens")),
            "reasoning_tokens": _count(_get(
                _get(usage, "output_tokens_details"), "reasoning_tokens")),
        })
    except Exception:
        # A malformed usage object or telemetry failure must not mask a result.
        logger.warning("No se pudo registrar un intento de clasificación JEV.")


def _cost(event, prices):
    rate = prices.get(event.get("model"))
    if not isinstance(rate, dict):
        return None
    incoming, outgoing, cached = (event.get(k) for k in (
        "input_tokens", "output_tokens", "cached_input_tokens"))
    if incoming is None or outgoing is None:
        return None
    rates = [rate.get(k) for k in ("input_per_million_usd", "output_per_million_usd",
                                 "cached_input_per_million_usd")]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and v >= 0 for v in rates):
        return None
    if cached is None:
        if rates[0] != rates[2]:
            return None
        cached = 0
    if cached > incoming:
        return None
    return ((incoming - cached) * rates[0] + outgoing * rates[1] + cached * rates[2]) / 1e6


def read_metrics(root, case_id):
    path = metrics_path(root, case_id)
    events = []
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            events = [json.loads(row[0]) for row in connection.execute(
                "SELECT body FROM events ORDER BY id")]
    prices = {}
    pricing_status = "not_configured"
    try:
        prices = json.loads((Path(root) / "metrics-pricing.json").read_text(encoding="utf-8"))
        if not isinstance(prices, dict):
            raise ValueError("Invalid pricing")
        pricing_status = "configured"
    except FileNotFoundError:
        pass
    except (ValueError, OSError):
        prices = {}
        pricing_status = "invalid"
    calls = [e for e in events if e["kind"] == "provider"]
    costs = [_cost(e, prices) for e in calls]
    groups = {}
    for event in events:
        key = (event["stage"], event["operation"], event["kind"])
        group = groups.setdefault(key, dict(stage=key[0], operation=key[1], kind=key[2],
                                           calls=0, seconds=0.0))
        group["calls"] += 1
        group["seconds"] = round(group["seconds"] + event["seconds"], 6)
    return {
        "case_id": case_id, "recorded_events": len(events),
        "coverage": "Eventos registrados desde la activación; no reconstruye consumo histórico.",
        "timing_note": "Las operaciones anidadas o paralelas no se suman como duración total.",
        "instrumented_providers": ["openai", "typesafe"],
        "cost_note": "Estimación del consumo reportado, no una factura; tarifas configurables.",
        "pricing_status": pricing_status,
        "provider_calls": len(calls),
        "calls_without_usage": sum(e.get("input_tokens") is None or e.get("output_tokens") is None
                                   for e in calls),
        "recorded_input_tokens": sum(e.get("input_tokens") or 0 for e in calls),
        "recorded_output_tokens": sum(e.get("output_tokens") or 0 for e in calls),
        "observed_http_retries": sum(e.get("http_retries") or 0 for e in calls),
        "calls_without_attempt_count": sum(e.get("http_attempts") is None for e in calls),
        "estimated_cost_usd": (
            round(sum(costs), 8) if calls and all(c is not None for c in costs) else None),
        "priced_calls": sum(c is not None for c in costs),
        "groups": list(groups.values()), "events": events,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    print(json.dumps(read_metrics(args.data_dir, args.case), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
