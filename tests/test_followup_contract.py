"""Future tasks enter the shared registry once and never become missing evidence."""

from copy import deepcopy

from test_requested_followup import fixture

from pqrs_claro.evidence_contract import (
    apply_evidence_contract,
    normalize_pending,
    pending_registry,
)


def test_explicit_followup_replaces_only_the_generated_generic_supervision():
    request, finding = fixture("Verifiquen cuando se publique la decisión final.")
    result = apply_evidence_contract(request, finding)
    assert result["missing"] == []
    assert len(result["actions"]) == 1
    action = result["actions"][0]
    assert action["reason_code"] == "requested_followup"
    assert action["stage"] == "fulfillment" and action["blocks_approval"] is False
    before = deepcopy(result)
    assert pending_registry(request, result) == result["checks"]
    assert normalize_pending(request, result, []) == result["checks"]
    assert result == before


def test_resolved_followup_does_not_reappear_as_generic_supervision():
    request, finding = fixture("Verifiquen cuando se publique la decisión final.")
    result = apply_evidence_contract(request, finding)
    action = result["checks"][0]
    action["resolution"] = {
        "status": "resolved",
        "action": "fulfilled",
        "by": "Gestora ficticia",
        "note": "Seguimiento realizado.",
    }
    result["actions"] = []
    before = deepcopy(result)
    assert pending_registry(request, result) == [action]
    assert normalize_pending(request, result, []) == []
    assert result == before


def test_future_announcement_without_followup_request_does_not_create_a_task():
    request, finding = fixture("Informen cuándo se publicará la decisión final.")
    result = apply_evidence_contract(request, finding)
    assert result["checks"] == []
    assert result["missing"] == result["actions"] == []


def test_pending_question_creates_one_specific_nonblocking_followup():
    request, finding = fixture()
    result = apply_evidence_contract(request, finding)
    assert len(result["checks"]) == 1
    assert result["checks"][0]["reason_code"] == "requested_followup"
    assert result["checks"][0]["blocks_approval"] is False
    assert result["missing"] == []


def test_another_literal_event_in_same_chunk_cannot_inherit_closed_followup():
    request, finding = fixture()
    other_quote = "La decisión sobre otra jornada se publicará el martes."
    finding["supports"][0]["quote"] += " " + other_quote
    result = apply_evidence_contract(request, finding)
    old = result["checks"][0]
    old["resolution"] = {"status": "resolved", "action": "fulfilled"}
    result["actions"] = []
    result["sufficiency"]["coverage"][0]["citations"][0]["quote"] = other_quote

    controls = pending_registry(request, result)
    assert len(controls) == 2
    assert len({item["check_key"] for item in controls}) == 2
    assert controls[0] == old
    current = normalize_pending(request, result, [])
    assert len(current) == 1
    assert current[0]["resolution"] == {"status": "open"}
    assert current[0]["followup_passages"][0]["quote"] == other_quote
    assert current[0]["source_versions"] == old["source_versions"]
    assert current[0]["affected_claim"] == old["affected_claim"]
