"""Future delivery conditions do not become new authenticity checks or duplicate tasks."""

from copy import deepcopy

import pytest
from test_signature_delivery_separation import mixed

from pqrs_claro.evidence_contract import (
    apply_evidence_contract,
    normalize_item,
    normalize_pending,
    pending_registry,
)
from pqrs_claro.request_requirements import build_requirements


def fixture(description="Remitan copia certificada del Acta 1436 de 2024."):
    request = {"id": "P-copia", "description": description,
               "allowed_collection_ids": ["archivo-ficticio"]}
    request["request_requirements"] = build_requirements(request)
    source = {"source_id": "copia-v1", "chunk_id": "copia-v1:p1", "document_id": "copia",
              "version": 1, "sha256": "one", "category": "historical_attachment",
              "collection_id": "archivo-ficticio", "quote": "El archivo conserva el acta."}
    gap = {"kind": "document", "reason_code": "specific_gap", "stage": "fulfillment",
           "basis": "unspecified", "source_chunk_ids": [source["chunk_id"]],
           "description": "Preparar, certificar y remitir la copia solicitada, "
                          "una vez acreditada la identidad y procedencia del acta.",
           "affected_claim": "La entrega de una copia certificada del Acta 1436 de 2024.",
           "why_unresolved": "La localización del archivo no acredita que la copia se remitió."}
    action = {**gap, "linked_chunk_ids": gap["source_chunk_ids"],
              "linked_source_ids": [source["source_id"]]}
    finding = {"request_id": request["id"], "supports": [source], "missing": [action],
               "sufficiency": {"evaluated_gaps": [gap], "requirement_checks": [
                   {"requirement_id": r["id"], "missing_indexes": [0] if i == 0 else []}
                   for i, r in enumerate(request["request_requirements"])]}}
    return request, finding


@pytest.mark.parametrize("reason", ["specific_gap", "requested_followup", "document_delivery"])
def test_requested_delivery_condition_does_not_become_provenance(reason):
    request, finding = fixture()
    finding["missing"][0]["reason_code"] = reason
    result = apply_evidence_contract(request, finding)
    assert result["missing"] == []
    assert len(result["actions"]) == 1
    action = result["actions"][0]
    assert action["description"] == finding["missing"][0]["description"]
    assert action["reason_code"] == "document_delivery"
    assert action["stage"] == "fulfillment" and not action["blocks_approval"]
    assert pending_registry(request, result) == result["checks"]


def test_delivery_condition_keeps_independent_provenance_and_material_signature():
    request, finding = fixture()
    source = finding["supports"][0]
    check = mixed(reason_code="provenance", stage="evidence", kind="clarification",
                  description="Cotejar la firma del ejemplar original.",
                  affected_claim="Procedencia del ejemplar.",
                  why_unresolved="No consta el cotejo de la firma.",
                  linked_source_ids=[source["source_id"]],
                  linked_chunk_ids=[source["chunk_id"]])
    finding["missing"].append(check)
    result = apply_evidence_contract(request, finding)
    assert len(result["missing"]) == len(result["actions"]) == 1
    kept = result["missing"][0]
    assert kept["reason_code"] == "provenance" and kept["blocks_approval"]
    assert kept["affected_claim"] == check["affected_claim"]


def test_future_delivery_after_transcription_review_is_not_itself_transcription():
    request, finding = fixture()
    action = finding["missing"][0]
    action["description"] = (
        "Entregar la copia solicitada, una vez revisada la transcripción del archivo."
    )
    item = normalize_item(request, action, finding["supports"])
    assert item["reason_code"] == "document_delivery"
    assert not item["blocks_approval"]


@pytest.mark.parametrize("change", ["no_request", "material", "explicit_provenance", "cotejo"])
def test_delivery_detection_does_not_reclassify_real_controls(change):
    request, finding = fixture()
    action = finding["missing"][0]
    if change == "no_request":
        request["description"] = "Informen quién conserva el acta."
    elif change == "material":
        action["basis"] = "content_gap"
        action["description"] = "Cotejar la firma del original y preparar la copia."
        action["why_unresolved"] = "La firma es ilegible y no consta cotejo con el original."
    elif change == "explicit_provenance":
        action["reason_code"] = "provenance"
    elif change == "cotejo":
        action["description"] = "Cotejar la procedencia del archivo antes de remitir la copia."
    item = normalize_item(request, action, finding["supports"])
    assert item["stage"] == "evidence" and item["blocks_approval"]


