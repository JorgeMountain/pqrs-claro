# ruff: noqa: F811
"""Provider failures expose useful categories without persisting exception contents."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError
from test_app import analyze, app_client, pdf_bytes, upload  # noqa: F401

from pqrs_claro.identification import OpenAIIdentifier
from pqrs_claro.models import Page
from pqrs_claro.provider_errors import IdentificationProviderError


@pytest.mark.parametrize(
    "status,category",
    [
        (401, "authentication"),
        (403, "permission"),
        (429, "rate_limit_or_quota"),
        (503, "provider_unavailable"),
        (400, "provider_request"),
    ],
)
def test_status_categories_never_expose_raw_provider_details(status, category):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.test"))
    exc = APIStatusError(
        "PRIVATE-CONTENT secret-key", response=response, body={"private": "PRIVATE-CONTENT"}
    )
    identifier = OpenAIIdentifier("test-not-real", "test")

    def fail(**kwargs):
        raise exc

    identifier.client = SimpleNamespace(responses=SimpleNamespace(parse=fail))
    with pytest.raises(IdentificationProviderError) as failure:
        identifier.identify(
            [Page(number=1, text="Petición ficticia", method="native", needs_review=False)]
        )
    assert failure.value.diagnostic["category"] == category
    assert failure.value.diagnostic["http_status"] == status
    assert "PRIVATE-CONTENT" not in str(failure.value) + json.dumps(failure.value.diagnostic)


@pytest.mark.parametrize(
    "error,category", [(APIConnectionError, "connection"), (APITimeoutError, "timeout")]
)
def test_connection_categories(error, category):
    exc = error(request=httpx.Request("POST", "https://example.test"))
    assert IdentificationProviderError(exc).diagnostic["category"] == category


def test_diagnostic_persisted_and_cleared_on_retry(app_client, pdf_bytes):
    app, client, identifier, _ = app_client
    case = upload(client, pdf_bytes)
    original = identifier.identify

    def fail(pages):
        raise IdentificationProviderError(
            APIConnectionError(request=httpx.Request("POST", "https://example.test"))
        )

    identifier.identify = fail
    app.state.service.run(case["id"])
    failed = client.get(f"/api/cases/{case['id']}").json()
    assert failed["status"] == "error"
    assert failed["error_diagnostic"]["category"] == "connection"
    assert failed["error_diagnostic"]["at"]
    identifier.identify = original
    recovered = analyze(client, failed)
    assert recovered["error_diagnostic"] is None
    assert recovered["error"] is None
