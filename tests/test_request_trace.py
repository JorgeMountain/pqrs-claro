"""New fictional records: diagnostic links never alter evidence or legitimate controls."""

from copy import deepcopy

import pytest

from pqrs_claro.request_trace import build_request_trace, trace_repair_issues


def fixture():
    request = {
        "id": "new-trace-library-loan", "case_id": "new-trace-case",
        "allowed_collection_ids": ["fictional-library"],
        "description": "Indique el plazo y su fundamento; explique la renovación.",
        "request_requirements": [
            {"id": "R1", "text": "Indique el plazo y su fundamento"},
            {"id": "R2", "text": "explique la renovación"},
        ],
    }
    quote = ("El préstamo dura nueve días. El plazo obedece a la rotación del material. "
             "La renovación requiere disponibilidad. Decide la Coordinación de Biblioteca.")
    source = {"chunk_id": "fictional-loan:v1:p1", "source_id": "fictional-loan-v1",
              "document_id": "fictional-loan", "version": 1, "quote": quote,
              "collection_id": "fictional-library", "category": "institutional_norm"}
    finding = {"supports": [source], "sufficiency": {"coverage": [
        {"citations": [{"chunk_id": source["chunk_id"], "quote": quote}]}],
        "evaluated_gaps": [], "uncertainties": [], "requirement_checks": [
            {"requirement_id": rid, "status": "supported", "coverage_indexes": [0],
             "missing_indexes": [], "uncertainty_indexes": []} for rid in ("R1", "R2")
        ]}}
    plan = {"coverage_units": [
        {"id": uid, "requirement_id": rid, "kind": kind, "required": True,
         "claim": claim, "reason": "Responde una parte de la solicitud.",
         "citations": [{"chunk_id": source["chunk_id"], "quote": passage}]}
        for uid, rid, kind, claim, passage in [
            ("U1", "R1", "answer", "El préstamo dura nueve días.",
             "El préstamo dura nueve días."),
            ("U2", "R1", "basis", "El fundamento es la rotación del material.",
             "El plazo obedece a la rotación del material."),
            ("U3", "R2", "condition", "La renovación requiere disponibilidad.",
             "La renovación requiere disponibilidad."),
        ]]}
    pending = {"check_key": "check-provenance-fictitious", "description": "Cotejar firma.",
               "basis": "content_gap", "stage": "evidence", "blocks_approval": True,
               "resolution": {"status": "open"}}
    draft = {"paragraphs": [
        {"text": "El préstamo dura nueve días.", "cited_chunk_ids": [source["chunk_id"]]},
        {"text": "La renovación requiere disponibilidad.",
         "cited_chunk_ids": [source["chunk_id"]]}], "pending": [pending]}
    checks = {"requirement_checks": [
        {"requirement_id": rid, "status": "answered", "paragraph_indexes": [i],
         "pending_indexes": [], "explanation": "Se declara respondido."}
        for i, rid in enumerate(("R1", "R2"))
    ], "unit_checks": [
        {"unit_id": uid, "status": status, "paragraph_indexes": pi,
         "pending_indexes": [], "explanation": reason}
        for uid, status, pi, reason in [
            ("U1", "answered", [0], "Contesta el plazo."),
            ("U2", "omitted", [], "Falta el fundamento que sí consta en la fuente."),
            ("U3", "answered", [1], "Contesta la condición."),
        ]]}
    return request, finding, plan, draft, checks


def test_omission_with_evidence_gets_same_requirement_destination_and_preserves_inputs():
    args = fixture()
    before = deepcopy(args)
    trace = build_request_trace(*args)
    row = trace["requirements"][0]
    assert row["status"] == "evidence_not_used"
    assert row["omissions"][0]["id"] == "U2"
    assert row["omissions"][0]["repair_paragraph_index"] == 0
    assert trace["missing_unit_ids"] == []
    issues = trace_repair_issues(trace, args[3])
    assert [(i["code"], i["paragraph_index"]) for i in issues] == [("answer_unit_omitted", 0)]
    assert args == before


def test_source_shared_by_other_procedure_does_not_supply_target():
    args = fixture()
    args[2]["coverage_units"][0]["required"] = False
    trace = build_request_trace(*args)
    assert trace["missing_unit_ids"] == ["U2"]
    assert trace_repair_issues(trace, args[3]) == []


