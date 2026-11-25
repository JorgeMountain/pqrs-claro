"""Protect evaluation validity without opening the library or calling a reader."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from pqrs_claro.request_intent import classify_request_intent

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("check_full_library_retrieval")


@pytest.fixture
def inputs():
    content = json.loads(
        (ROOT / "tests/fixtures/full_library_retrieval_content.json").read_text(encoding="utf-8")
    )
    scope = {"case_id": "fictional-evaluation", "allowed_collection_ids": ["fictional-library"]}
    saved = {}
    for identifier in ("P2", "P4"):
        request = {"id": identifier, "description": "Explique el contenido de la guía."}
        request["request_intent"] = classify_request_intent(request)
        saved[identifier] = request
    return content, scope, saved


def test_fictional_reader_requests_have_production_intent_without_inheriting_delivery(
    harness, inputs
):
    requests = harness.fixture_requests(*inputs)

    assert requests
    assert all("request_intent" in request for request in requests.values())
    assert requests["FL-ACT-P3"]["request_intent"]["document_delivery_requested"] is True
    assert requests["FL-ACT-P1"]["request_intent"]["document_delivery_requested"] is False
    assert requests["FL-ACT-P2"]["request_intent"]["document_delivery_requested"] is False


def test_answer_key_metadata_cannot_enter_or_change_reader_requests(harness, inputs):
    content, scope, saved = inputs
    expected = harness.fixture_requests(content, scope, saved)
    polluted = deepcopy(content)
    oracle = {"required_points": ["ORACLE-ANSWER-DO-NOT-SEND"], "expected_source_id": "gold-only"}
    polluted["evaluation"] = oracle
    for fixture in polluted["cases"]:
        fixture["evaluation"] = oracle
        for question in fixture["questions"]:
            question["evaluation"] = oracle

    actual = harness.fixture_requests(polluted, scope, saved)

    assert actual == expected
    assert "ORACLE-ANSWER-DO-NOT-SEND" not in json.dumps(actual)
