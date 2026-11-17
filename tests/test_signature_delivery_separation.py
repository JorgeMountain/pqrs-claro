"""Material signature checks stay separate from requested future delivery."""

from copy import deepcopy

import pytest
from test_evidence_contract import application, finding, request, source

from pqrs_claro.evidence_contract import (
    apply_evidence_contract,
    normalize_item,
    normalize_pending,
)


def inquiry():
    return request(description="Solicito copia certificada del acta del taller de cerámica.")


def mixed(**changes):
    return {
        "kind": "document", "reason_code": "document_search", "stage": "fulfillment",
        "description": "Completar el cotejo de la firma con el original custodiado "
                       "y preparar la copia certificada solicitada.",
        "affected_claim": "Que se proporcione la copia certificada del acta.",
        "why_unresolved": "La firma es ilegible en la reproducción y no hay constancia "
                          "de cotejo con el original; no se acredita la copia expedida.",
        "basis": "content_gap", "linked_source_ids": ["one"],
        "linked_chunk_ids": ["one:1:1:3"], **changes,
    }


@pytest.mark.parametrize("description", [
    "Completar el cotejo de la firma con el original custodiado "
    "y preparar la copia certificada solicitada.",
    "Cotejar la firma del ejemplar con el original; entregar la copia solicitada.",
    "Realizar el contraste de la firma con el original y luego remitir el archivo pedido.",
])
def test_material_cotejo_and_delivery_become_two_distinct_controls(description):
    raw = mixed(description=description)
    before = deepcopy(raw)
    result = apply_evidence_contract(inquiry(), finding([raw]))
    assert len(result["missing"]) == 1
    check = result["missing"][0]
    assert check["stage"] == "evidence" and check["blocks_approval"] is True
    assert check["reason_code"] == "fact_confirmation" and check["kind"] == "fact"
    assert check["linked_source_ids"] == ["one"]
    assert check["linked_chunk_ids"] == ["one:1:1:3"]
    assert check["original_description"] == description
    assert check["separated_fulfillment"]["represented_by"] == ["document_delivery"]
    assert len(result["actions"]) == 1
    assert result["actions"][0]["reason_code"] == "document_delivery"
    assert result["actions"][0]["blocks_approval"] is False
    assert raw == before
    assert normalize_pending(inquiry(), result, []) == result["checks"]


def test_signature_comparison_alone_cannot_be_downgraded_by_model_stage():
    raw = mixed(description="Completar el cotejo de la firma con el original custodiado.")
    result = apply_evidence_contract(inquiry(), finding([raw]))
    check = result["missing"][0]
    assert check["stage"] == "evidence" and check["blocks_approval"]
    assert "separated_fulfillment" not in check
    assert len(result["actions"]) == 1


@pytest.mark.parametrize("text", [
    "Faciliten copia simple del reglamento del vivero.",
    "Indiquen quién firmó el acta del encuentro.",
    "Informen qué cargo figura junto a la firma del documento.",
    "Tramiten la firma de la nueva respuesta por la responsable del archivo.",
])
def test_request_mentions_do_not_invent_authenticity_controls(text):
    result = apply_evidence_contract(request(description=text), finding())
    assert result["missing"] == []


@pytest.mark.parametrize("raw", [
    mixed(description="Preparar la copia y tramitar la firma de la nueva certificación.",
          why_unresolved="La certificación futura aún no se ha preparado."),
    mixed(description="Verificar la firma de la respuesta futura y entregar el documento.",
          why_unresolved="No hay cotejo con el original de una respuesta aún no expedida."),
    mixed(description="Cotejar la firma con el original y preparar la copia.",
          basis="metadata_only", why_unresolved="El catálogo no registra la revisión."),
    mixed(description="Cotejar la firma con el original y preparar la copia.",
          why_unresolved="Solo se conoce la fecha de publicación del instructivo."),
    mixed(description="Cotejar la firma con el original y preparar la copia.",
          why_unresolved="No se requiere cotejo con el original; basta preparar la copia."),
    mixed(description="Cotejar la firma con el original y preparar la copia.",
          why_unresolved="No hay discrepancia sobre la firma del ejemplar; el cotejo no consta."),
])
def test_no_material_signature_gap_means_no_new_split_or_block(raw):
    normalized = normalize_item(inquiry(), raw, [source()])
    assert normalized["stage"] == "fulfillment"
    assert normalized["blocks_approval"] is False
    assert "separated_fulfillment" not in normalized