def test_two_answered_paragraphs_of_same_requirement_are_ambiguous():
    args = fixture()
    args[4]["unit_checks"][0]["paragraph_indexes"] = [0, 1]
    trace = build_request_trace(*args)
    assert trace["missing_unit_ids"] == ["U2"]
    assert trace_repair_issues(trace, args[3]) == []


def test_explicit_omitted_paragraph_retains_existing_target():
    args = fixture()
    args[4]["unit_checks"][1]["paragraph_indexes"] = [0]
    assert build_request_trace(*args)["requirements"][0]["omissions"][0][
        "repair_paragraph_index"] == 0


@pytest.mark.parametrize("change", ["permission", "version", "quote"])
def test_revoked_or_corrected_source_cannot_supply_repair_evidence(change):
    args = fixture()
    if change == "permission":
        args[0]["allowed_collection_ids"] = []
    elif change == "version":
        args[1]["supports"][0]["is_latest"] = False
    else:
        args[1]["supports"][0]["quote"] = "El préstamo ahora dura once días."
    trace = build_request_trace(*args)
    assert all(row["status"] == "not_evaluated" for row in trace["requirements"])
    assert trace["missing_unit_ids"] == []
    assert trace_repair_issues(trace, args[3]) == []


def test_missing_checklist_is_unknown_not_document_missing_or_retrieval_gap():
    request, finding, _, _, _ = fixture()
    finding["sufficiency"] = {}
    trace = build_request_trace(request, finding, {})
    assert {row["status"] for row in trace["requirements"]} == {"not_evaluated"}
    assert all(row["evidence_chunk_ids"] == [] for row in trace["requirements"])


def test_explicit_source_gap_reports_retrieval_gap_without_claiming_document_absence():
    request, finding, _, _, _ = fixture()
    finding["sufficiency"].update(evaluated_gaps=[{
        "description": "Se requiere el registro de préstamos del periodo.", "basis": "content_gap",
    }], requirement_checks=[{
        "requirement_id": "R1", "status": "pending", "coverage_indexes": [],
        "missing_indexes": [0], "uncertainty_indexes": [],
    }])
    trace = build_request_trace(request, finding, {})
    assert trace["requirements"][0]["status"] == "retrieval_gap"
    assert trace["requirements"][1]["status"] == "not_evaluated"


@pytest.mark.parametrize("invalid", ["fulfilled", "resolved", "metadata", "nonblocking"])
def test_unrelated_or_closed_pending_cannot_cover_omission(invalid):
    args = fixture()
    args[2]["coverage_units"] = []
    args[4]["requirement_checks"][0].update(status="pending", pending_indexes=[0])
    pending = args[3]["pending"][0]
    if invalid == "fulfilled":
        pending["stage"] = "fulfillment"
    elif invalid == "resolved":
        pending["resolution"]["status"] = "resolved"
    elif invalid == "metadata":
        pending["basis"] = "metadata_only"
    else:
        pending["blocks_approval"] = False
    trace = build_request_trace(*args)
    assert trace["requirements"][0]["status"] == "not_evaluated"
    assert trace["requirements"][0]["pending_check_keys"] == []


def test_legitimate_pending_and_its_identity_survive_trace():
    args = fixture()
    args[2]["coverage_units"] = []
    args[4]["requirement_checks"][0].update(status="pending", pending_indexes=[0])
    before = deepcopy(args)
    trace = build_request_trace(*args)
    assert trace["requirements"][0]["status"] == "pending"
    assert trace["requirements"][0]["pending_check_keys"] == ["check-provenance-fictitious"]
    assert args == before


def test_optional_context_never_creates_a_missing_unit_or_pending():
    args = fixture()
    args[2]["coverage_units"][1].update(required=False, kind="context")
    trace = build_request_trace(*args)
    assert trace["requirements"][0]["status"] == "reviewed_answer"
    assert trace["missing_unit_ids"] == []
    assert trace["requirements"][0]["omissions"] == []


def test_duplicate_review_identity_is_unknown_instead_of_silently_overwritten():
    args = fixture()
    args[4]["unit_checks"].append(deepcopy(args[4]["unit_checks"][1]))
    trace = build_request_trace(*args)
    assert trace["requirements"][0]["status"] == "not_evaluated"
    assert trace["missing_unit_ids"] == []