@pytest.mark.parametrize("change", ["mapping", "claim", "chunk", "version", "permission"])
def test_inexact_or_stale_delivery_cannot_suppress_new_generic_task(change):
    request, finding = fixture()
    action = finding["missing"][0]
    if change == "mapping":
        finding["sufficiency"]["requirement_checks"][0]["missing_indexes"] = []
    elif change == "claim":
        action["affected_claim"] = "Otra entrega."
    elif change == "chunk":
        action["linked_chunk_ids"] = ["another-passage"]
    elif change == "version":
        action = normalize_item(request, action, finding["supports"])
        action["source_versions"][0]["version"] = 0
        finding["missing"] = [action]
    elif change == "permission":
        request["allowed_collection_ids"] = []
    assert len(pending_registry(request, finding)) == 2


@pytest.mark.parametrize("description", [
    "Remitan copia del Acta 1436 de 2024; envíen copia del Oficio 1622 de 2025.",
    "Remitan copia del Acta 1436 de 2024 y del Oficio 1622 de 2025.",
    "Remitan copia del informe y del cronograma.",
    "Entreguen copias del Acta 1436 de 2024 y su anexo fotográfico.",
    "Remitan copias de los archivos A, B.",
    "Entreguen copia del Acta 1436 de 2024 y anexo fotográfico.",
])
def test_partial_delivery_does_not_remove_generic_obligation(description):
    request, finding = fixture(description)
    assert len(pending_registry(request, finding)) == 2


def test_mapped_delivery_of_a_different_numbered_document_does_not_suppress_generic():
    request, finding = fixture("Remitan copia del Acta 1622 de 2025.")
    assert len(pending_registry(request, finding)) == 2


def test_exact_closed_delivery_is_preserved_without_recreating_generic():
    request, finding = fixture()
    result = apply_evidence_contract(request, finding)
    action = result["checks"][0]
    action["resolution"] = {"status": "resolved", "action": "fulfilled", "actor": "Gestora"}
    result["actions"] = []
    before = deepcopy(result)
    assert pending_registry(request, result) == [action]
    assert normalize_pending(request, result, []) == []
    assert result == before


def test_closed_delivery_from_other_version_cannot_remove_current_obligation():
    request, finding = fixture()
    result = apply_evidence_contract(request, finding)
    result["checks"][0]["resolution"] = {"status": "resolved", "action": "fulfilled"}
    result["actions"] = []
    result["supports"][0]["version"] = 2
    result["supports"][0]["sha256"] = "two"
    current = normalize_pending(request, result, [])
    assert len(current) == 1 and current[0]["resolution"] == {"status": "open"}
    assert current[0]["reason_code"] == "document_delivery"


def supported_fixture():
    request, finding = fixture()
    source = finding["supports"][0]
    finding["sufficiency"]["requirement_checks"][0].update(
        status="supported", missing_indexes=[], coverage_indexes=[0]
    )
    finding["sufficiency"]["coverage"] = [{
        "use": "attributed_content", "claim": "El archivo solicitado está localizado.",
        "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
    }]
    return request, finding


def test_supported_copy_reuses_one_existing_delivery_without_changing_coverage():
    request, finding = supported_fixture()
    before = deepcopy(finding)
    result = apply_evidence_contract(request, finding)
    assert finding == before
    assert result["sufficiency"] == before["sufficiency"]
    assert result["missing"] == []
    assert len(result["actions"]) == 1
    assert result["actions"][0]["reason_code"] == "document_delivery"
    assert not result["actions"][0]["blocks_approval"]
    assert pending_registry(request, result) == result["checks"]
    result["checks"][0]["resolution"] = {"status": "resolved", "action": "fulfilled"}
    result["actions"] = []
    assert normalize_pending(request, result, []) == []


