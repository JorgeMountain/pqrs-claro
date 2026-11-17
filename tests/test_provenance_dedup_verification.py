"""Reuse the audited catalog obligation only after its actual human review.

These fictional controls exercise the real application validator without API calls
or modifying any live documents or human verification records.
"""

from copy import deepcopy

import pytest

from pqrs_claro.evidence_contract import apply_evidence_contract, normalize_pending


@pytest.fixture
def scenario():
    source = {
        "source_id": "fictional-circular-763", "document_id": "fictional-document-763",
        "version": 1, "sha256": "a" * 64, "extraction_revision": 1,
        "title": "Circular 763 de 2025", "category": "institutional_norm",
        "extraction_status": "ready", "chunk_id": "fictional-circular-763:1:1:2",
        "quote": "CIRCULAR 763 DE 2025\nPréstamo de telescopios escolares.",
    }
    request = {
        "id": "AUTH-P1", "case_id": "fictional-auth-case", "title": "Autenticidad",
        "description": "Confirme la autenticidad del documento conservado.",
    }
    generic = {
        "kind": "clarification", "reason_code": "provenance", "basis": "metadata_only",
        "catalog_check": "review_status",
        "description": "Revisar la procedencia y el contenido de «Circular 763 de 2025».",
        "linked_source_ids": [source["source_id"]],
        "linked_chunk_ids": [source["chunk_id"]],
    }
    specific = {
        "kind": "clarification", "reason_code": "provenance", "basis": "contradiction",
        "description": "Cotejar la autenticidad del documento con el original institucional.",
        "affected_claim": "La copia conservada es un documento auténtico.",
        "why_unresolved": "La identificación del ejemplar no coincide con el registro.",
        "linked_source_ids": [source["source_id"]],
        "linked_chunk_ids": [source["chunk_id"]],
    }
    finding = {
        "request_id": request["id"], "status": "needs_evidence", "supports": [source],
        "missing": [generic, specific], "warnings": [],
    }
    return request, source, generic, specific, finding


def review(request, source, check):
    record = {
        "id": "fictional-human-review", "kind": "human_review",
        "fact": "Se cotejó la autenticidad del ejemplar.",
        "basis": "Cotejo del documento con el original institucional conservado.",
        "recorded_by": "Gestor ficticio", "recorded_at": "2026-11-17T12:00:00Z",
        "recording_method": "human_form", "case_id": request["case_id"],
        "source_id": source["source_id"], "document_id": source["document_id"],
        "version": source["version"], "source_sha256": source["sha256"],
        "extraction_revision": source["extraction_revision"],
        "passage": {
            "chunk_id": source["chunk_id"], "page": 1, "line_start": 1, "line_end": 2,
            "quote": source["quote"],
        },
    }
    return {
        "id": "fictional-review-application", "verification_id": record["id"],
        "record": record, "case_id": request["case_id"],
        "check_key": check["check_key"], "request_ids": [request["id"]],
        "scope_key": check["scope_key"], "check_reason": check["reason_code"],
        "basis": record["basis"], "recorded_by": record["recorded_by"],
    }


def reviewed_finding(scenario):
    request, source, _, _, raw = scenario
    finding = apply_evidence_contract(request, raw)
    assert len(finding["checks"]) == 1
    application = review(request, source, finding["checks"][0])
    reviewed = apply_evidence_contract(request, finding, applications=[application])
    assert reviewed["checks"][0]["resolution"]["status"] == "resolved"
    assert reviewed["missing"] == []
    return reviewed, application


def test_real_human_review_prevents_reintroducing_its_audited_catalog_obligation(scenario):
    request, _, generic, _, _ = scenario
    reviewed, application = reviewed_finding(scenario)
    repeated = {key: value for key, value in generic.items() if key != "catalog_check"}
    before = deepcopy(reviewed)

    assert normalize_pending(request, reviewed, [repeated]) == []
    assert reviewed == before
    assert reviewed["gap_decisions"][0]["covering_check_keys"] == [application["check_key"]]
    assert reviewed["gap_decisions"][0]["original"]["resolution"] == {"status": "open"}


