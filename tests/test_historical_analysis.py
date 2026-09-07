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
    assert result["status"] == "needs_evidence"
    assert any("persona y periodo" in item["description"] for item in result["missing"])
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
    assert "solo fue informada por el usuario" in missing
    assert "procedencia" in missing
    assert result["supports"][0]["verification_status"] == "reported_by_user"


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"document_status": "draft"}, "es un borrador"),
        ({"document_status": "unknown"}, "versión expedida o a un documento de trabajo"),
        ({"filename": "Oficio_XXXX-2026.pdf", "document_status": "issued"}, "es un borrador"),
        ({"verification_status": "pending"}, "Documentar quién verificó"),
        ({"verification_note": ""}, "Completar el registro de verificación"),
        ({"extraction_status": "partial"}, "extracción es parcial"),
    ],
)
def test_drafts_unknown_verification_and_partial_extraction_stay_visible(changes, expected):
    result = materialize(historical(**changes))
    assert result["status"] == "needs_evidence"
    assert any(expected in item["description"] for item in result["missing"])


def test_response_mentioning_an_acta_and_relation_to_file_does_not_supply_the_file():
    request = inquiry(title="Copia del acta", description="Solicito copia del acta de prácticas.")
    result = materialize(request=request)
    assert any(item["kind"] == "document" for item in result["missing"])
    assert result["supports"][0]["related_source_ids"] == ["acta-v1"]
    assert any("no sustituye" in warning for warning in result["warnings"])


def test_actual_historical_attachment_can_locate_copy_but_needs_correspondence_check():
    request = inquiry(title="Copia del acta", description="Solicito copia del acta de prácticas.")
    source = historical(
        category="historical_attachment",
        title="Acta del comité de prácticas",
        filename="acta.pdf",
        quote="ACTA 1. El comité aprobó la plaza.",
    )
    result = materialize(source, request, choice(role="document"))
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert any("persona y periodo" in item["description"] for item in result["missing"])
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
    assert any("Documentar quién verificó" in item["description"] for item in result["missing"])
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
    assert result["status"] == "needs_evidence"


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
def test_request_to_certify_keeps_certificate_pending_beyond_the_historical_finding(description):
    source = historical(quote="El oficio afirma que existía soporte de titularidad en 2015-1.")
    result = materialize(source, inquiry(title="Titularidad docente", description=description))
    certificates = [
        item for item in result["missing"]
        if item["kind"] == "document" and "certificación" in item["description"]
    ]
    assert len(certificates) == 1
    assert description in certificates[0]["description"]
    assert "confirmar institucionalmente quién puede expedirla" in certificates[0]["description"]
    assert result["supports"][0]["role"] == "antecedent"
    assert result["status"] == "needs_evidence"


def test_request_only_to_explain_the_historical_fact_does_not_demand_a_new_certificate():
    result = materialize(
        request=inquiry(
            title="Titularidad docente", description="Explique quién fue el docente durante 2015-1."
        )
    )
    assert not any(item["kind"] == "document" for item in result["missing"])
    assert result["supports"][0]["role"] == "antecedent"


def test_located_certificate_remains_subject_to_review_without_requesting_it_again():
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
    assert any("persona y periodo" in item["description"] for item in result["missing"])
    assert result["status"] == "needs_evidence"


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