def test_resolution_is_reused_without_reopening_and_version_change_is_not_approved():
    first = apply_evidence_contract(inquiry(), finding([mixed()]))
    check = first["missing"][0]
    applied = apply_evidence_contract(
        inquiry(), first, applications=[application(check, ["P1"])],
    )
    assert next(x for x in applied["checks"] if x["check_key"] == check["check_key"])[
        "resolution"]["status"] == "resolved"
    assert applied["missing"] == []
    repeated = normalize_pending(inquiry(), applied, [{
        "kind": "fact", "description": "Revisar otra vez el mismo cotejo.",
        "existing_check_keys": [check["check_key"]],
    }])
    assert len(repeated) == 1 and repeated[0]["stage"] == "fulfillment"
    changed = apply_evidence_contract(
        inquiry(), finding([mixed()], supports=[source(version=2, sha256="new-file")]),
        applications=[application(check, ["P1"])],
    )
    assert changed["missing"][0]["resolution"] == {"status": "open"}
    assert changed["missing"][0]["check_key"] != check["check_key"]


def test_signature_control_does_not_merge_with_competence_of_signer():
    authority = {**mixed(), "description": "Confirmar la competencia de quien firmó el acta.",
                 "kind": "fact", "reason_code": "fact_confirmation", "stage": "evidence",
                 "affected_claim": "El firmante tenía competencia para expedir el acta.",
                 "why_unresolved": "No consta la delegación que estaba vigente al expedirla."}
    result = apply_evidence_contract(inquiry(), finding([mixed(), authority]))
    assert len(result["missing"]) == 2
    assert len({item["check_key"] for item in result["missing"]}) == 2
    assert all(item["blocks_approval"] for item in result["missing"])


def test_other_material_purpose_keeps_its_identity_despite_mentioning_signature():
    raw = mixed(
        kind="clarification", reason_code="provenance", stage="evidence",
        description="Comprobar la procedencia del archivo y la firma del acta.",
        affected_claim="El ejemplar procede del archivo institucional.",
    )
    check = normalize_item(inquiry(), raw, [source()])
    assert check["reason_code"] == "provenance"
    assert check["affected_claim"] == raw["affected_claim"]
    assert check["description"] == raw["description"]
    assert check["blocks_approval"] is True


def test_digital_signature_validation_is_separate_from_copy_delivery():
    raw = mixed(
        description="Validar la cadena del certificado de la firma digital "
                    "y preparar la copia solicitada.",
        affected_claim="La firma digital del informe pertenece al responsable.",
        why_unresolved="No pudo verificarse la cadena del certificado del firmante "
                       "y su validación está pendiente.",
    )
    result = apply_evidence_contract(inquiry(), finding([raw]))
    assert len(result["missing"]) == 1
    check = result["missing"][0]
    assert check["stage"] == "evidence" and check["blocks_approval"]
    assert check["description"] == "Validar la cadena del certificado de la firma digital"
    assert len(result["actions"]) == 1 and not result["actions"][0]["blocks_approval"]


@pytest.mark.parametrize("description", [
    "Validar la firma digital de la respuesta futura y preparar la copia.",
    "Validar la cadena del certificado SSL del portal y entregar el documento.",
])
def test_future_digital_signature_and_unrelated_ssl_are_not_existing_signature_checks(description):
    raw = mixed(description=description,
                why_unresolved="No pudo verificarse la cadena del certificado y "
                               "su validación está pendiente.")
    result = normalize_item(inquiry(), raw, [source()])
    assert result["stage"] == "fulfillment" and not result["blocks_approval"]
    assert "separated_fulfillment" not in result


def test_document_link_in_delivery_clause_survives_separation():
    raw = mixed(
        description="Completar el cotejo de la firma con el original y preparar "
                    "la copia del Oficio 1436-2024.", linked_source_ids=[], linked_chunk_ids=[],
    )
    result = normalize_item(inquiry(), raw, [source()])
    assert result["linked_source_ids"] == ["one"]
    assert result["source_versions"][0]["document_id"] == "office"
