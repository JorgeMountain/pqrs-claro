"""Future execution is tracked separately from reviewed, source-backed content."""

from copy import deepcopy

import pytest
from test_delivery_contract import supported_fixture
from test_request_trace import fixture

from pqrs_claro.evidence_contract import apply_evidence_contract, request_scope, source_version
from pqrs_claro.request_trace import build_request_trace, trace_repair_issues


def complete_with_future_action():
    request, finding, plan, draft, checks = fixture()
    text = "Indique el plazo y su fundamento y compruebe su aplicación cuando venza"
    request["request_requirements"][0]["text"] = text
    request["description"] = text + "; explique la renovación."
    source = finding["supports"][0]
    action = {
        "check_key": "check-future-loan", "description": "Comprobar el plazo cuando venza.",
        "affected_claim": "La comprobación futura del plazo.", "reason_code": "requested_followup",
        "basis": "content_gap", "stage": "fulfillment", "blocks_approval": False,
        "state": "confirmation_pending", "resolution": {"status": "open"},
        "request_ids": [request["id"]], "scope_key": request_scope(request),
        "linked_chunk_ids": [source["chunk_id"]], "source_versions": [source_version(source)],
    }
    finding["checks"] = [deepcopy(action)]
    draft["pending"].append(action)
    finding["sufficiency"]["evaluated_gaps"] = [{
        "stage": "fulfillment", "description": action["description"],
        "affected_claim": action["affected_claim"], "basis": action["basis"],
        "source_chunk_ids": action["linked_chunk_ids"],
    }]
    finding["sufficiency"]["requirement_checks"][0].update(
        status="pending", missing_indexes=[0]
    )
    draft["paragraphs"][0]["text"] += " El plazo obedece a la rotación del material."
    checks["unit_checks"][1].update(status="answered", paragraph_indexes=[0])
    checks["requirement_checks"][0].update(status="pending", pending_indexes=[1])
    return request, finding, plan, draft, checks


def test_complete_current_answer_keeps_future_execution_separate_and_inputs_unchanged():
    args = complete_with_future_action()
    before = deepcopy(args)
    trace = build_request_trace(*args)
    row = trace["requirements"][0]
    assert row["status"] == "reviewed_answer"
    assert row["paragraph_indexes"] == [0]
    assert row["pending_check_keys"] == []
    assert row["fulfillment_check_keys"] == ["check-future-loan"]
    assert row["omissions"] == []
    assert trace_repair_issues(trace, args[3]) == []
    assert args == before


def test_mixed_evidence_gap_and_future_action_keep_both_identities_independent():
    args = complete_with_future_action()
    args[4]["requirement_checks"][0]["pending_indexes"] = [0, 1]
    row = build_request_trace(*args)["requirements"][0]
    assert row["status"] == "pending"
    assert row["pending_check_keys"] == ["check-provenance-fictitious"]
    assert row["fulfillment_check_keys"] == ["check-future-loan"]


def test_supported_copy_keeps_exact_delivery_key_without_inventing_missing_index():
    request, finding = supported_fixture()
    finding = apply_evidence_contract(request, finding)
    source = finding["supports"][0]
    plan = {"coverage_units": []}
    draft = {"paragraphs": [{"text": source["quote"], "cited_chunk_ids": [source["chunk_id"]]}],
             "pending": deepcopy(finding["actions"])}
    checks = {"requirement_checks": [{
        "requirement_id": "R1", "status": "answered", "paragraph_indexes": [0],
        "pending_indexes": [], "explanation": "Localización respondida; entrega pendiente.",
    }], "unit_checks": []}
    before = deepcopy(finding)
    row = build_request_trace(request, finding, plan, draft, checks)["requirements"][0]
    assert row["status"] == "not_evaluated"
    assert row["pending_check_keys"] == []
    assert row["fulfillment_check_keys"] == [draft["pending"][0]["check_key"]]
    assert finding == before
    assert finding["sufficiency"]["requirement_checks"][0]["missing_indexes"] == []
    assert row["omissions"] == []


@pytest.mark.parametrize("missing", ["unit", "requirement", "inventory", "unit_review", "citation"])
def test_future_action_cannot_cover_missing_content_or_missing_inventory(missing):
    args = complete_with_future_action()
    if missing == "unit":
        args[4]["unit_checks"][1].update(status="omitted", paragraph_indexes=[])
    elif missing == "requirement":
        args[4]["requirement_checks"][0].update(status="omitted", pending_indexes=[])
    elif missing == "inventory":
        args[2]["coverage_units"] = []
    elif missing == "unit_review":
        args[4]["unit_checks"] = []
    elif missing == "citation":
        args[3]["paragraphs"][0]["cited_chunk_ids"] = []
    row = build_request_trace(*args)["requirements"][0]
    assert row["status"] != "reviewed_answer"
    assert row["fulfillment_check_keys"] == ["check-future-loan"]
    assert row["pending_check_keys"] == []


@pytest.mark.parametrize("invalid", [
    "closed_registry", "closed_draft", "version", "permission", "scope", "purpose",
    "other_requirement", "unknown_key", "missing_registration",
])
def test_invalid_or_closed_future_action_cannot_inherit_content_review(invalid):
    args = complete_with_future_action()
    request, finding, _, draft, _ = args
    original, action = finding["checks"][0], draft["pending"][1]
    if invalid == "closed_registry":
        original["resolution"]["status"] = "resolved"
    elif invalid == "closed_draft":
        action["resolution"]["status"] = "resolved"
    elif invalid == "version":
        finding["supports"][0]["version"] = 2
    elif invalid == "permission":
        request["allowed_collection_ids"] = []
    elif invalid == "scope":
        request["description"] = "Indique sólo el plazo."
    elif invalid == "purpose":
        action["description"] = "Entregar el informe de otra actuación."
    elif invalid == "other_requirement":
        original["requirement_ids"] = ["R2"]
    elif invalid == "unknown_key":
        action["check_key"] = "another-task"
    elif invalid == "missing_registration":
        finding["checks"] = []
    before = deepcopy(args)
    row = build_request_trace(*args)["requirements"][0]
    assert row["status"] == "not_evaluated"
    assert row["fulfillment_check_keys"] == []
    assert args == before


@pytest.mark.parametrize("status", ["omitted", "out_of_scope", "pending", "missing"])
def test_all_material_details_must_be_answered_before_reviewing_content(status):
    args = complete_with_future_action()
    unit = args[2]["coverage_units"][0]
    source = args[1]["supports"][0]
    citation = {"chunk_id": source["chunk_id"],
                "quote": "Decide la Coordinación de Biblioteca."}
    unit.update(details_version=1, no_details_reason="", details=[{
        "id": "U1-K1", "kind": "authority", "citation": citation,
        "members": [{"chunk_id": source["chunk_id"], "quote": "Coordinación de Biblioteca"}],
        "reason": "La autoridad forma parte del dato pedido.",
    }])
    if status != "missing":
        args[4]["detail_checks"] = [{
            "detail_id": "U1-K1", "status": status, "evidence": [],
            "pending_indexes": [1] if status == "pending" else [],
            "explanation": "Revisión parcial del detalle.",
        }]
    row = build_request_trace(*args)["requirements"][0]
    assert row["status"] != "reviewed_answer"
    assert row["fulfillment_check_keys"] == ["check-future-loan"]
