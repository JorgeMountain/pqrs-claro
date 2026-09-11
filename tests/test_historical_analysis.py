"""Antecedentes ficticios: alcance, atribución y reutilización sin hechos inventados."""

from types import SimpleNamespace

import pytest

from pqrs_claro.models import DomainError
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.source_retrieval import retrieve


def inquiry(**changes):
    return {
        "id": "P1",
        "title": "Decisión del comité de prácticas",
        "description": "Explique la decisión del comité de prácticas sobre la plaza.",
        "case_id": "nuevo-caso",
        "allowed_collection_ids": ["historia-equipo"],
        **changes,
    }


def historical(**changes):
    return {
        "chunk_id": "respuesta:1",
        "source_id": "respuesta-v1",
        "document_id": "respuesta",
        "version": 1,
        "title": "Oficio 0123 del comité de prácticas",
        "category": "historical_response",
        "case_id": None,
        "collection_id": "historia-equipo",
        "historical_group": "HISTORIA-01",
        "radicados": ["FICTICIO-123"],
        "document_status": "issued",
        "verification_status": "documented",
        "verification_note": "Secretaría ficticia cotejó el oficio y el acta el 2 de agosto.",
        "related_source_ids": ["acta-v1"],
        "filename": "oficio_0123.pdf",
        "origin": "Corpus ficticio, secretaría del comité.",
        "review_status": "reviewed",
        "validity": "not_applicable",
        "page": 1,
        "line_start": 1,
        "line_end": 2,
        "quote": (
            "El comité de prácticas aprobó la plaza en la sesión anterior.\nSe menciona el acta."
        ),
        "method": "native",
        "needs_review": False,
        **changes,
    }


def choice(role="antecedent", **changes):
    return _SourceSelection.model_validate(
        {
            "status": "references_found",
            "summary": "Se localizó el antecedente sobre la decisión del comité.",
            "missing": [],
            "supports": [
                {
                    "chunk_id": "respuesta:1",
                    "reason": "Permite consultar qué se respondió en el trámite anterior.",
                    "role": role,
                }
            ],
            "warnings": [],
            **changes,
        }
    )


def materialize(source=None, request=None, proposed=None):
    return OpenAISourceAssessor._materialize(
        proposed or choice(), request or inquiry(), [source or historical()]
    )


def missing_content(result):
    return [{key: item[key] for key in ("kind", "description")} for item in result["missing"]]


def test_retrieval_accepts_linked_history_but_keeps_legacy_style_excluded():
    sources = [
        historical(),
        historical(chunk_id="peticion:1", category="historical_petition", document_id="p"),
        historical(chunk_id="anexo:1", category="historical_attachment", document_id="a"),
        historical(chunk_id="estilo:1", category="previous_response", document_id="e"),
    ]
    results = retrieve(inquiry(), sources)
    assert {source["chunk_id"] for source in results} == {"respuesta:1", "peticion:1", "anexo:1"}
    assert results[0]["quote"] == sources[0]["quote"]


@pytest.mark.parametrize(
    "source_changes,request_changes",
    [
        ({"collection_id": "otra-coleccion"}, {}),
        ({"collection_id": None}, {}),
        ({}, {"allowed_collection_ids": []}),
        ({}, {"allowed_collection_ids": "historia-equipo"}),
        ({"case_id": "caso-ajeno"}, {}),
        ({"validity": "superseded"}, {}),
    ],
)
def test_retrieval_excludes_unlinked_missing_or_malformed_scope(source_changes, request_changes):
    assert retrieve(inquiry(**request_changes), [historical(**source_changes)]) == []


def test_norms_in_historical_collection_require_linking_too():
    norm = historical(category="institutional_norm", validity="current")
    assert retrieve(inquiry(allowed_collection_ids=[]), [norm]) == []
    assert retrieve(inquiry(), [norm])[0]["chunk_id"] == norm["chunk_id"]
    result = materialize(norm, proposed=choice(role="rule"))
    assert result["supports"][0]["role"] == "rule"


def test_response_reuses_exact_attributed_content_without_becoming_current_fact():
    original = historical()
    result = materialize(original)
    support = result["supports"][0]
    for key in ("quote", "source_id", "historical_group", "radicados", "related_source_ids"):
        assert support[key] == original[key]
    assert support["role"] == "antecedent"
    assert result["status"] == "references_found"
    assert result["evidence_states"] == ["support_found"]
    assert result["missing"] == []
    assert not any("quién verificó" in item["description"] for item in result["missing"])
    assert any("anexos mencionados" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    "category,role",
    [
        ("historical_response", "fact"),
        ("historical_response", "document"),
        ("historical_petition", "fact"),
        ("historical_petition", "historical_evidence"),
        ("historical_attachment", "fact"),
        ("case_evidence", "antecedent"),
    ],
)
def test_historical_content_cannot_silently_become_current_fact_or_actual_file(category, role):
    with pytest.raises(DomainError, match="tipo de fuente"):
        materialize(historical(category=category), proposed=choice(role=role))


