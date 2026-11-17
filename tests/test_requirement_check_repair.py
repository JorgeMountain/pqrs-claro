"""One bounded structural retry; never rewrite content or manufacture coverage."""

import json
from copy import deepcopy

import pytest
from test_draft_engine import engine, finding, inquiry, support

from pqrs_claro.request_requirements import build_requirements


@pytest.mark.parametrize("repaired", [False, True])
def test_draft_check_retries_invalid_checklist_once_with_identical_evidence(repaired):
    request = inquiry()
    request["request_requirements"] = build_requirements(request)
    source = support()
    plan = {"objective": "Responder con atribución al oficio.", "points": [{
        "description": "Describir la respuesta conservada.",
        "cited_chunk_ids": [source["chunk_id"]],
    }]}
    draft = {"status": "needs_review", "paragraphs": [{
        "text": "Según el oficio de 2024, el comité informó que aprobó la plaza de prácticas.",
        "cited_chunk_ids": [source["chunk_id"]],
    }], "pending": []}
    before = deepcopy(draft)
    invalid = {"status": "passed", "issues": [], "requirement_checks": []}
    valid = {**invalid, "requirement_checks": [{
        "requirement_id": "R1", "status": "answered", "paragraph_indexes": [0],
        "pending_indexes": [], "explanation": "El párrafo responde con atribución literal.",
    }]}
    worker, calls = engine(invalid, valid if repaired else invalid)
    result = worker.check(request, finding(missing=[]), plan, draft)
    assert len(calls) == 2
    assert result["status"] == ("passed" if repaired else "needs_changes")
    assert draft == before
    first, second = [json.loads(call["input"]) for call in calls]
    retry = second.pop("requirement_check_repair")
    assert first == second
    assert retry["errors"][0]["code"] == "coverage_review_incomplete"
    assert any(c["code"] == "requirement_check_repair" for c in result["local_checks"])


def test_semantically_omitted_component_is_reported_without_retrying_to_make_it_pass():
    request = inquiry()
    request["request_requirements"] = build_requirements(request)
    source = support()
    proposed = {"status": "needs_changes", "issues": [], "requirement_checks": [{
        "requirement_id": "R1", "status": "omitted", "paragraph_indexes": [],
        "pending_indexes": [], "explanation": "Falta una parte de lo preguntado.",
    }]}
    worker, calls = engine(proposed)
    result = worker.check(request, finding(missing=[]), {"objective": "Responder.",
        "points": [{"description": "Contenido atribuido.",
                    "cited_chunk_ids": [source["chunk_id"]]}]},
        {"status": "needs_review", "paragraphs": [{
            "text": "Según el oficio de 2024, el comité informó que aprobó la plaza de prácticas.",
            "cited_chunk_ids": [source["chunk_id"]]}], "pending": []})
    assert len(calls) == 1 and result["status"] == "needs_changes"
    assert any(i["code"] == "request_component_omitted" for i in result["issues"])
