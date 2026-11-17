"""Specific authentication checks cover redundant catalog provenance, not other duties.

New fictional originals in temporary libraries; reader selections are deterministic.
No API calls, live files or human approvals are involved.
"""

from copy import deepcopy

import pytest

from pqrs_claro.evidence_contract import (
    apply_evidence_contract,
    normalize_item,
    normalize_pending,
)
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.source_library import SourceLibrary

DOCUMENTS = [
    ("Circular 556 de 2022", "CIRCULAR 556 DE 2022", "institutional_norm",
     "Préstamo de kits de astronomía. La devolución se registra en la estación."),
    ("Resolución 812 de 2024", "RESOLUCIÓN 812 DE 2024", "institutional_norm",
     "Uso del jardín de polinizadores. La reserva se presenta ante la coordinación."),
    ("Decreto 394 de 2021", "DECRETO 394 DE 2021", "national_norm",
     "Consulta de la colección de partituras. Se conserva un registro de préstamos."),
]


def add_document(library, document, *, document_id=None, extra=""):
    name, header, category, body = document
    saved = library.add(
        name + ".txt", (header + "\n" + body + extra).encode(), title=name,
        category=category, origin="Archivo ficticio para pruebas de procedencia",
        collection_id="provenance-fixtures", document_id=document_id,
    )
    _, chunks = library.snapshot("provenance-case")
    return next(chunk for chunk in chunks if chunk["source_id"] == saved["id"])


def new_library(tmp_path):
    library = SourceLibrary(tmp_path / "provenance-fixtures", PDFExtractor())
    library.save_collection({"id": "provenance-fixtures", "title": "Biblioteca ficticia nueva"})
    library.link_collections("provenance-case", ["provenance-fixtures"])
    return library


@pytest.fixture(params=DOCUMENTS, ids=[row[0] for row in DOCUMENTS])
def original(tmp_path, request):
    library = new_library(tmp_path)
    return library, request.param, add_document(library, request.param)


def inquiry(source):
    return {
        "id": "PROV-P1", "case_id": "provenance-case", "title": "Copia certificada",
        "description": f"Adjunte copia certificada de {source['title']}.",
        "allowed_collection_ids": ["provenance-fixtures"], "context": {},
    }


def specific(source, reason="source_identity", **changes):
    descriptions = {
        "provenance": "Cotejar la procedencia del ejemplar con el registro institucional "
                      "para verificar su autenticidad.",
        "source_identity": "Contrastar la autenticidad de este ejemplar con el original "
                           "custodiado por el archivo.",
        "issued_version": "Comprobar la autenticidad de la versión expedida cotejando "
                          "el sello del archivo.",
    }
    return {
        "kind": "clarification", "reason_code": reason, "basis": "content_gap",
        "stage": "evidence", "source_chunk_ids": [source["chunk_id"]],
        "description": descriptions.get(reason, "Comprobar el objeto documental solicitado."),
        "affected_claim": "La copia conservada corresponde al documento auténtico expedido "
                          "por la entidad.",
        "why_unresolved": "Los pasajes no contienen el cotejo de autenticidad del ejemplar.",
        **changes,
    }


def linked(raw, source):
    result = deepcopy(raw)
    result["linked_chunk_ids"] = result.pop("source_chunk_ids", [source["chunk_id"]])
    result["linked_source_ids"] = [source["source_id"]]
    return result


def generic(source):
    return {
        "kind": "clarification", "reason_code": "provenance", "basis": "metadata_only",
        "catalog_check": "review_status",
        "description": f"Revisar la procedencia y el contenido de «{source['title']}».",
        "linked_source_ids": [source["source_id"]],
        "linked_chunk_ids": [source["chunk_id"]],
    }


def select(source, missing):
    return _SourceSelection.model_validate({
        "status": "needs_evidence", "summary": "Copia localizada con cotejo pendiente.",
        "supports": [{"chunk_id": source["chunk_id"], "role": "document",
                      "reason": "El encabezado identifica el ejemplar solicitado."}],
        "missing": missing, "warnings": [], "coverage_complete": False,
        "coverage": [{
            "aspect": "Identificación de la copia", "claim": "El ejemplar está localizado.",
            "use": "document_delivery",
            "application": {"status": "not_requested", "uncertainty_indexes": [],
                            "explanation": "Se pide copia certificada, no aplicación normativa."},
            "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
            "explanation": "La identidad no acredita autenticidad, certificación o envío.",
        }],
    })


