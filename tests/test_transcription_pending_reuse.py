"""Exact local OCR fallback reuse keeps the entire cited passage under review."""

from copy import deepcopy

import pytest

from pqrs_claro.evidence_contract import (
    apply_evidence_contract,
    normalize_item,
    normalize_pending,
    pending_registry,
)
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.verification_policy import application_matches_check


def fixture(title="Calendario de inspecciones 482", page=3):
    request = {"id": "P1", "description": "Explique las fechas previstas en el documento.",
               "allowed_collection_ids": ["fictitious"]}
    source = {
        "id": "fictitious-source", "source_id": "fictitious-source", "document_id": "doc",
        "version": 1, "sha256": "a" * 64, "extraction_revision": 2,
        "chunk_id": f"fictitious-source:{page}:1:47", "page": page,
        "line_start": 1, "line_end": 47, "quote": "Texto del pasaje completo.",
        "collection_id": "fictitious", "is_latest": True, "extraction_status": "ready",
        "method": "ocr", "needs_review": True, "title": title,
        "category": "historical_attachment", "review_status": "reviewed",
        "validity": "not_applicable",
    }
    common = {"reason_code": "transcription", "stage": "evidence",
              "linked_source_ids": [source["source_id"]],
              "linked_chunk_ids": [source["chunk_id"]]}
    material = {**common, "kind": "fact", "basis": "content_gap",
                "description": "Cotejar en el original la transcripción OCR de las fechas.",
                "affected_claim": "Las fechas previstas para la inspección.",
                "why_unresolved": "La lectura OCR del pasaje no se ha cotejado con el original."}
    generic = {**common, "kind": "clarification", "basis": "unspecified",
               "description": f"Contrastar la transcripción de «{title}», página {page}, "
                              "con su original."}
    finding = {"request_id": "P1", "supports": [source], "missing": [material, generic],
               "warnings": [generic["description"]], "status": "needs_evidence"}
    return request, finding


@pytest.mark.parametrize("title,page", [
    ("Calendario de inspecciones 482", 3),
    ("Inventario del taller técnico", 8),
    ("Informe de restauración 709", 1),
])
def test_only_local_duplicate_is_absorbed_with_identity_and_full_passage_preserved(title, page):
    request, finding = fixture(title, page)
    before = deepcopy(finding)
    expected = normalize_item(request, finding["missing"][0], finding["supports"])
    result = apply_evidence_contract(request, finding)
    assert result["missing"] == [expected]
    assert result["checks"] == [expected]
    assert result["missing"][0]["blocks_approval"]
    assert result["missing"][0]["resolution"] == {"status": "open"}
    assert result["warnings"] == []
    audit = result["gap_decisions"][0]
    assert audit["decision"] == "covered_transcription_fallback"
    assert audit["original"]["description"] == finding["missing"][1]["description"]
    assert audit["covering_check_keys"] == [expected["check_key"]]
    assert pending_registry(request, result) == [expected]
    assert normalize_pending(request, result, [finding["missing"][1]]) == [expected]
    again = apply_evidence_contract(request, result)
    assert again["checks"] == result["checks"] and again["gap_decisions"] == result["gap_decisions"]
    assert finding == before


@pytest.mark.parametrize("change", [
    "narrower_chunk", "other_page", "other_source", "unknown_chunk", "unknown_hash",
    "other_version", "other_revision", "other_request", "revoked", "superseded",
    "different_control", "different_local_text", "unlinked_claim", "already_closed_generic",
])
def test_unequal_or_unproved_scope_keeps_both_controls(change):
    request, finding = fixture()
    source = finding["supports"][0]
    material, generic = finding["missing"]
    if change in {"narrower_chunk", "other_page", "other_source", "unknown_chunk"}:
        chunks = {"narrower_chunk": "fictitious-source:3:12:14",
                  "other_page": "fictitious-source:4:1:47",
                  "other_source": "other-source:3:1:47", "unknown_chunk": "unknown"}
        material["linked_chunk_ids"] = [chunks[change]]
    elif change == "unknown_hash":
        source["sha256"] = "unverified"
    elif change in {"other_version", "other_revision", "other_request"}:
        item = normalize_item(request, material, [source])
        if change == "other_version":
            item["source_versions"][0]["version"] = 0
        elif change == "other_revision":
            item["source_versions"][0]["extraction_revision"] = 1
        else:
            item["request_ids"] = ["P2"]
        finding["missing"][0] = item
    elif change == "revoked":
        request["allowed_collection_ids"] = []
    elif change == "superseded":
        source["is_latest"] = False
    elif change == "different_control":
        generic["description"] = "Comprobar en la transcripción si se omitió otra condición."
    elif change == "different_local_text":
        generic["description"] += " Revisar además el anexo."
    elif change == "unlinked_claim":
        material["affected_claim"] = ""
    elif change == "already_closed_generic":
        item = normalize_item(request, generic, [source])
        item["resolution"] = {
            "status": "resolved", "application_id": "prior", "verification_id": "v"}
        finding["missing"][1] = item
    assert len(pending_registry(request, finding)) == 2


