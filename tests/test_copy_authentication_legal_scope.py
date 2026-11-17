"""Copy authentication must not be mistaken for a question about legal effects.

New fictional documents in temporary libraries; simulated reader output, no API.
The checks exercise materialization so the final citations, open controls and
future delivery duties are checked together with request-scope classification.
"""

from copy import deepcopy

import pytest

from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.source_library import SourceLibrary

DOCUMENTS = [
    ("Circular 473 de 2023", "CIRCULAR 473 DE 2023", "institutional_norm",
     "Préstamo de prismáticos del observatorio ficticio. Se registra cada devolución."),
    ("Resolución 619 de 2020", "RESOLUCIÓN 619 DE 2020", "institutional_norm",
     "Acceso al herbario ficticio. Las visitas se anotan en el libro de recepción."),
    ("Decreto 758 de 2019", "DECRETO 758 DE 2019", "national_norm",
     "Consulta del archivo ficticio de grabados. El préstamo queda registrado."),
]


@pytest.fixture
def corpus(tmp_path):
    library = SourceLibrary(tmp_path / "copy-auth-scope", PDFExtractor())
    library.save_collection({"id": "copy-auth-scope", "title": "Fuentes ficticias de alcance"})
    library.link_collections("copy-auth-case", ["copy-auth-scope"])
    ids = []
    for title, header, category, body in DOCUMENTS:
        saved = library.add(
            title + ".txt", (header + "\n" + body).encode(), title=title,
            category=category, origin="Documento ficticio nuevo para pruebas de software",
            collection_id="copy-auth-scope",
        )
        ids.append(saved["id"])
    _, chunks = library.snapshot("copy-auth-case")
    sources = [next(row for row in chunks if row["source_id"] == sid) for sid in ids]
    assert all(source["validity"] == "unknown" for source in sources)
    return sources


def request_for(source, suffix=""):
    return {
        "id": "COPYAUTH-P1", "case_id": "copy-auth-case",
        "title": "Copia y comprobación documental",
        "description": f"Adjunte copia certificada de {source['title']}. {suffix}".strip(),
        "allowed_collection_ids": ["copy-auth-scope"], "context": {},
    }


def gap(source, reason="source_identity", *, basis="content_gap", **changes):
    return {
        "kind": "clarification", "reason_code": reason, "basis": basis,
        "stage": "evidence", "source_chunk_ids": [source["chunk_id"]],
        "description": "Contrastar la firma del ejemplar con la identidad de quien lo suscribió.",
        "affected_claim": "La firma del ejemplar corresponde a la persona "
                          "identificada en el sello.",
        "why_unresolved": "No consta el cotejo de la firma con el registro de expedición.",
        **changes,
    }


def materialize(source, request, missing=()):
    selected = _SourceSelection.model_validate({
        "status": "references_found", "summary": "La copia se encuentra en la biblioteca.",
        "supports": [{"chunk_id": source["chunk_id"], "role": "document",
                      "reason": "El encabezado identifica la copia solicitada."}],
        "missing": list(missing), "warnings": [], "coverage_complete": True,
        "coverage": [{
            "aspect": "Archivo disponible", "claim": "Se conserva el ejemplar solicitado.",
            "use": "document_delivery",
            "application": {"status": "not_requested", "uncertainty_indexes": [],
                            "explanation": "La selección identifica la copia disponible."},
            "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
            "explanation": "La disponibilidad no acredita cotejo, certificación ni envío.",
        }],
    })
    return OpenAISourceAssessor._materialize(selected, request, [source])


def validity_checks(result):
    return [row for row in result["missing"] if row["reason_code"] == "validity"]