def materialize(source, missing):
    return OpenAISourceAssessor._materialize(select(source, missing), inquiry(source), [source])


def contract(source, gaps, *, sources=None):
    return apply_evidence_contract(inquiry(source), {
        "request_id": "PROV-P1", "status": "needs_evidence",
        "supports": [{**item, "role": "document"} for item in sources or [source]],
        "missing": gaps, "warnings": [],
    })


def assert_open_material_and_delivery(result, source, raw):
    material = next(item for item in result["missing"] if item["description"] == raw["description"])
    assert material["basis"] == raw["basis"]
    assert material["affected_claim"] == raw["affected_claim"]
    assert material["why_unresolved"] == raw["why_unresolved"]
    assert material["linked_source_ids"] == [source["source_id"]]
    assert material["resolution"] == {"status": "open"}
    assert material["blocks_approval"]
    assert result["status"] == "needs_evidence"
    assert result["supports"][0]["quote"] == source["quote"]
    actions = result["actions"]
    assert len(actions) == 1 and actions[0]["reason_code"] == "document_delivery"
    assert actions[0]["resolution"] == {"status": "open"}
    assert not actions[0]["blocks_approval"]
    return material


@pytest.mark.parametrize("reason", ["provenance", "source_identity", "issued_version"])
def test_specific_authentication_covers_generic_provenance_without_closing_it(original, reason):
    _, _, source = original
    raw = specific(source, reason)
    expected = normalize_item(inquiry(source), linked(raw, source), [source])
    result = materialize(source, [raw])
    material = assert_open_material_and_delivery(result, source, raw)
    assert result["missing"] == [material]
    assert material == expected
    decisions = [row for row in result["gap_decisions"]
                 if row["decision"] == "covered_by_specific_check"]
    assert len(decisions) == 1
    assert decisions[0]["original"]["basis"] == "metadata_only"
    assert decisions[0]["original"]["reason_code"] == "provenance"
    assert decisions[0]["covering_check_keys"] == [material["check_key"]]
    assert decisions[0]["reason"]
    assert result.get("verifications", []) == []


@pytest.mark.parametrize("reason,description,claim", [
    ("source_identity", "Precisar si el título identifica la sala norte o la sala sur.",
     "El asunto del documento corresponde al espacio consultado."),
    ("applicability", "Confirmar si la coordinación tiene competencia para autorizar el préstamo.",
     "La coordinación es la autoridad competente para esta solicitud."),
    ("transcription", "Contrastar la transcripción de la cifra ilegible con la página original.",
     "La duración transcrita coincide con la cifra de la página original."),
    ("validity", "Cotejar la vigencia de la disposición para el periodo consultado.",
     "La disposición rige para el periodo de la solicitud."),
])
def test_other_checks_do_not_cover_authentication(original, reason, description, claim):
    _, _, source = original
    raw = specific(source, reason, description=description, affected_claim=claim,
                   why_unresolved="Los pasajes no resuelven esa comprobación concreta.")
    result = materialize(source, [raw])
    assert any(item["basis"] == "metadata_only" and item["reason_code"] == "provenance"
               for item in result["missing"])
    assert any(item["description"] == description for item in result["missing"])
    assert not any(row["decision"] == "covered_by_specific_check"
                   for row in result["gap_decisions"])


def test_two_material_authentication_checks_keep_distinct_identity(original):
    _, _, source = original
    first = specific(source, "provenance")
    second = specific(
        source, "provenance", basis="contradiction",
        description="Contrastar la firma del ejemplar: el registro contiene una firma distinta.",
        affected_claim=("La firma del ejemplar es auténtica y corresponde "
                        "al registro de expedición."),
        why_unresolved="El cotejo adjunto muestra una diferencia entre ambas firmas.",
    )
    result = materialize(source, [first, second])
    material = [row for row in result["missing"] if row["basis"] != "metadata_only"]
    assert len(material) == 2
    assert {row["description"] for row in material} == {first["description"], second["description"]}
    assert len({row["check_key"] for row in material}) == 2
    assert all(row["resolution"] == {"status": "open"} for row in material)
    assert not any(row["basis"] == "metadata_only" for row in result["missing"])