def test_two_material_discrepancies_in_same_passage_stay_separate():
    request, finding = fixture()
    other = {**finding["missing"][0], "description": "Cotejar la transcripción de la cantidad.",
             "affected_claim": "La cantidad prevista de equipos.",
             "why_unresolved": "La cantidad no se ha cotejado con la imagen original."}
    finding["missing"].insert(1, other)
    result = apply_evidence_contract(request, finding)
    assert len(result["checks"]) == len(result["missing"]) == 2
    assert {c["affected_claim"] for c in result["checks"]} == {
        "Las fechas previstas para la inspección.", "La cantidad prevista de equipos."}


def human_application(check, source, *, end=47):
    return {
        "id": "app-fictitious", "case_id": "case-fictitious", "verification_id": "human",
        "check_key": check["check_key"], "request_ids": ["P1"],
        "basis": "Cotejo humano registrado.", "check_reason": "transcription",
        "scope_key": "passage",
        "record": {
            "id": "human", "kind": "human_review", "case_id": "case-fictitious",
            "fact": "Se cotejó el texto indicado.", "basis": "Comparación con el original.",
            "recorded_by": "Gestora ficticia", "recorded_at": "2026-11-17T12:00:00Z",
            "recording_method": "human_form", "source_id": source["source_id"],
            "document_id": source["document_id"], "version": source["version"],
            "source_sha256": source["sha256"], "extraction_revision": source["extraction_revision"],
            "passage": {"chunk_id": source["chunk_id"], "page": source["page"],
                        "line_start": 1, "line_end": end, "quote": source["quote"]},
        },
    }


def test_check_of_some_dates_cannot_close_the_full_passage_obligation():
    request, finding = fixture()
    result = apply_evidence_contract(request, finding)
    control = result["checks"][0]
    partial = human_application(control, finding["supports"][0], end=14)
    assert not application_matches_check(partial, control, request["id"])
    checked = apply_evidence_contract(request, result, applications=[partial])
    assert len(checked["missing"]) == 1
    assert checked["missing"][0]["resolution"] == {"status": "open"}


def test_full_human_review_remains_closed_and_fallback_does_not_reappear():
    request, finding = fixture()
    result = apply_evidence_contract(request, finding)
    app = human_application(result["checks"][0], finding["supports"][0])
    assert application_matches_check(app, result["checks"][0], request["id"])
    checked = apply_evidence_contract(request, result, applications=[app])
    assert checked["missing"] == []
    assert checked["checks"][0]["resolution"]["status"] == "resolved"
    assert normalize_pending(request, checked, [finding["missing"][1]]) == []
    assert len(pending_registry(request, checked)) == 1


def test_unrelated_prior_resolution_cannot_cover_new_local_fallback():
    request, finding = fixture()
    item = normalize_item(request, finding["missing"][0], finding["supports"])
    item["resolution"] = {"status": "resolved", "application_id": "app", "verification_id": "v"}
    finding["missing"][0] = item
    registered = pending_registry(request, finding)
    assert len(registered) == 2
    assert registered[0]["resolution"]["status"] == "resolved"
    assert registered[1]["resolution"] == {"status": "open"}


def test_normal_reader_materialization_does_not_duplicate_its_ocr_fallback():
    request, finding = fixture()
    source = finding["supports"][0]
    material = deepcopy(finding["missing"][0])
    material["source_chunk_ids"] = material.pop("linked_chunk_ids")
    material.pop("linked_source_ids")
    selected = _SourceSelection.model_validate({
        "status": "needs_evidence", "summary": "Fechas leídas; falta cotejar la transcripción.",
        "supports": [{"chunk_id": source["chunk_id"], "role": "historical_evidence",
                      "reason": "El pasaje describe el calendario consultado."}],
        "missing": [material], "warnings": [],
    })
    result = OpenAISourceAssessor._materialize(selected, request, [source])
    assert len(result["checks"]) == len(result["missing"]) == 1
    assert result["checks"][0]["description"] == material["description"]
    assert result["checks"][0]["blocks_approval"]


def test_later_chunk_of_same_document_is_not_lost_during_normalization():
    request, finding = fixture()
    source = finding["supports"][0]
    first = {**source, "chunk_id": "fictitious-source:2:1:47", "page": 2}
    finding["supports"].insert(0, first)
    result = apply_evidence_contract(request, finding)
    assert len(result["checks"]) == 1
    assert result["checks"][0]["linked_chunk_ids"] == [source["chunk_id"]]
