"""Copias nuevas: disponibilidad no acredita autenticidad ni entrega.

Bibliotecas temporales y selección simulada; ninguna llamada API ni expediente vivo.
Los controles de contenido se mantienen aunque el lector etiquete cobertura completa.
"""

from copy import deepcopy

import pytest

from pqrs_claro.evidence_contract import apply_evidence_contract
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.source_library import SourceLibrary

DOCUMENTS = [
    {
        "name": "Circular 913 de 2026",
        "category": "institutional_norm",
        "text": (
            "CIRCULAR 913 DE 2026\n"
            "Préstamo de instrumentos de la Escuela Municipal de Música.\n"
            "El préstamo dura siete días. La renovación requiere disponibilidad."
        ),
    },
    {
        "name": "Resolución 628 de 2023",
        "category": "institutional_norm",
        "text": (
            "RESOLUCIÓN 628 DE 2023\n"
            "Uso de las salas del Archivo de la Sierra.\n"
            "Las reservas se reciben los miércoles, por orden de solicitud."
        ),
    },
    {
        "name": "Oficio 2341-2022",
        "category": "historical_response",
        "text": (
            "OFICIO 2341-2022\n"
            "Consulta sobre acceso al observatorio comunitario.\n"
            "La visita descrita para 2022 requiere reserva previa de grupo."
        ),
    },
]


@pytest.fixture(params=DOCUMENTS, ids=[item["name"] for item in DOCUMENTS])
def conserved_document(tmp_path, request):
    document = request.param
    library = SourceLibrary(tmp_path / "isolated-library", PDFExtractor())
    library.save_collection({"id": "new-documents", "title": "Documentos ficticios nuevos"})
    library.link_collections("new-case", ["new-documents"])
    saved = library.add(
        document["name"] + ".txt",
        document["text"].encode(),
        title=document["name"],
        category=document["category"],
        origin="Biblioteca ficticia; autenticidad no cotejada",
        collection_id="new-documents",
    )
    _, chunks = library.snapshot("new-case")
    source = next(item for item in chunks if item["source_id"] == saved["id"])
    return library, document, source


def inquiry(document, description=None):
    return {
        "id": "NEW-P1",
        "case_id": "new-case",
        "title": "Consulta documental nueva",
        "description": description or f"Adjunte copia de {document['name']}.",
        "allowed_collection_ids": ["new-documents"],
        "context": {},
    }


def selected(source, *, missing=(), role="document", use="document_delivery"):
    return _SourceSelection.model_validate({
        "status": "references_found",
        "summary": "Se conserva el archivo identificado; no se acredita certificación ni envío.",
        "supports": [{
            "chunk_id": source["chunk_id"], "role": role,
            "reason": "El encabezado identifica el documento consultado.",
        }],
        "missing": list(missing),
        "warnings": [],
        "coverage_complete": True,
        "coverage": [{
            "aspect": "Documento identificado en la biblioteca",
            "claim": "La biblioteca conserva el documento identificado en su encabezado.",
            "use": use,
            "application": {
                "status": "not_requested", "uncertainty_indexes": [],
                "explanation": "Se consulta el ejemplar conservado; no se aplica a hechos nuevos.",
            },
            "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
            "explanation": "La localización permite preparar la copia, no afirmar su entrega.",
        }],
    })


def materialize(document, source, *, description=None, missing=(), role="document",
                use="document_delivery"):
    return OpenAISourceAssessor._materialize(
        selected(source, missing=missing, role=role, use=use),
        inquiry(document, description), [source],
    )


def test_available_plain_copy_does_not_require_catalog_authentication(conserved_document):
    library, document, source = conserved_document
    before = deepcopy(source)
    assert library.original(source["source_id"], case_id="new-case").read_bytes()
    result = materialize(document, source)
    assert result["missing"] == []
    assert result["status"] == "references_found"
    assert result["supports"][0]["quote"] == before["quote"]
    assert result["supports"][0]["sha256"] == before["sha256"]
    assert result["verifications"] == []
    state = result["sufficiency"]["document_states"][source["source_id"]]
    assert state["availability"] == "identified_copy"
    assert state["authenticity"] == "not_inferred_from_availability"
    assert state["authentication_requested"] is False
    assert state["delivery"] == "pending"
    assert result["warnings"], "La copia disponible no debe declararse autenticada."
    deliveries = [item for item in result["actions"] if item["reason_code"] == "document_delivery"]
    assert len(deliveries) == 1
    assert deliveries[0]["resolution"]["status"] == "open"
    assert not deliveries[0]["blocks_approval"]
    assert source == before