def test_ingress_traceability_covers_catalog_provenance_but_preserves_signature_check(original):
    _, _, source = original
    provenance = specific(
        source, "provenance",
        affected_claim="De qué registro de ingreso procede el archivo y cuál es su trazabilidad",
        description="Identificar el registro de ingreso vinculado al archivo conservado, "
                    "mediante su asiento o identificador.",
        why_unresolved="El pasaje conservado no identifica el asiento de ingreso del archivo.",
    )
    signature = specific(
        source, "fact_confirmation",
        affected_claim=("La firma del ejemplar es auténtica y corresponde "
                        "al registro de expedición."),
        description="Comprobar la autenticidad de la firma del ejemplar.",
        why_unresolved="No se ha contrastado la firma con el registro de expedición.",
    )
    result = materialize(source, [provenance, signature])
    expected = [normalize_item(inquiry(source), linked(raw, source), [source])
                for raw in (provenance, signature)]
    assert result["missing"] == expected
    assert len({item["check_key"] for item in result["missing"]}) == 2
    assert all(item["resolution"] == {"status": "open"} for item in result["missing"])
    decisions = [row for row in result["gap_decisions"]
                 if row["decision"] == "covered_by_specific_check"]
    assert len(decisions) == 1
    assert decisions[0]["covering_check_keys"] == [expected[0]["check_key"]]
    assert decisions[0]["original"]["catalog_check"] == "review_status"
    assert result["status"] == "needs_evidence"


def test_signature_authenticity_alone_does_not_cover_catalog_provenance(original):
    _, _, source = original
    signature = specific(
        source, "source_identity",
        affected_claim=("La firma del ejemplar es auténtica y corresponde "
                        "al registro de expedición."),
        description="Comprobar la autenticidad de la firma del ejemplar.",
        why_unresolved="No se ha contrastado la firma con el registro de expedición.",
    )
    result = materialize(source, [signature])
    expected = normalize_item(inquiry(source), linked(signature, source), [source])
    assert expected in result["missing"]
    assert len(result["missing"]) == 2
    assert any(item.get("catalog_check") == "review_status" for item in result["missing"])
    assert not any(row["decision"] == "covered_by_specific_check"
                   for row in result["gap_decisions"])
    assert all(item["resolution"] == {"status": "open"} for item in result["missing"])


def test_different_source_cannot_cover_generic_provenance(original):
    library, document, source = original
    other = next(row for row in DOCUMENTS if row != document)
    other_source = add_document(library, other)
    raw = linked(specific(other_source), other_source)
    result = contract(source, [generic(source), raw], sources=[source, other_source])
    assert len(result["missing"]) == 2
    assert any(row["basis"] == "metadata_only" for row in result["missing"])
    assert raw["description"] in {row["description"] for row in result["missing"]}


def test_different_version_cannot_cover_generic_provenance(original):
    library, document, old = original
    current = add_document(library, document, document_id=old["document_id"],
                           extra="\nSe añade una nota a la versión conservada.")
    assert current["version"] == old["version"] + 1
    raw = linked(specific(old), old)
    result = contract(current, [generic(current), raw], sources=[current, old])
    assert len(result["missing"]) == 2
    generic_check = next(row for row in result["missing"] if row["basis"] == "metadata_only")
    specific_check = next(row for row in result["missing"] if row["basis"] != "metadata_only")
    assert generic_check["source_versions"] != specific_check["source_versions"]


def test_reapplying_contract_is_idempotent_and_keeps_audit(original):
    _, _, source = original
    first = materialize(source, [specific(source)])
    second = apply_evidence_contract(inquiry(source), first, [source])
    assert second["checks"] == first["checks"]
    assert second["missing"] == first["missing"]
    assert second["actions"] == first["actions"]
    assert second["gap_decisions"] == first["gap_decisions"]
    assert len(second["missing"]) == 1