def test_required_unit_without_review_cannot_be_reported_as_reviewed_answer():
    args = fixture()
    args[4]["unit_checks"] = []
    assert build_request_trace(*args)["requirements"][0]["status"] == "not_evaluated"


def test_missing_authority_detail_uses_existing_validator_and_current_paragraph():
    args = fixture()
    source = args[1]["supports"][0]
    unit = args[2]["coverage_units"][2]
    quote = "La renovación requiere disponibilidad. Decide la Coordinación de Biblioteca."
    citation = {"chunk_id": source["chunk_id"], "quote": quote}
    unit.update(citations=[citation], details_version=1, no_details_reason="", details=[{
        "id": "U3-K1", "kind": "authority", "citation": citation,
        "members": [{"chunk_id": source["chunk_id"], "quote": "Coordinación de Biblioteca"}],
        "reason": "La autoridad que decide forma parte de lo consultado.",
    }])
    args[4]["detail_checks"] = [{
        "detail_id": "U3-K1", "status": "omitted", "evidence": [], "pending_indexes": [],
        "explanation": "No se identifica la autoridad de la renovación.",
    }]
    trace = build_request_trace(*args)
    row = trace["requirements"][1]
    assert row["status"] == "evidence_not_used"
    assert row["omissions"][0]["id"] == "U3-K1"
    assert row["omissions"][0]["repair_paragraph_index"] == 1
    assert any(issue["code"] == "answer_detail_omitted" and issue["paragraph_index"] == 1
               for issue in trace_repair_issues(trace, args[3]))


def test_unit_specific_pending_retains_key_even_when_requirement_claims_answered():
    args = fixture()
    args[4]["unit_checks"][1].update(status="pending", pending_indexes=[0])
    trace = build_request_trace(*args)
    assert trace["requirements"][0]["status"] == "pending"
    assert trace["requirements"][0]["pending_check_keys"] == ["check-provenance-fictitious"]
    assert trace["missing_unit_ids"] == []


def test_source_metadata_warning_is_not_an_evaluated_retrieval_gap():
    request, finding, _, _, _ = fixture()
    finding["sufficiency"].update(evaluated_gaps=[{
        "description": "El catálogo no informa procedencia.", "basis": "metadata_only",
    }], requirement_checks=[{
        "requirement_id": "R1", "status": "pending", "coverage_indexes": [],
        "missing_indexes": [0], "uncertainty_indexes": [],
    }])
    trace = build_request_trace(request, finding, {})
    assert trace["requirements"][0]["status"] == "not_evaluated"


def test_source_coverage_uses_existing_whitespace_equivalence_without_changing_quotes():
    args = fixture()
    args[2]["coverage_units"] = []
    citation = args[1]["sufficiency"]["coverage"][0]["citations"][0]
    citation["quote"] = citation["quote"].replace(" ", "\n")
    before = deepcopy(args)
    trace = build_request_trace(*args)
    assert trace["requirements"][0]["status"] == "reviewed_answer"
    assert args == before


def test_parent_omission_does_not_patch_when_specific_unit_needs_separate_paragraph():
    args = fixture()
    second = deepcopy(args[1]["supports"][0])
    second.update(chunk_id="fictional-rationale:v1:p1", source_id="fictional-rationale-v1")
    args[1]["supports"].append(second)
    args[2]["coverage_units"][1]["citations"][0]["chunk_id"] = second["chunk_id"]
    args[4]["requirement_checks"][0].update(status="omitted", paragraph_indexes=[])
    trace = build_request_trace(*args)
    assert trace["missing_unit_ids"] == ["U2"]
    assert trace_repair_issues(trace, args[3]) == []


def test_existing_omission_target_cannot_also_authorize_an_append():
    args = fixture()
    second = deepcopy(args[1]["supports"][0])
    second.update(chunk_id="fictional-rationale:v1:p1", source_id="fictional-rationale-v1")
    args[1]["supports"].append(second)
    args[2]["coverage_units"][1]["citations"][0]["chunk_id"] = second["chunk_id"]
    args[4]["unit_checks"][1]["paragraph_indexes"] = [0]
    trace = build_request_trace(*args)
    assert trace["missing_unit_ids"] == []
    assert trace_repair_issues(trace, args[3]) == []
