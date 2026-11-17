"""General application controls: fictitious sources, no provider or live records."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from pqrs_claro.models import DomainError
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection


def fixture():
    request = {"id": "P7", "case_id": "case-new", "title": "Duración de reserva",
               "description": "¿Cuánto dura la reserva según los dos reglamentos? "
               "Si no puede decidirse, explique qué debe contrastarse.",
               "request_requirements": [{"id": "R1", "text": "Duración y contraste requerido"}]}
    sources = [{
        "chunk_id": f"s{i}:1:1:2", "source_id": f"s{i}", "document_id": f"doc{i}",
        "version": 1, "sha256": str(i) * 64, "is_latest": True,
        "title": f"Reglamento de reserva {i}", "filename": f"reglamento_{i}.pdf",
        "category": "institutional_norm", "case_id": None, "validity": "current",
        "review_status": "reviewed", "needs_review": False, "extraction_status": "ready",
        "page": 1, "line_start": 1, "line_end": 2,
        "quote": f"REGLAMENTO {i}\nLa reserva caduca a las {hours} horas de confirmarse.",
    } for i, hours in [(1, 6), (2, 9)]]
    data = {
        "status": "references_found", "summary": "Los textos no fijan cuál regla prevalece.",
        "supports": [{"chunk_id": s["chunk_id"], "role": "rule",
                      "reason": "Se atribuye el plazo a su fuente."} for s in sources],
        "missing": [], "warnings": [], "coverage_complete": True,
        "coverage": [{"aspect": "Duración de reserva", "claim": s["quote"].splitlines()[1],
                      "use": "attributed_content", "explanation": "Mismo objeto y supuesto.",
                      "citations": [{"chunk_id": s["chunk_id"], "quote": s["quote"]}],
                      "application": {"status": "unresolved", "uncertainty_indexes": [0],
                                      "explanation": "No se acredita cuál plazo prevalece."}}
                     for s in sources],
        "requirement_checks": [{"requirement_id": "R1", "status": "supported",
                                "coverage_indexes": [0, 1], "missing_indexes": [],
                                "explanation": "Se explican ambas reglas y la limitación."}],
        "uncertainties": [{"requirement_ids": ["R1"], "coverage_indexes": [0, 1],
                           "basis": "contradiction", "affected_claim": "Plazo aplicable.",
                           "why_unresolved": "Los dos textos regulan el mismo inicio y reserva "
                           "con duraciones incompatibles, sin relación de prevalencia acreditada.",
                           "required_check": "Contrastar el ámbito y la relación de prevalencia "
                           "entre los dos reglamentos antes de aplicar un plazo."}],
    }
    return request, sources, data


def materialize(request, sources, data):
    return OpenAISourceAssessor._materialize(
        _SourceSelection.model_validate(data), request, sources)


def test_explicit_uncertainty_becomes_pending_even_with_complete_answer_and_empty_missing():
    request, sources, data = fixture()
    original = deepcopy(data)
    result = materialize(request, sources, data)
    assert data == original
    assert result["status"] == "needs_evidence"
    assert result["sufficiency"]["coverage_complete"] is True
    assert len(result["missing"]) == 1
    control = result["missing"][0]
    assert control["reason_code"] == "applicability"
    assert control["basis"] == "contradiction" and control["stage"] == "evidence"
    assert control["resolution"] == {"status": "open"} and control["blocks_approval"]
    assert control["requirement_ids"] == ["R1"]
    assert control["linked_source_ids"] == ["s1", "s2"]
    assert {s["sha256"] for s in control["source_versions"]} == {"1" * 64, "2" * 64}
    assert [p["quote"] for p in result["sufficiency"]["uncertainties"][0]["passages"]] == [
        s["quote"] for s in sources]
    assert result["sufficiency"]["evaluated_gaps"] == []


@pytest.mark.parametrize("status", ["not_requested", "supported"])
def test_separate_historical_scope_or_supported_application_creates_no_uncertainty(status):
    request, sources, data = fixture()
    data["uncertainties"] = []
    for row in data["coverage"]:
        row["application"] = {"status": status, "uncertainty_indexes": [],
                              "explanation": "Los ámbitos se distinguen explícitamente: "
                              "la primera reserva es presencial; la segunda es remota."}
    result = materialize(request, sources, data)
    assert result["missing"] == []
    assert result["status"] == "references_found"


@pytest.mark.parametrize("change", [
    "empty_uncertainties", "empty_link", "wrong_status", "orphan", "unknown_requirement",
    "unknown_coverage", "duplicate_coverage", "duplicate_requirement", "one_passage",
    "blank_reason", "unrelated_requirement", "nonliteral", "unselected", "invalid_role",
])
def test_cross_contract_rejects_incomplete_or_unrelated_application_controls(change):
    request, sources, data = fixture()
    if change == "empty_uncertainties":
        data["uncertainties"] = []
    elif change == "empty_link":
        data["coverage"][0]["application"]["uncertainty_indexes"] = []
    elif change == "wrong_status":
        data["coverage"][0]["application"]["status"] = "supported"
    elif change == "orphan":
        data["uncertainties"][0]["coverage_indexes"] = [1]
    elif change == "unknown_requirement":
        data["uncertainties"][0]["requirement_ids"] = ["R9"]
    elif change == "unknown_coverage":
        data["uncertainties"][0]["coverage_indexes"] = [0, 5]
    elif change == "duplicate_coverage":
        data["uncertainties"][0]["coverage_indexes"] = [0, 0, 1]
    elif change == "duplicate_requirement":
        data["uncertainties"][0]["requirement_ids"] = ["R1", "R1"]
    elif change == "one_passage":
        data["coverage"][1]["citations"] = deepcopy(data["coverage"][0]["citations"])
    elif change == "blank_reason":
        data["uncertainties"][0]["why_unresolved"] = " "
    elif change == "unrelated_requirement":
        request["request_requirements"].append({"id": "R2", "text": "Otro objeto"})
        data["coverage"].append(deepcopy(data["coverage"][0]))
        data["coverage"][2]["application"] = {
            "status": "not_requested", "uncertainty_indexes": [], "explanation": "Otro ámbito"}
        data["requirement_checks"].append({"requirement_id": "R2", "status": "supported",
                                          "coverage_indexes": [2], "missing_indexes": [],
                                          "explanation": "Otro ámbito"})
        data["uncertainties"][0]["requirement_ids"] = ["R2"]
    elif change == "nonliteral":
        data["coverage"][1]["citations"][0]["quote"] = "Un texto inexistente."
    elif change == "unselected":
        data["supports"].pop()
    elif change == "invalid_role":
        data["supports"][1]["role"] = "fact"
    with pytest.raises(DomainError):
        materialize(request, sources, data)


def test_every_coverage_row_requires_application_decision_in_schema():
    _, _, data = fixture()
    data["coverage"][0].pop("application")
    with pytest.raises(ValidationError):
        _SourceSelection.model_validate(data)


def test_pending_application_links_uncertainty_without_duplicating_missing():
    request, sources, data = fixture()
    data["coverage_complete"] = False
    data["requirement_checks"][0].update(status="pending", uncertainty_indexes=[0])
    result = materialize(request, sources, data)
    assert len(result["missing"]) == 1
    assert result["missing"][0]["reason_code"] == "applicability"
    assert result["sufficiency"]["evaluated_gaps"] == []
    assert result["sufficiency"]["requirement_checks"][0]["missing_indexes"] == []
    assert result["sufficiency"]["requirement_checks"][0]["uncertainty_indexes"] == [0]
    assert result["sufficiency"]["coverage_complete"] is False


def test_uncertainty_indexes_do_not_renumber_other_evaluated_gaps():
    request, sources, data = fixture()
    request["request_requirements"].append({"id": "R2", "text": "Procedencia del ejemplar"})
    data["coverage_complete"] = False
    data["requirement_checks"][0].update(status="pending", uncertainty_indexes=[0])
    data["requirement_checks"].append({
        "requirement_id": "R2", "status": "pending", "coverage_indexes": [0],
        "missing_indexes": [0], "uncertainty_indexes": [],
        "explanation": "El documento carece de firma cotejada."})
    data["missing"] = [{"kind": "clarification", "reason_code": "provenance",
                        "description": "Cotejar la firma del ejemplar original.",
                        "source_chunk_ids": [sources[0]["chunk_id"]], "basis": "content_gap",
                        "affected_claim": "Procedencia del ejemplar.",
                        "why_unresolved": "No consta el cotejo de la firma."}]
    result = materialize(request, sources, data)
    assert len(result["missing"]) == 2
    assert {item["reason_code"] for item in result["missing"]} == {"provenance", "applicability"}
    assert result["sufficiency"]["evaluated_gaps"][0]["description"] == (
        data["missing"][0]["description"])
    assert len(result["sufficiency"]["evaluated_gaps"]) == 1
    assert result["sufficiency"]["requirement_checks"][1]["missing_indexes"] == [0]
    assert result["sufficiency"]["requirement_checks"][0]["uncertainty_indexes"] == [0]


@pytest.mark.parametrize("change", ["unknown", "duplicate", "supported", "no_reciprocal",
                                   "no_coverage"])
def test_pending_uncertainty_link_is_closed_and_reciprocal(change):
    request, sources, data = fixture()
    data["coverage_complete"] = False
    row = data["requirement_checks"][0]
    row.update(status="pending", uncertainty_indexes=[0])
    if change == "unknown":
        row["uncertainty_indexes"] = [4]
    elif change == "duplicate":
        row["uncertainty_indexes"] = [0, 0]
    elif change == "supported":
        data["coverage_complete"] = True
        row["status"] = "supported"
    elif change == "no_reciprocal":
        request["request_requirements"].append({"id": "R2", "text": "Otro inciso descriptivo"})
        data["requirement_checks"].append({"requirement_id": "R2", "status": "supported",
                                          "coverage_indexes": [0], "missing_indexes": [],
                                          "explanation": "Contenido atribuido."})
        data["uncertainties"][0]["requirement_ids"] = ["R2"]
    else:
        row["coverage_indexes"] = []
    with pytest.raises(DomainError):
        materialize(request, sources, data)


def test_content_gap_can_link_one_passage_and_keeps_other_legitimate_checks():
    request, sources, data = fixture()
    sources[0]["review_status"] = "pending"
    sources[0]["needs_review"] = True
    data["uncertainties"][0]["basis"] = "content_gap"
    data["uncertainties"][0]["coverage_indexes"] = [0]
    data["coverage"][1]["application"] = {
        "status": "not_requested", "uncertainty_indexes": [], "explanation": "Referencia histórica"}
    data["missing"] = [{"kind": "clarification", "description": "Cotejar la firma del ejemplar.",
                        "reason_code": "provenance", "basis": "content_gap",
                        "source_chunk_ids": [sources[0]["chunk_id"]],
                        "affected_claim": "Procedencia", "why_unresolved": "Falta cotejo real."}]
    result = materialize(request, sources, data)
    assert {p["reason_code"] for p in result["missing"]} >= {
        "applicability", "provenance", "transcription"}
    assert all(p["state"] != "document_missing" for p in result["missing"])


def test_unreadable_or_forbidden_source_does_not_become_document_absence():
    request, sources, data = fixture()
    sources[0]["extraction_status"] = "unsupported"
    result = materialize(request, sources, data)
    assert "analysis_error" in result["evidence_states"]
    assert "document_missing" not in result["evidence_states"]
    sources[0]["collection_id"] = "forbidden"
    with pytest.raises(DomainError, match="colección"):
        materialize(request, sources, data)


def test_bounded_existing_retry_repairs_cross_contract_and_materializes_aliases():
    request, sources, data = fixture()
    for i, row in enumerate(data["coverage"], 1):
        row["citations"][0]["chunk_id"] = f"C{i}"
        data["supports"][i - 1]["chunk_id"] = f"C{i}"
    data["uncertainties"][0]["why_unresolved"] = "C1 y C2 no acreditan prevalencia."
    broken = deepcopy(data)
    broken["uncertainties"] = []
    outputs = iter([broken, data])
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=
                               _SourceSelection.model_validate(next(outputs)))

    assessor = OpenAISourceAssessor("fictitious-no-network", "fake-model")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = assessor.assess(request, sources)
    assert len(calls) == 2
    assert "citation_repair" in json.loads(calls[1]["input"])
    assert result["analysis_diagnostic"]["attempts"] == 2
    control = result["missing"][0]
    assert "C1" not in control["why_unresolved"]
    assert "reglamento_1.pdf" in control["why_unresolved"]
    assert control["linked_source_ids"] == ["s1", "s2"]
