"""Real source materialization preserves requested future copies before normalization."""

from copy import deepcopy

import pytest
from test_source_sufficiency import coverage, request, source

from pqrs_claro.evidence_contract import apply_evidence_contract, pending_registry
from pqrs_claro.request_requirements import build_requirements
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection


def fixture(title="Acta 753 de 2025", category="historical_attachment", qualification="certificada",
            condition="", material=False):
    reference = ("de la " if title.startswith("Resolución") else "del ") + title
    inquiry = request(f"Solicito copia {qualification} {reference}.")
    inquiry["request_requirements"] = build_requirements(inquiry)
    document = source(title=title, filename=title.replace(" ", "_") + ".pdf", category=category,
                      is_latest=True,
                      quote=f"{title}. El archivo conserva una reproducción de consulta. "
                            "Su código de verificación remite a otro registro y no se ha "
                            "cotejado con el original.")
    delivery = {
        "kind": "document", "description": f"Preparar y entregar la copia {qualification} "
                                             f"{reference} solicitada{condition}.",
        "reason_code": "specific_gap", "stage": "fulfillment", "basis": "unspecified",
        "source_chunk_ids": [document["chunk_id"]],
        "affected_claim": f"Entrega de la copia {qualification} {reference}.",
        "why_unresolved": "La reproducción está localizada; ello no acredita que la copia "
                          "se haya preparado o entregado.",
    }
    gaps = [delivery]
    if material:
        gaps.insert(0, {
            "kind": "fact", "description": f"Cotejar el {title} con el original y su registro "
                                             "para aclarar la discrepancia del código.",
            "reason_code": "fact_confirmation", "stage": "evidence", "basis": "content_gap",
            "source_chunk_ids": [document["chunk_id"]],
            "affected_claim": "Autenticidad de la reproducción disponible.",
            "why_unresolved": "El código conduce a otro registro y no consta cotejo con "
                              "el original del archivo solicitado.",
        })
    selected = _SourceSelection.model_validate({
        "status": "needs_evidence", "summary": "Archivo localizado; actuaciones pendientes.",
        "supports": [{"chunk_id": document["chunk_id"], "role": "document",
                      "reason": "El encabezado identifica el archivo solicitado."}],
        "missing": gaps, "warnings": [], "coverage_complete": False,
        "coverage": [coverage(document, aspect="Copia disponible",
                              claim="El archivo está descrito como reproducción de consulta.")],
        "requirement_checks": [{
            "requirement_id": "R1", "status": "pending", "coverage_indexes": [0],
            "missing_indexes": list(range(len(gaps))),
            "explanation": "Se conserva la copia y se separan los cotejos de su entrega futura.",
        }],
    })
    return inquiry, document, selected


@pytest.mark.parametrize("title,category", [
    ("Acta 753 de 2025", "historical_attachment"),
    ("Resolución 821 de 2024", "institutional_norm"),
    ("Oficio 966 de 2023", "historical_response"),
])
@pytest.mark.parametrize("qualification", ["simple", "certificada"])
@pytest.mark.parametrize("condition", ["", ", una vez acreditada su procedencia"])
def test_materialization_keeps_future_delivery_scope_and_is_idempotent(
    title, category, qualification, condition,
):
    inquiry, document, selected = fixture(title, category, qualification, condition)
    before = deepcopy((inquiry, document, selected))
    result = OpenAISourceAssessor._materialize(selected, inquiry, [document])
    deliveries = [p for p in result["actions"] if p["reason_code"] == "document_delivery"]
    assert len(deliveries) == 1
    item = deliveries[0]
    original = selected.missing[0]
    assert item["description"] == original.description
    assert item["affected_claim"] == original.affected_claim
    assert item["why_unresolved"] == original.why_unresolved
    assert item["stage"] == "fulfillment" and item["blocks_approval"] is False
    assert item["linked_chunk_ids"] == [document["chunk_id"]]
    assert item["source_versions"][0]["sha256"] == document["sha256"]
    assert not any("Ya están localizados como candidatos:" in p["description"]
                   for p in result["missing"])
    assert result["verifications"] == []
    states = result["sufficiency"]["document_states"][document["source_id"]]
    assert states["authenticity"] == "not_inferred_from_availability"
    assert states["delivery"] == "pending"
    again = apply_evidence_contract(inquiry, result, [document])
    assert again["checks"] == result["checks"]
    assert pending_registry(inquiry, result) == result["checks"]
    assert (inquiry, document, selected) == before


@pytest.mark.parametrize("qualification", ["simple", "certificada"])
def test_material_authenticity_defect_stays_blocking_beside_future_delivery(qualification):
    inquiry, document, selected = fixture(qualification=qualification, material=True)
    result = OpenAISourceAssessor._materialize(selected, inquiry, [document])
    concrete = next(p for p in result["missing"]
                    if p["description"] == selected.missing[0].description)
    assert concrete["basis"] == "content_gap"
    assert concrete["stage"] == "evidence" and concrete["blocks_approval"] is True
    assert concrete["affected_claim"] == selected.missing[0].affected_claim
    assert len(result["actions"]) == 1
    assert result["actions"][0]["description"] == selected.missing[1].description
    assert not result["actions"][0]["blocks_approval"]
    assert not any("Ya están localizados como candidatos:" in p["description"]
                   for p in result["missing"])


def test_copy_request_alone_does_not_add_generic_identity_check():
    inquiry, document, selected = fixture(qualification="simple")
    result = OpenAISourceAssessor._materialize(selected, inquiry, [document])
    assert result["missing"] == []
    assert len(result["actions"]) == 1


@pytest.mark.parametrize("stage", ["evidence", "fulfillment"])
def test_absence_or_search_task_is_not_exempted_just_because_it_says_document_or_fulfillment(stage):
    inquiry, document, selected = fixture()
    selected.missing[0].description = "Localizar y aportar el Acta 753 de 2025."
    selected.missing[0].stage = stage
    selected.missing[0].basis = "unavailable_document"
    result = OpenAISourceAssessor._materialize(selected, inquiry, [document])
    assert any("Ya están localizados como candidatos:" in p["description"]
               and p["blocks_approval"] for p in result["missing"])


def test_actually_unlocated_document_keeps_specific_search_pending():
    inquiry, document, selected = fixture()
    inquiry["description"] = "Adjunte copia del Acta 284 de 2022."
    inquiry["request_requirements"] = build_requirements(inquiry)
    selected.supports[0].role = "historical_evidence"
    selected.missing[0].description = "Localizar y aportar el Acta 284 de 2022 solicitada."
    selected.missing[0].affected_claim = "Disponibilidad del Acta 284 de 2022."
    selected.missing[0].stage = "evidence"
    selected.missing[0].basis = "unavailable_document"
    selected.missing[0].source_chunk_ids = []
    result = OpenAISourceAssessor._materialize(selected, inquiry, [document])
    missing = next(p for p in result["missing"]
                   if p["description"] == selected.missing[0].description)
    assert missing["stage"] == "evidence" and missing["blocks_approval"]
    assert missing["reason_code"] == "search_incomplete"
    assert missing["state"] != "document_missing"