def assert_preserved_evidence_and_duties(result, source):
    assert result["supports"][0]["quote"] == source["quote"]
    assert result["supports"][0]["sha256"] == source["sha256"]
    state = result["sufficiency"]["document_states"][source["source_id"]]
    assert state["availability"] == "identified_copy"
    assert state["authenticity"] == "not_inferred_from_availability"
    assert state["delivery"] == "pending"
    assert any(row["reason_code"] == "document_delivery" for row in result["actions"])
    assert all(row["resolution"] == {"status": "open"} for row in result["actions"])
    assert all(not row["blocks_approval"] for row in result["actions"])
    assert result["verifications"] == []


@pytest.mark.parametrize("document_index,suffix", [
    (0, "Confirme si la firma corresponde a la persona indicada en el sello."),
    (1, "Indique a qué persona corresponde la firma del ejemplar."),
    (2, "Identifique a quien suscribió el documento."),
    (0, "Identifique el registro de ingreso y su trazabilidad."),
    (1, "Informe qué cadena de custodia tiene el archivo conservado."),
    (2, "Precise de qué registro procede el documento y cómo llegó al archivo."),
    (0, "Confirme si el sello corresponde al archivo que conservó la copia."),
    (1, "Determine si la firma del archivo es auténtica."),
])
def test_copy_and_authentication_do_not_create_legal_effect_question(
    corpus, document_index, suffix,
):
    source = corpus[document_index]
    before = deepcopy(source)
    concrete = gap(source)
    result = materialize(source, request_for(source, suffix), [concrete])
    assert validity_checks(result) == []
    assert result["sufficiency"]["copy_without_legal_application"] is True
    assert any(row["description"] == concrete["description"]
               and row["affected_claim"] == concrete["affected_claim"]
               and row["resolution"] == {"status": "open"}
               and row["blocks_approval"] for row in result["missing"])
    assert any(row["decision"] == "non_blocking_metadata"
               and row["original"]["reason_code"] == "validity"
               for row in result["gap_decisions"])
    assert_preserved_evidence_and_duties(result, source)
    assert source == before


@pytest.mark.parametrize("document_index,suffix", [
    (0, "Confirme si me corresponde el préstamo previsto en la norma."),
    (1, "Indique si puedo ingresar al herbario al amparo de la resolución."),
    (2, "Confirme si tengo derecho a consultar el archivo según el decreto."),
    (0, "Indique si la disposición aplica a mi solicitud."),
    (1, "Explique los efectos jurídicos de la resolución sobre mi caso."),
    (2, "Confirme la vigencia del decreto."),
    (0, "Determine si la circular regía durante el año 2024."),
    (1, "Explique si debo obtener una autorización con arreglo a esa resolución."),
    (2, "Confirme si sus requisitos siguen siendo obligatorios."),
    (0, "Verifique a quién corresponde firmar la resolución según el reglamento."),
    (1, "Verifique si la firma corresponde según la norma al funcionario competente."),
    (2, "Verifique la firma, la competencia del firmante para dictar la resolución."),
    (0, "Confirme si la firma del documento corresponde al rector según el estatuto."),
    (1, "Confirme si la firma de la resolución corresponde al director."),
    (2, "Verifique la firma, la ejecución del trámite."),
])
def test_legal_question_keeps_validity_despite_reader_copy_label(corpus, document_index, suffix):
    source = corpus[document_index]
    result = materialize(source, request_for(source, suffix))
    assert validity_checks(result)
    assert result["sufficiency"]["copy_without_legal_application"] is False
    assert all(row["resolution"] == {"status": "open"} for row in validity_checks(result))
    assert_preserved_evidence_and_duties(result, source)