@pytest.mark.parametrize("qualification", ["certificada", "auténtica", "autenticada", "firmada"])
def test_certified_copy_still_needs_authentication(conserved_document, qualification):
    _, document, source = conserved_document
    result = materialize(
        document, source, description=f"Adjunte copia {qualification} de {document['name']}.",
    )
    assert result["supports"], "Una condición pendiente no borra el ejemplar encontrado."
    assert result["missing"]
    assert any(item["reason_code"] in {"provenance", "issued_version"}
               and item["resolution"]["status"] == "open" for item in result["missing"])
    assert result["verifications"] == []


@pytest.mark.parametrize("contrast", [
    ", solo la versión firmada", ", únicamente la versión suscrita",
    " sino la versión firmada", " y sí la versión firmada",
])
def test_negated_certification_does_not_erase_a_requested_signed_version(
    conserved_document, contrast,
):
    _, document, source = conserved_document
    result = materialize(document, source, description=(
        f"Solicito copia de {document['name']}. No requiero certificación{contrast}."
    ))
    state = result["sufficiency"]["document_states"][source["source_id"]]
    assert state["authentication_requested"] is True
    assert any(item["reason_code"] in {"provenance", "issued_version"}
               for item in result["missing"])
    assert result["actions"][0]["resolution"]["status"] == "open"


@pytest.mark.parametrize("qualification", [
    "en su versión suscrita", "con constancia de expedición", "con sello de autenticación",
])
def test_explicit_authentication_qualification_keeps_controls(conserved_document, qualification):
    _, document, source = conserved_document
    result = materialize(
        document, source, description=f"Adjunte copia de {document['name']} {qualification}.",
    )
    assert result["sufficiency"]["document_states"][source["source_id"]][
        "authentication_requested"] is True
    assert any(item["reason_code"] in {"provenance", "issued_version"}
               and item["blocks_approval"] for item in result["missing"])
    assert result["verifications"] == []


def test_explicit_exclusion_does_not_create_an_authentication_requirement(conserved_document):
    _, document, source = conserved_document
    result = materialize(
        document, source,
        description=(f"Adjunte copia de {document['name']}. "
                     "No requiero autenticidad ni certificación."),
    )
    assert result["sufficiency"]["document_states"][source["source_id"]][
        "authentication_requested"] is False
    assert result["missing"] == []


@pytest.mark.parametrize("global_requirement", [True, False], ids=["global", "sibling-only"])
def test_authentication_scope_uses_introduction_without_inheriting_sibling_requirements(
    conserved_document, global_requirement,
):
    _, document, source = conserved_document
    request = inquiry(document)
    introduction = (
        "Solicito que todas las copias que pido abajo sean certificadas."
        if global_requirement else "Solicito información sobre los archivos conservados."
    )
    request["context"] = {"document_context": {
        "origin": "original_petition", "purpose": "scope_only_not_evidence", "truncated": False,
        "excerpts": [{
            "page": 1, "line_start": 1, "line_end": 3,
            "quote": (introduction + "\n1. " + request["description"]
                      + "\n2. Adjunte copia certificada de la Resolución 882 de 2020."),
        }],
        "question_ranges": [
            {"request_id": "NEW-P1", "page": 1, "line_start": 2, "line_end": 2},
            {"request_id": "NEW-P2", "page": 1, "line_start": 3, "line_end": 3},
        ],
    }}
    result = OpenAISourceAssessor._materialize(selected(source), request, [source])
    state = result["sufficiency"]["document_states"][source["source_id"]]
    assert state["authentication_requested"] is global_requirement
    if global_requirement:
        assert any(item["reason_code"] in {"provenance", "issued_version"}
                   and item["blocks_approval"] for item in result["missing"])
    else:
        assert result["missing"] == []


def test_specific_authenticity_contradiction_is_not_waived(conserved_document):
    _, document, source = conserved_document
    gap = {
        "kind": "clarification", "reason_code": "provenance", "basis": "contradiction",
        "source_chunk_ids": [source["chunk_id"]],
        "description": "Contrastar la firma del ejemplar: difiere de la firma del registro.",
        "affected_claim": "Correspondencia del ejemplar con el registro del archivo.",
        "why_unresolved": "El cotejo aportado registra firmas diferentes.",
    }
    result = materialize(document, source, missing=[gap])
    assert result["status"] == "needs_evidence"
    assert any(item["description"] == gap["description"] and item["blocks_approval"]
               for item in result["missing"])
    assert result["supports"][0]["source_id"] == source["source_id"]