def test_petition_is_context_not_proof_of_an_answer_or_an_allegation():
    result = materialize(historical(category="historical_petition"))
    assert result["supports"][0]["role"] == "antecedent"
    assert any("preguntas o afirmaciones" in warning for warning in result["warnings"])
    assert any("ni que fueran respondidos" in warning for warning in result["warnings"])


def test_reported_verification_is_recorded_as_reported_and_does_not_count_as_review():
    source = historical(
        verification_status="reported_by_user",
        review_status="pending",
        verification_note="El usuario informa que anteriormente fue verificado.",
    )
    result = materialize(source)
    missing = " ".join(item["description"] for item in result["missing"])
    assert "persona y periodo" not in missing
    assert "Revisar la procedencia y el contenido" not in missing
    assert "Documentar quién verificó" not in missing
    assert any("fue informada por el usuario" in warning for warning in result["warnings"])
    assert any("sin exigir repetir" in warning for warning in result["warnings"])
    assert result["supports"][0]["verification_status"] == "reported_by_user"
    assert result["supports"][0]["review_status"] == "pending"
    assert result["verifications"] == []


def test_unselected_named_file_is_located_for_review_without_becoming_support():
    existing = historical(
        chunk_id="oficio:4", source_id="oficio-v2", document_id="oficio", version=2,
        title="Oficio 765", filename="Oficio_765-2024.pdf", page=4,
        quote="La revisión del semestre anterior contiene un alcance específico.",
    )
    proposed = choice(
        status="needs_evidence",
        summary="No se localizó una copia del oficio 765-2024 para contrastar la información.",
        missing=[
            {"kind": "document", "description": "Aportar el oficio 765-2024, no localizado."},
            {"kind": "document", "description": "Aportar los planes de trabajo de 2010."},
        ],
        warnings=["No se encontró el oficio 765-2024."],
    )
    result = OpenAISourceAssessor._materialize(proposed, inquiry(), [historical(), existing])
    assert [source["source_id"] for source in result["supports"]] == ["respuesta-v1"]
    assert "No se localizó" not in result["summary"]
    assert result["missing"][0]["kind"] == "clarification"
    assert result["missing"][0]["linked_source_ids"] == ["oficio-v2"]
    assert result["missing"][0]["linked_chunk_ids"] == ["oficio:4"]
    assert result["missing"][1]["description"] == "Aportar los planes de trabajo de 2010."
    assert "no encontrado" not in " ".join(result["warnings"])
    candidate = result["candidate_documents"][1]
    assert candidate["selected_as_support"] is False
    assert candidate["version"] == 2
    assert candidate["chunks"][0]["quote"] == existing["quote"]
    assert candidate["chunks"][0]["page"] == 4
    assert result["selection_status"] == "additional_candidates_available"


def test_additional_candidates_are_visible_without_forcing_support_or_pending_item():
    other = historical(
        chunk_id="otro:1", source_id="otro-v1", document_id="otro",
        title="Oficio 555", filename="oficio_555.pdf", quote="Otro asunto y otro periodo.",
    )
    one = materialize()
    result = OpenAISourceAssessor._materialize(choice(), inquiry(), [historical(), other])
    assert result["supports"] == one["supports"]
    assert result["missing"] == one["missing"]
    assert len(result["candidate_documents"]) == 2
    assert result["selection_status"] == "additional_candidates_available"


@pytest.mark.parametrize("name,category", [
    ("Correo de remision oficio 765-2024.pdf", "historical_attachment"),
    ("Notificacion oficio 765-2024.pdf", "historical_attachment"),
    ("Oficio_765-2025.pdf", "historical_response"),
    ("Peticion sobre oficio 765-2024.pdf", "historical_petition"),
])
def test_reference_or_different_year_does_not_cancel_a_missing_original(name, category):
    pending = {"kind": "document", "description": "Aportar el oficio 765-2024."}
    source = historical(filename=name, category=category)
    role = "historical_evidence" if category == "historical_attachment" else "antecedent"
    result = materialize(source, proposed=choice(role=role, missing=[pending]))
    assert pending in missing_content(result)
    item = next(item for item in result["missing"] if item["description"] == pending["description"])
    assert item["linked_source_ids"] == []
    assert item["state"] == "confirmation_pending"
    assert item["reason_code"] == "search_incomplete"