@pytest.mark.parametrize("change", [
    "other_chunk", "other_document", "other_object", "two_coverages", "two_actions",
    "two_requirements", "literal", "permission", "old_version", "list",
])
def test_ambiguous_or_stale_coverage_cannot_suppress_generic_delivery(change):
    request, finding = supported_fixture()
    source = finding["supports"][0]
    sufficiency = finding["sufficiency"]
    if change == "other_chunk":
        second = {**source, "chunk_id": "same-document:another-passage"}
        finding["supports"].append(second)
        sufficiency["coverage"][0]["citations"][0]["chunk_id"] = second["chunk_id"]
    elif change in {"other_document", "old_version"}:
        item = normalize_item(request, finding["missing"][0], finding["supports"])
        finding["missing"] = [item]
        key, value = ("document_id", "another-document") if change == "other_document" else (
            "version", 0
        )
        item["source_versions"][0][key] = value
    elif change == "other_object":
        request["description"] = "Remitan copia certificada del Acta 1622 de 2025."
        request["request_requirements"] = build_requirements(request)
    elif change == "two_coverages":
        sufficiency["coverage"].append(deepcopy(sufficiency["coverage"][0]))
        sufficiency["requirement_checks"][0]["coverage_indexes"] = [0, 1]
    elif change == "two_actions":
        gap = {**sufficiency["evaluated_gaps"][0], "description": "Entregar otra copia."}
        sufficiency["evaluated_gaps"].append(gap)
    elif change == "two_requirements":
        request["description"] += "; Remitan copia del Oficio 1622 de 2025."
        request["request_requirements"] = build_requirements(request)
        sufficiency["requirement_checks"].append({
            "requirement_id": "R2", "status": "supported", "coverage_indexes": [0],
            "missing_indexes": [],
        })
    elif change == "literal":
        sufficiency["coverage"][0]["citations"][0]["quote"] = "Una cita no presente."
    elif change == "permission":
        request["allowed_collection_ids"] = []
    elif change == "list":
        request["description"] = "Remitan copias de los archivos A, B."
        request["request_requirements"] = build_requirements(request)
    assert len(pending_registry(request, finding)) == 2


def mapped_copy(description, task, claim, *, supported):
    request, finding = supported_fixture() if supported else fixture(description)
    request["description"] = description
    request["request_requirements"] = build_requirements(request)
    if not supported:
        finding["sufficiency"]["requirement_checks"][0]["status"] = "pending"
    for item in (finding["missing"][0], finding["sufficiency"]["evaluated_gaps"][0]):
        item.update(description=task, affected_claim=claim)
    return request, finding


@pytest.mark.parametrize("supported", [False, True])
@pytest.mark.parametrize("description,task,claim", [
    ("Remitan copia del informe.", "Entregar la copia del cronograma.",
     "Entrega de la copia del cronograma."),
    ("Remitan copia certificada del Acta 1436 de 2024.",
     "Entregar la copia simple del Acta 1436 de 2024.",
     "Entrega de copia simple del Acta 1436 de 2024."),
])
def test_other_object_or_copy_modality_does_not_replace_the_requested_delivery(
    supported, description, task, claim,
):
    request, finding = mapped_copy(description, task, claim, supported=supported)
    before = deepcopy(finding)
    registry = pending_registry(request, finding)
    assert len(registry) == 2
    assert any(item["description"] == task for item in registry)
    assert any(item["description"].startswith("Preparar la entrega de los archivos")
               for item in registry)
    assert finding == before


@pytest.mark.parametrize("supported", [False, True])
@pytest.mark.parametrize("description,task,claim", [
    ("Remitan copia del informe.", "Entregar la copia del informe.",
     "Entrega de la copia del informe."),
    ("Remitan copia simple del informe.", "Entregar la copia simple del informe.",
     "Entrega de la copia simple del informe."),
    ("Remitan copia certificada del informe.", "Preparar y certificar la copia del informe.",
     "Entrega de la copia certificada del informe."),
    ("Remitan copia certificada del Acta 1436 de 2024.",
     "Entregar la copia certificada del Acta 1436.",
     "Entrega de la copia certificada del Acta 1436."),
])
def test_same_literal_object_and_modality_still_reuses_delivery_without_extra_title_requirements(
    supported, description, task, claim,
):
    request, finding = mapped_copy(description, task, claim, supported=supported)
    before = deepcopy(finding)
    registry = pending_registry(request, finding)
    assert len(registry) == 1 and registry[0]["description"] == task
    assert registry[0]["stage"] == "fulfillment" and not registry[0]["blocks_approval"]
    assert finding == before


@pytest.mark.parametrize("supported", [False, True])
@pytest.mark.parametrize("action_object,expected_count", [
    ("plano de logística TL-52", 1),
    ("plano de evacuación TL-52", 2),
])
def test_explicit_location_tail_does_not_change_identity_or_allow_a_similar_title(
    supported, action_object, expected_count,
):
    request, finding = mapped_copy(
        "Envíen una copia simple del plano de logística TL-52 disponible en el archivo municipal.",
        f"Preparar y enviar la copia simple del {action_object}.",
        "Envío efectivo de la copia simple solicitada.", supported=supported,
    )
    before = deepcopy(finding)
    registry = pending_registry(request, finding)
    assert len(registry) == expected_count
    assert any(item["description"] == finding["missing"][0]["description"] for item in registry)
    assert finding == before