def test_available_body_does_not_close_a_specific_missing_annex(conserved_document):
    _, document, source = conserved_document
    gap = {
        "kind": "document", "reason_code": "document_search", "basis": "content_gap",
        "source_chunk_ids": [source["chunk_id"]],
        "description": "Localizar el anexo de inventario solicitado; no se conserva su archivo.",
        "affected_claim": "Copia del anexo de inventario.",
        "why_unresolved": "El ejemplar conservado contiene el cuerpo, pero no el anexo pedido.",
    }
    result = materialize(
        document, source, missing=[gap],
        description=f"Adjunte copia de {document['name']} y su anexo de inventario.",
    )
    assert result["status"] == "needs_evidence"
    assert result["supports"][0]["source_id"] == source["source_id"]
    assert any(item["description"] == gap["description"]
               and item["resolution"]["status"] == "open"
               and item["blocks_approval"] for item in result["missing"])


def test_uncertain_transcription_is_preserved_for_a_copy(conserved_document):
    _, document, source = conserved_document
    result = materialize(document, {**source, "needs_review": True, "method": "ocr"})
    assert any(item["reason_code"] == "transcription" for item in result["missing"])
    assert "support_found" in result["evidence_states"]


def test_description_only_does_not_create_delivery_or_certification(conserved_document):
    _, document, source = conserved_document
    role = "antecedent" if source["category"] == "historical_response" else "rule"
    result = materialize(
        document, source, description=f"Describa qué dice {document['name']}.",
        role=role, use="attributed_content",
    )
    assert result["missing"] == []
    assert result["actions"] == []
    assert result["verifications"] == []


def test_delivery_deadline_does_not_require_authenticating_a_plain_copy(conserved_document):
    _, document, source = conserved_document
    result = materialize(
        document, source, description=f"Envíeme hoy una copia de {document['name']}.",
    )
    assert not any(item["reason_code"] in {"provenance", "issued_version"}
                   for item in result["missing"])
    assert result["supports"][0]["source_id"] == source["source_id"]
    assert any(item["reason_code"] == "document_delivery"
               and item["resolution"]["status"] == "open" for item in result["actions"])


def test_selected_header_identifies_copy_when_neighbor_passage_is_also_selected(conserved_document):
    library, document, initial = conserved_document
    library.add(
        document["name"] + ".txt",
        (document["text"] + "\n" + "Contenido del ejemplar conservado. " * 120).encode(),
        document_id=initial["document_id"], title=document["name"],
        category=document["category"], origin="Biblioteca ficticia; autenticidad no cotejada",
        collection_id="new-documents",
    )
    _, chunks = library.snapshot("new-case")
    header = next(item for item in chunks if item["page"] == 1 and item["line_start"] == 1)
    neighbor = next(item for item in chunks if item["chunk_id"] != header["chunk_id"])
    assert document["text"].splitlines()[0] not in neighbor["quote"]
    selection = selected(header)
    neighbor_role = "antecedent" if document["category"] == "historical_response" else "rule"
    extra = selected(neighbor, role=neighbor_role, use="attributed_content")
    selection.supports.extend(extra.supports)
    selection.coverage.extend(extra.coverage)
    result = OpenAISourceAssessor._materialize(selection, inquiry(document), [header, neighbor])
    assert result["missing"] == []
    assert {item["chunk_id"] for item in result["supports"]} == {
        header["chunk_id"], neighbor["chunk_id"],
    }
    assert all(item["version"] == 2 for item in result["supports"])
    assert result["verifications"] == []


def test_a_past_delivery_receipt_is_not_the_future_delivery_action(conserved_document):
    _, document, source = conserved_document
    question = inquiry(document, f"Informe si {document['name']} se entregó el 8 de abril de 2025.")
    gap = {
        "kind": "document", "reason_code": "document_search", "basis": "content_gap",
        "description": "Localizar el comprobante de entrega anterior del 8 de abril de 2025.",
        "linked_source_ids": [source["source_id"]],
    }
    result = apply_evidence_contract(question, {
        "request_id": question["id"], "status": "needs_evidence",
        "supports": [{**source, "role": "antecedent"}], "missing": [gap], "warnings": [],
    })
    assert result["actions"] == []
    assert len(result["missing"]) == 1
    assert result["missing"][0]["stage"] == "evidence"
    assert result["missing"][0]["blocks_approval"]
    assert result["missing"][0]["resolution"]["status"] == "open"


def test_available_copy_never_bypasses_original_integrity_or_revoked_permission(conserved_document):
    library, document, source = conserved_document
    original = library.original(source["source_id"], case_id="new-case")
    before = original.read_bytes()
    original.write_bytes(before + b"\nExternal change")
    with pytest.raises(DomainError, match="original cambió"):
        library.original(source["source_id"], case_id="new-case")
    original.write_bytes(before)
    library.link_collections("new-case", [])
    assert library.snapshot("new-case") == ([], [])
    with pytest.raises(KeyError):
        library.original(source["source_id"], case_id="new-case")
    revoked = inquiry(document)
    revoked["allowed_collection_ids"] = []
    with pytest.raises(DomainError, match="no está vinculada"):
        OpenAISourceAssessor._materialize(selected(source), revoked, [source])