def test_copy_request_with_known_unselected_file_needs_identity_check_not_another_upload():
    source = historical(title="Oficio 765", filename="oficio_765.pdf")
    result = materialize(
        source,
        inquiry(title="Copia de oficio", description="Solicito copia del oficio 765."),
        choice(supports=[]),
    )
    assert result["supports"] == []
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert any("candidato ya localizado" in item["description"] for item in result["missing"])


def test_draft_candidate_does_not_cancel_request_for_the_issued_version():
    pending = {"kind": "document", "description": "Aportar la versión expedida del oficio 765."}
    source = historical(filename="Oficio_765.pdf", document_status="draft")
    result = materialize(source, proposed=choice(missing=[pending]))
    assert pending in missing_content(result)
    issued = [item for item in result["missing"] if item["reason_code"] == "issued_version"]
    assert len(issued) == 1
    assert issued[0]["linked_source_ids"] == [source["source_id"]]
    assert issued[0]["resolution"]["status"] == "open"
    assert issued[0]["blocks_approval"] is True
    assert result["supports"][0]["document_status"] == "draft"
    assert any("es un borrador" in warning for warning in result["warnings"])


def test_reconciliation_preserves_another_missing_numbered_document_in_same_item():
    source = historical(filename="Oficio_765-2024.pdf")
    result = materialize(source, proposed=choice(missing=[{
        "kind": "document", "description": "Aportar el oficio 765-2024 y el acta 789."
    }]))
    assert any(item["kind"] == "clarification" and item.get("linked_source_ids")
               for item in result["missing"])
    assert any(item["kind"] == "document" and "acta 789" in item["description"]
               for item in result["missing"])


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"document_status": "draft"}, "es un borrador"),
        ({"document_status": "unknown"}, "versión expedida o a un documento de trabajo"),
        ({"filename": "Oficio_XXXX-2026.pdf", "document_status": "issued"}, "es un borrador"),
        ({"verification_status": "pending", "review_status": "pending"},
         "Revisar la procedencia y el contenido"),
    ],
)
def test_drafts_and_unreviewed_provenance_stay_visible(changes, expected):
    result = materialize(historical(**changes))
    assert result["status"] == "needs_evidence"
    assert any(expected in item["description"] for item in result["missing"])


def test_partial_extraction_blocks_requested_complete_copy_but_not_a_readable_passage():
    source = historical(extraction_status="partial")
    partial = materialize(source)
    assert partial["supports"][0]["extraction_status"] == "partial"
    assert partial["missing"] == []
    request = inquiry(description="Solicito copia íntegra del oficio 0123.")
    complete_copy = materialize(source, request)
    checks = [
        item for item in complete_copy["missing"] if item["reason_code"] == "extraction_error"
    ]
    assert len(checks) == 1 and checks[0]["state"] == "analysis_error"
    assert checks[0]["linked_source_ids"] == [source["source_id"]]
    assert "extracción es parcial" in checks[0]["description"]


@pytest.mark.parametrize("changes", [
    {"verification_status": "pending"}, {"verification_note": ""},
])
def test_generic_review_metadata_never_invents_fact_verification_or_an_extra_gap(changes):
    source = historical(**changes)
    result = materialize(source)
    assert result["supports"][0]["review_status"] == "reviewed"
    assert result["missing"] == []
    assert result["verifications"] == []
    for key, value in changes.items():
        assert result["supports"][0][key] == value


def test_concrete_different_period_requires_check_even_when_antecedent_is_verified():
    pending = {
        "kind": "clarification",
        "description": (
            "Confirmar si la conclusión del Oficio 0123 del comité de prácticas, "
            "documentada para 2015-1, aplica a la designación diferente de 2019-2."
        ),
    }
    source = historical(quote="En el semestre 2015-1 el comité aprobó la plaza.")
    request = inquiry(description="Explique la designación del semestre 2019-2.")
    result = materialize(source, request, choice(missing=[pending]))
    assert pending in missing_content(result)
    assert result["evidence_states"] == ["support_found", "confirmation_pending"]
    item = next(item for item in result["missing"] if item["description"] == pending["description"])
    assert item["linked_source_ids"] == [source["source_id"]]
    assert item["scope_key"] != "document"
    assert item["request_ids"] == ["P1"]
    assert item["resolution"]["status"] == "open"
    assert result["supports"][0]["role"] == "antecedent"