def test_real_review_without_prior_absorption_cannot_close_catalog_obligation(scenario):
    request, _, generic, _, _ = scenario
    reviewed, _ = reviewed_finding(scenario)
    reviewed.pop("gap_decisions")

    pending = normalize_pending(request, reviewed, [generic])
    assert len(pending) == 1
    assert pending[0]["description"] == generic["description"]
    assert pending[0]["resolution"] == {"status": "open"}


@pytest.mark.parametrize("missing_reference", ["application_id", "verification_id"])
def test_resolved_status_without_review_references_cannot_absorb_catalog_task(
    scenario, missing_reference,
):
    request, _, generic, _, _ = scenario
    reviewed, _ = reviewed_finding(scenario)
    reviewed["checks"][0]["resolution"].pop(missing_reference)

    pending = normalize_pending(request, reviewed, [generic])
    assert len(pending) == 1
    assert pending[0]["resolution"] == {"status": "open"}


@pytest.mark.parametrize("change", [
    {"id": "AUTH-P2"},
    {"context": {"purpose": "Otra aplicación del documento"}},
])
def test_prior_review_cannot_absorb_catalog_task_in_another_request_scope(scenario, change):
    request, _, generic, _, _ = scenario
    reviewed, _ = reviewed_finding(scenario)

    pending = normalize_pending({**request, **change}, reviewed, [generic])
    assert len(pending) == 1
    assert pending[0]["resolution"] == {"status": "open"}


@pytest.mark.parametrize("change", [
    {"version": 2},
    {"sha256": "b" * 64},
    {"extraction_revision": 2},
])
def test_prior_review_cannot_absorb_catalog_task_for_changed_source(scenario, change):
    request, source, generic, _, _ = scenario
    reviewed, _ = reviewed_finding(scenario)
    reviewed["supports"] = [{**source, **change}]

    pending = normalize_pending(request, reviewed, [generic])
    assert len(pending) == 1
    assert pending[0]["resolution"] == {"status": "open"}


@pytest.mark.parametrize("changed_field, changed_value", [
    ("affected_claim", "El archivo procede del registro institucional de ingreso."),
    ("why_unresolved", "La cadena de custodia contiene un remitente contradictorio."),
])
def test_approval_of_one_material_control_does_not_close_a_new_control(
    scenario, changed_field, changed_value,
):
    request, _, generic, specific, raw = scenario
    reviewed, application = reviewed_finding(scenario)
    new_specific = {**specific, changed_field: changed_value}
    fresh = {**raw, "missing": [generic, new_specific]}

    result = apply_evidence_contract(request, fresh, applications=[application])
    material = next(item for item in result["missing"] if item["basis"] == "contradiction")
    assert material["check_key"] != reviewed["checks"][0]["check_key"]
    assert material["resolution"] == {"status": "open"}
    assert material[changed_field] == changed_value
    assert result["supports"] == raw["supports"]


def test_review_of_one_material_control_keeps_another_existing_control_open(scenario):
    request, source, generic, specific, raw = scenario
    second = {
        **specific, "description": "Cotejar la procedencia del archivo y su cadena de custodia.",
        "affected_claim": "La procedencia del documento es institucional.",
        "why_unresolved": "El registro de ingreso identifica otro remitente.",
    }
    finding = apply_evidence_contract(request, {**raw, "missing": [generic, specific, second]})
    assert len(finding["checks"]) == 2
    first = next(item for item in finding["checks"]
                 if item["description"] == specific["description"])

    result = apply_evidence_contract(
        request, finding, applications=[review(request, source, first)]
    )
    assert len(result["missing"]) == 1
    assert result["missing"][0]["description"] == second["description"]
    assert result["missing"][0]["resolution"] == {"status": "open"}
    assert normalize_pending(request, result, [generic]) == result["missing"]