def test_drafting_cannot_reintroduce_generic_provenance(original):
    _, _, source = original
    finding = materialize(source, [specific(source)])
    reintroduced = generic(source)
    reintroduced.pop("catalog_check")
    pending = normalize_pending(inquiry(source), finding, [reintroduced])
    assert {row["check_key"] for row in pending} == {
        row["check_key"] for row in [*finding["missing"], *finding["actions"]]
    }
    assert not any(row["basis"] == "metadata_only" for row in pending if row.get("basis"))


def test_future_certification_is_not_an_existing_authentication_check(original):
    _, _, source = original
    future = linked(specific(
        source, "specific_gap", stage="fulfillment",
        description="Preparar la certificación de autenticidad para la respuesta final.",
    ), source)
    result = contract(source, [generic(source), future])
    assert len(result["missing"]) == 1
    assert result["missing"][0]["basis"] == "metadata_only"
    assert any(row["description"] == future["description"] for row in result["actions"])
    assert result["missing"][0]["resolution"] == {"status": "open"}


def test_model_generic_cannot_replace_local_audit_marker(original):
    _, _, source = original
    model_generic = {
        "kind": "clarification", "reason_code": "provenance", "basis": "metadata_only",
        "description": "Cotejar la procedencia del archivo.",
        "source_chunk_ids": [source["chunk_id"]],
    }
    finding = materialize(source, [model_generic, specific(source)])
    assert len(finding["missing"]) == 1
    decision = next(row for row in finding["gap_decisions"]
                    if row["decision"] == "covered_by_specific_check")
    assert decision["original"]["catalog_check"] == "review_status"
    repeated = generic(source)
    repeated.pop("catalog_check")
    assert normalize_pending(inquiry(source), finding, [repeated]) == [
        *finding["missing"], *finding["actions"],
    ]


def test_unmarked_generic_without_previous_audit_is_not_absorbed(tmp_path):
    source = add_document(new_library(tmp_path), DOCUMENTS[0])
    unmarked = generic(source)
    unmarked.pop("catalog_check")
    result = contract(source, [unmarked, linked(specific(source), source)])
    assert len(result["missing"]) == 2
    assert any(item["basis"] == "metadata_only" for item in result["missing"])
    assert not any(item["decision"] == "covered_by_specific_check"
                   for item in result.get("gap_decisions", []))


@pytest.mark.parametrize("change", [{"sha256": None}, {"version": None}])
def test_absorption_requires_complete_version_identity(tmp_path, change):
    source = {**add_document(new_library(tmp_path), DOCUMENTS[0]), **change}
    result = contract(source, [generic(source), linked(specific(source), source)])
    assert len(result["missing"]) == 2
    assert any(item["basis"] == "metadata_only" for item in result["missing"])


def test_material_check_for_another_question_cannot_cover_current_generic(tmp_path):
    source = add_document(new_library(tmp_path), DOCUMENTS[0])
    request = inquiry(source)
    other_request = {**request, "id": "PROV-P2", "description": "Otro cotejo de autenticidad."}
    foreign = normalize_item(other_request, linked(specific(source), source), [source])
    finding = {"supports": [source], "missing": [generic(source)], "checks": []}
    pending = normalize_pending(request, finding, [foreign])
    assert any(item["basis"] == "metadata_only" for item in pending if item.get("basis"))
    assert foreign in pending


def test_resolved_material_check_cannot_implicitly_resolve_catalog_provenance(tmp_path):
    source = add_document(new_library(tmp_path), DOCUMENTS[0])
    request = inquiry(source)
    resolved = normalize_item(request, linked(specific(source), source), [source])
    resolved["resolution"] = {"status": "resolved", "verification_id": "old-human-review"}
    finding = {"supports": [source], "missing": [generic(source)], "checks": [resolved]}
    pending = normalize_pending(request, finding, [resolved])
    assert any(item["basis"] == "metadata_only" for item in pending if item.get("basis"))
    assert all(item["check_key"] != resolved["check_key"] for item in pending)