def test_response_mentioning_an_acta_and_relation_to_file_does_not_supply_the_file():
    request = inquiry(title="Copia del acta", description="Solicito copia del acta de prácticas.")
    result = materialize(request=request)
    assert any(item["kind"] == "document" for item in result["missing"])
    assert result["supports"][0]["related_source_ids"] == ["acta-v1"]
    assert any("no sustituye" in warning for warning in result["warnings"])


def test_actual_historical_attachment_locates_copy_and_keeps_future_delivery_visible():
    request = inquiry(title="Copia del acta", description="Solicito copia del acta de prácticas.")
    source = historical(
        category="historical_attachment",
        title="Acta del comité de prácticas",
        filename="acta.pdf",
        quote="ACTA 1. El comité aprobó la plaza.",
    )
    result = materialize(source, request, choice(role="document"))
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert result["missing"] == []
    assert result["evidence_states"] == ["support_found"]
    assert any(item["reason_code"] == "document_delivery" for item in result["actions"])
    assert any("ni entrega de documentos" in warning for warning in result["warnings"])


def test_historical_evidence_role_is_distinct_from_locating_a_requested_document():
    request = inquiry(title="Copia del acta", description="Solicito copia del acta de prácticas.")
    source = historical(category="historical_attachment")
    result = materialize(source, request, choice(role="historical_evidence"))
    assert result["supports"][0]["role"] == "historical_evidence"
    assert any(item["kind"] == "document" for item in result["missing"])


@pytest.mark.parametrize(
    "description",
    [
        "Solicito copia del documento que contiene el acta 2212 del consejo.",
        "Adjunte el documento correspondiente al acta2212 del consejo.",
        "Solicito copia del acta 2212 del consejo.",
    ],
)
def test_email_mention_cannot_locate_the_acta_even_inside_generic_document_wording(description):
    source = historical(
        category="historical_attachment",
        title="Notificación del consejo",
        filename="notificacion.pdf",
        quote="1 mensaje\nPara: destinatario@example.test\nSe menciona el acta 2212 del consejo.",
    )
    result = materialize(
        source,
        inquiry(title="Copia del documento", description=description),
        choice(role="document"),
    )
    assert result["supports"][0]["role"] == "historical_evidence"
    assert result["supports"][0]["quote"] == source["quote"]
    assert any(item["kind"] == "document" for item in result["missing"])
    assert "no permite identificar" in result["supports"][0]["reason"]
    assert result["status"] == "needs_evidence"


@pytest.mark.parametrize(
    "title,quote",
    [
        ("Acta 2212 del consejo", "El oficio hace referencia al acta 2212 del consejo."),
        ("Acta 2213 del consejo", "ACTA 2213 DEL CONSEJO\nSe menciona el acta 2212 anterior."),
    ],
)
def test_document_title_or_mention_does_not_replace_corresponding_identity(title, quote):
    source = historical(
        category="historical_attachment", title=title, filename="anexo.pdf", quote=quote
    )
    result = materialize(
        source,
        inquiry(title="Copia del acta", description="Solicito copia del acta 2212."),
        choice(role="document"),
    )
    assert result["supports"][0]["role"] != "document"
    assert any(item["kind"] == "document" for item in result["missing"])


def test_copy_of_the_requested_historical_office_is_located_without_certifying_issuance():
    source = historical(
        title="Oficio 1436 Respuesta a petición ficticia",
        filename="Oficio_1436.pdf",
        quote=(
            "21360001-1436-2024\nAsunto: Respuesta a petición ficticia.\n"
            "Se recibió una comunicación por correo electrónico."
        ),
        document_status="unknown",
        verification_status="pending",
        review_status="pending",
    )
    result = materialize(
        source,
        inquiry(
            title="Copia del oficio", description="Solicito copia del oficio 21360001-1436-2024."
        ),
        choice(role="document"),
    )
    assert result["supports"][0]["role"] == "document"
    assert result["supports"][0]["quote"] == source["quote"]
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert any("versión expedida" in item["description"] for item in result["missing"])
    assert any(item["reason_code"] == "provenance" for item in result["missing"])
    assert len([item for item in result["missing"] if item["reason_code"] == "provenance"]) == 1
    assert any("ni entrega de documentos" in warning for warning in result["warnings"])
    assert result["status"] == "needs_evidence"