@pytest.mark.parametrize("scope,legal", [
    ("parent", False), ("parent", True),
    ("common", False), ("common", True), ("sibling", False),
])
def test_authentication_and_legal_scope_follow_parent_or_common_instruction(corpus, scope, legal):
    source = corpus[0]
    request = request_for(source)
    common = ("Para cada copia, confirme si me corresponde el derecho previsto en la norma."
              if legal else "Para cada copia, confirme si la firma corresponde a su suscriptor.")
    if scope == "sibling":
        common = "Peticiones independientes."
        request["description"] += " Confirme si la firma corresponde a su suscriptor."
    if scope == "parent":
        request["context"] = {"ancestors": [{"id": "parent", "description": common}]}
    else:
        request["context"] = {"document_context": {
            "origin": "original_petition", "truncated": False,
            "excerpts": [{"page": 1, "line_start": 1, "line_end": 3,
                          "quote": common + "\n" + request["description"]
                          + "\nConfirme si otra norma está vigente."}],
            "question_ranges": [
                {"request_id": "COPYAUTH-P1", "page": 1, "line_start": 2, "line_end": 2},
                {"request_id": "COPYAUTH-P2", "page": 1, "line_start": 3, "line_end": 3},
            ],
        }}
    result = materialize(source, request, [gap(source)])
    assert bool(validity_checks(result)) is legal
    assert_preserved_evidence_and_duties(result, source)


@pytest.mark.parametrize("basis", ["metadata_only", "content_gap", "contradiction"])
def test_only_catalog_validity_is_waived_not_concrete_legal_discrepancy(corpus, basis):
    source = corpus[1]
    request = request_for(source, "Confirme si la firma corresponde a su suscriptor.")
    concrete = gap(
        source, "validity", basis=basis,
        description="Cotejar la derogación parcial consignada en el registro normativo.",
        affected_claim="La disposición rige en el periodo señalado por el registro.",
        why_unresolved="El texto del archivo difiere del asiento de derogación parcial.",
    )
    result = materialize(source, request, [concrete])
    if basis == "metadata_only":
        assert validity_checks(result) == []
    else:
        assert len(validity_checks(result)) == 1
        retained = validity_checks(result)[0]
        assert retained["description"] == concrete["description"]
        assert retained["affected_claim"] == concrete["affected_claim"]
        assert retained["basis"] == basis
        assert retained["resolution"] == {"status": "open"}
        assert retained["blocks_approval"]
    assert_preserved_evidence_and_duties(result, source)


def test_transcription_check_survives_copy_authentication_scope(corpus):
    source = corpus[2]
    request = request_for(source, "Indique a quién corresponde la firma del ejemplar.")
    transcription = gap(
        source, "transcription",
        description="Cotejar la lectura del apellido en el sello con la página original.",
        affected_claim="El apellido transcrito corresponde al sello del ejemplar.",
        why_unresolved="La imagen no permite distinguir dos letras del apellido.",
    )
    result = materialize(source, request, [transcription])
    assert validity_checks(result) == []
    assert any(row["reason_code"] == "transcription"
               and row["description"] == transcription["description"]
               and row["resolution"] == {"status": "open"} for row in result["missing"])
    assert_preserved_evidence_and_duties(result, source)


@pytest.mark.parametrize("issue_certification", [False, True])
def test_copy_authentication_keeps_future_certification_and_delivery(corpus, issue_certification):
    source = corpus[2]
    request = request_for(source, "Confirme si la firma corresponde a la persona indicada.")
    if issue_certification:
        request["description"] += " Expida una certificación de autenticidad de esa copia."
    result = materialize(source, request, [gap(source)])
    assert validity_checks(result) == []
    assert_preserved_evidence_and_duties(result, source)
    assert any(row["blocks_approval"] for row in result["missing"])
    if issue_certification:
        assert any(row["reason_code"] == "certification_preparation"
                   and row["resolution"] == {"status": "open"} for row in result["actions"])


@pytest.mark.parametrize("context", [
    {"truncated": True},
    {"document_context": {"truncated": True, "excerpts": []}},
])
def test_incomplete_context_cannot_establish_absence_of_legal_question(corpus, context):
    source = corpus[1]
    request = request_for(source, "Confirme si la firma corresponde al suscriptor.")
    request["context"] = context
    result = materialize(source, request)
    assert validity_checks(result)
    assert result["sufficiency"]["copy_without_legal_application"] is False
    assert_preserved_evidence_and_duties(result, source)