def test_same_office_number_in_another_year_does_not_match_a_mention_of_the_requested_one():
    source = historical(
        title="Oficio 1436-2025",
        filename="oficio_1436_2025.pdf",
        quote="21360001-1436-2025\nEste oficio menciona el anterior 21360001-1436-2024.",
    )
    result = materialize(
        source,
        inquiry(title="Copia del oficio", description="Adjunte el oficio 21360001-1436-2024."),
        choice(role="document"),
    )
    assert result["supports"][0]["role"] == "antecedent"
    assert any(item["kind"] == "document" for item in result["missing"])


def notification_email():
    return historical(
        category="historical_attachment",
        title="Anexo 2 NOTIFICACIÓN Oficio 21360001-1436-2024",
        filename="notificacion_oficio_1436.pdf",
        quote=(
            "NOTIFICACIÓN PERSONAL POR MEDIO ELECTRÓNICO\n1 mensaje\n"
            "Para: destinatario@example.test\nSe adjunta el oficio 21360001-1436-2024."
        ),
        document_status="unknown",
        review_status="pending",
    )


def test_email_itself_can_be_located_when_it_is_the_requested_object():
    result = materialize(
        notification_email(),
        inquiry(
            title="Correo de remisión",
            description="Adjunte copia del correo de remisión del oficio 21360001-1436-2024.",
        ),
        choice(role="document"),
    )
    assert result["supports"][0]["role"] == "document"
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert any("ni entrega de documentos" in warning for warning in result["warnings"])
    assert result["status"] == "references_found"
    assert result["missing"] == []
    assert any(item["reason_code"] == "document_delivery" for item in result["actions"])


def test_the_same_email_does_not_locate_the_office_attached_to_it():
    result = materialize(
        notification_email(),
        inquiry(title="Copia del oficio", description="Adjunte el oficio 21360001-1436-2024."),
        choice(role="document"),
    )
    assert result["supports"][0]["role"] == "historical_evidence"
    assert any(item["kind"] == "document" for item in result["missing"])


@pytest.mark.parametrize(
    "description",
    [
        "Solicitar al Secretario General que certifique la titularidad docente durante 2015.",
        "Obtener una certificación del Secretario General sobre la titularidad durante 2015.",
        "Solicito expedir un certificado sobre la titularidad docente durante 2015.",
        "Solicito emitir una certificación sobre la titularidad docente durante 2015.",
    ],
)
def test_request_to_certify_keeps_future_issuance_separate_from_evidence(description):
    source = historical(quote="El oficio afirma que existía soporte de titularidad en 2015-1.")
    result = materialize(source, inquiry(title="Titularidad docente", description=description))
    certificates = [
        item for item in result["actions"]
        if item["reason_code"] == "certification_preparation"
    ]
    assert len(certificates) == 1
    assert certificates[0]["request_ids"] == ["P1"]
    assert "autoridad competente" in certificates[0]["description"]
    assert certificates[0]["stage"] == "fulfillment"
    assert certificates[0]["blocks_approval"] is False
    assert certificates[0]["resolution"]["status"] == "open"
    assert result["supports"][0]["role"] == "antecedent"
    assert result["missing"] == []
    assert result["status"] == "references_found"


def test_request_only_to_explain_the_historical_fact_does_not_demand_a_new_certificate():
    result = materialize(
        request=inquiry(
            title="Titularidad docente", description="Explique quién fue el docente durante 2015-1."
        )
    )
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert result["supports"][0]["role"] == "antecedent"


def test_located_prior_certificate_does_not_claim_a_new_certification_was_issued():
    source = historical(
        category="historical_attachment",
        title="Certificación de titularidad docente",
        filename="certificacion.pdf",
        quote="CERTIFICACIÓN DE TITULARIDAD DOCENTE\nContenido ficticio referido a 2015-1.",
    )
    result = materialize(
        source,
        inquiry(title="Certificación", description="Solicito certificar la titularidad en 2015-1."),
        choice(role="document"),
    )
    assert result["supports"][0]["role"] == "document"
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert result["missing"] == []
    assert len(result["actions"]) == 1
    assert result["actions"][0]["reason_code"] == "certification_preparation"
    assert result["actions"][0]["resolution"]["status"] == "open"
    assert result["status"] == "references_found"


def test_assessor_checks_scope_before_transmitting_any_content_to_provider():
    calls = []
    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **kwargs: calls.append(kwargs))
    )
    with pytest.raises(DomainError, match="no vinculado"):
        assessor.assess(inquiry(allowed_collection_ids=[]), [historical()])
    assert calls == []
    with pytest.raises(DomainError, match="no está vinculada"):
        materialize(request=inquiry(allowed_collection_ids=[]))
