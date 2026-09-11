from copy import deepcopy

import pytest

from pqrs_claro.evidence_contract import (
    apply_evidence_contract,
    catalog_audit,
    group_checks,
    normalize_pending,
)


def request(id="P1", description="Explique la conclusión sobre el periodo 2015."):
    return {
        "id": id,
        "description": description,
        "context": {},
        "allowed_collection_ids": ["history"],
    }


def source(**changes):
    return {
        "source_id": "one",
        "id": "one",
        "document_id": "office",
        "version": 1,
        "sha256": "original",
        "extraction_revision": 1,
        "filename": "Oficio 1436-2024.pdf",
        "title": "Oficio 1436-2024",
        "category": "historical_response",
        "collection_id": "history",
        "extraction_status": "ready",
        "quote": "Conclusión.",
        **changes,
    }


def finding(missing=(), supports=None):
    return {
        "request_id": "P1",
        "status": "needs_evidence",
        "supports": supports or [source()],
        "missing": list(missing),
        "warnings": [],
    }


def application(check, request_ids):
    document = source()
    return {
        "id": "app",
        "case_id": "case",
        "verification_id": "human",
        "check_key": check["check_key"],
        "request_ids": request_ids,
        "basis": "Cotejo de esta versión para las preguntas indicadas.",
        "check_reason": check["reason_code"],
        "scope_key": check["scope_key"],
        "record": {
            "id": "human",
            "kind": "human_review",
            "case_id": "case",
            "fact": "La versión fue cotejada con su original.",
            "basis": "Cotejo documental.",
            "recorded_by": "Responsable ficticio",
            "recorded_at": "2026-01-01T00:00:00Z",
            "recording_method": "human_form",
            "source_id": document["source_id"],
            "document_id": document["document_id"],
            "version": document["version"],
            "source_sha256": document["sha256"],
            "extraction_revision": document["extraction_revision"],
            "passage": {
                "chunk_id": "one:1:1:1",
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "quote": document["quote"],
            },
        },
    }


def test_found_support_and_unconfirmed_fact_coexist():
    result = apply_evidence_contract(
        request(),
        finding([{"kind": "fact", "description": "Confirmar si el periodo corresponde a 2015."}]),
    )
    assert result["evidence_states"] == ["support_found", "confirmation_pending"]
    assert result["missing"][0]["scope_key"] != "document"


def test_shared_document_check_has_one_identity_but_per_question_application():
    raw = {
        "kind": "clarification",
        "description": "Comprobar la versión expedida de «Oficio 1436-2024».",
    }
    first = apply_evidence_contract(request(), finding([raw]))
    second = apply_evidence_contract(request("P2"), {**finding([raw]), "request_id": "P2"})
    assert first["checks"][0]["check_key"] == second["checks"][0]["check_key"]
    groups = group_checks([first, second])
    assert len(groups) == 1 and groups[0]["request_ids"] == ["P1", "P2"]
    recorded = application(groups[0], ["P1"])
    applied = apply_evidence_contract(request(), first, applications=[recorded])
    unapplied = apply_evidence_contract(request("P2"), second, applications=[recorded])
    assert applied["missing"] == []
    assert len(unapplied["missing"]) == 1


def test_change_of_source_version_reopens_check():
    raw = {
        "kind": "clarification",
        "description": "Comprobar la versión expedida de «Oficio 1436-2024».",
    }
    first = apply_evidence_contract(request(), finding([raw]))
    recorded = application(first["checks"][0], ["P1"])
    changed = apply_evidence_contract(
        request(), finding([raw], [source(version=2)]), applications=[recorded]
    )
    assert changed["missing"] and changed["checks"][0]["resolution"]["status"] == "open"


def test_question_specific_fact_checks_are_not_merged():
    raw = {"kind": "fact", "description": "Confirmar el periodo del nombramiento."}
    first = apply_evidence_contract(request(), finding([raw]))
    second = apply_evidence_contract(
        request("P2", "Confirme el nombramiento de 2019."), finding([raw])
    )
    assert first["checks"][0]["check_key"] != second["checks"][0]["check_key"]


def test_document_missing_requires_targeted_complete_local_catalog_search():
    inquiry = request(description="Entregue copia del acta 15.")
    proposed = finding([{"kind": "document", "description": "Localizar el acta 15."}])
    unsearched = apply_evidence_contract(inquiry, proposed)
    assert unsearched["missing"][0]["state"] == "confirmation_pending"
    scoped = catalog_audit(
        inquiry,
        proposed,
        [source()],
        chunks=[source(chunk_id="one:1:1:1", page=1, line_start=1, line_end=1)],
    )
    searched = apply_evidence_contract(scoped, proposed)
    assert searched["missing"][0]["state"] == "document_missing"
    assert searched["search_audit"]["external_systems_searched"] == []
    scoped["search_audit"]["access_limited"] = True
    limited = apply_evidence_contract(scoped, proposed)
    assert limited["missing"][0]["state"] == "confirmation_pending"


def test_unread_file_in_full_catalog_is_an_analysis_error_not_absent():
    inquiry = request(description="Entregue copia del oficio 1436-2024.")
    proposed = finding(
        [{"kind": "document", "description": "Aportar el oficio 1436-2024."}],
        supports=[source(source_id="other", filename="Oficio 999.pdf", title="Otra respuesta")],
    )
    scoped = catalog_audit(inquiry, proposed, [source(extraction_status="pending")])
    result = apply_evidence_contract(scoped, proposed)
    assert result["missing"][0]["state"] == "analysis_error"
    assert result["missing"][0]["linked_source_ids"] == ["one"]
    assert "conservado" in result["missing"][0]["description"]


def test_future_response_cannot_be_its_own_evidence_dependency():
    inquiry = request(description="Solicito que firme la respuesta a esta petición.")
    result = apply_evidence_contract(
        inquiry,
        finding([{"kind": "document", "description": "Aportar la respuesta final firmada."}]),
    )
    assert result["missing"] == []
    assert result["actions"]
    assert result["evidence_states"] == ["support_found"]


def test_past_delivery_receipt_remains_evidence_requirement():
    result = apply_evidence_contract(
        request(),
        finding(
            [
                {
                    "kind": "document",
                    "description": "Aportar el justificante de envío del oficio anterior.",
                }
            ]
        ),
    )
    assert len(result["missing"]) == 1 and not result["actions"]


@pytest.mark.parametrize("description", [
    (
        "Asignar y tramitar la actuación de vigilancia o verificación solicitada ante el "
        "responsable competente, conservando el alcance referido a las peticiones Cuarta, "
        "Quinta y Sexta. Esta actuación futura no debe presentarse como iniciada, decidida "
        "o concluida."
    ),
    (
        "Asignar y tramitar ante el responsable competente la actuación de vigilancia o "
        "verificación solicitada sobre las actuaciones relacionadas con las peticiones "
        "Cuarta, Quinta y Sexta, conservando el alcance de las preguntas y de las solicitudes "
        "documentales. La ejecución de esta actuación queda pendiente y no debe describirse "
        "como realizada."
    ),
    "Preparar la supervisión solicitada sobre la entrega de documentos al peticionario.",
])
def test_supervision_preparation_paraphrases_remain_future_actions(description):
    inquiry = request(description="Solicita ejercer supervigilancia sobre la respuesta.")
    result = apply_evidence_contract(
        inquiry, finding([{"kind": "clarification", "description": description}])
    )
    proposed = next(check for check in result["checks"] if check["description"] == description)
    assert proposed["stage"] == "fulfillment" and not proposed["blocks_approval"]
    assert result["missing"] == []


@pytest.mark.parametrize("description", [
    "Gestionar la firma solicitada ante el responsable competente.",
    "Preparar el envío de esta respuesta después de su aprobación.",
    "Tramitar la firma y remisión de la respuesta aprobada.",
])
def test_preparing_current_signature_and_dispatch_is_not_evidence(description):
    inquiry = request(description="Solicita que el profesor firme personalmente la respuesta.")
    result = apply_evidence_contract(
        inquiry, finding([{"kind": "clarification", "description": description}])
    )
    proposed = next(check for check in result["checks"] if check["description"] == description)
    assert proposed["stage"] == "fulfillment" and not proposed["blocks_approval"]


@pytest.mark.parametrize("kind, description", [
    (
        "norm",
        "Contrastar las normas vigentes que delimitan la competencia de la Procuraduría "
        "General de la Nación para valorar o iniciar una actuación de supervigilancia.",
    ),
    (
        "fact",
        "Verificar específicamente si se entregaron documentos recientes, documentos sin "
        "certificado de autenticidad o documentos distintos de los solicitados.",
    ),
    ("fact", "Confirmar la competencia del profesor para firmar la respuesta final."),
    ("fact", "Comprobar la autenticidad de los documentos incluidos en la respuesta final."),
    ("fact", "Verificar que la firma de la respuesta final corresponde al autorizado."),
    ("document", "Aportar el justificante de envío de la respuesta final anterior."),
    ("fact", "Comprobar si ya se realizó la supervisión solicitada en el trámite anterior."),
])
def test_supervision_and_final_response_mentions_do_not_remove_evidence(kind, description):
    inquiry = request(description="Solicita ejercer supervigilancia sobre la respuesta.")
    result = apply_evidence_contract(
        inquiry, finding([{"kind": kind, "description": description}])
    )
    proposed = next(check for check in result["checks"] if check["description"] == description)
    assert proposed["stage"] == "evidence" and proposed["blocks_approval"]
    assert proposed in result["missing"]


def test_resolved_check_not_reintroduced_into_draft():
    result = apply_evidence_contract(
        request(),
        finding([{"kind": "fact", "description": "Confirmar el periodo del nombramiento."}]),
    )
    check = result["checks"][0]
    resolved = deepcopy(result)
    resolved["missing"] = []
    resolved["checks"][0]["resolution"] = {"status": "resolved"}
    pending = normalize_pending(
        request(), resolved, [{"kind": check["kind"], "description": check["description"]}]
    )
    assert pending == []


def test_analysis_failure_never_becomes_document_absence():
    result = apply_evidence_contract(request(), {"status": "error", "supports": [], "missing": []})
    assert result["evidence_states"] == ["analysis_error"]


def test_same_ocr_passage_check_is_shared_despite_model_wording_and_kind():
    inquiry = request(description="Informe quién remitió el correo.")
    checks = [
        {
            "kind": "document",
            "description": "Cotejar humanamente la extracción OCR del correo.",
            "linked_source_ids": ["one"],
            "linked_chunk_ids": ["one:1:1:3"],
        },
        {
            "kind": "clarification",
            "description": "Contrastar la transcripción con su original.",
            "linked_source_ids": ["one"],
            "linked_chunk_ids": ["one:1:1:3"],
        },
    ]
    result = apply_evidence_contract(inquiry, finding(checks))
    assert len(result["checks"]) == 1
    assert result["checks"][0]["reason_code"] == "transcription"
    assert result["checks"][0]["state"] == "confirmation_pending"


def test_information_reuses_declared_check_subject_to_specific_application():
    inquiry = request(description="Confirme si aparece en los planes de trabajo aprobados de 2019.")
    raw = {
        "kind": "document",
        "description": "Localizar el plan completo de 2019.",
        "linked_source_ids": ["one"],
    }
    proposed = finding([raw])
    proposed["verifications"] = [
        {
            "id": "declared",
            "kind": "antecedent_declared",
            "source_id": "one",
            "fact": "Asignación revisada en 2019.",
        }
    ]
    result = apply_evidence_contract(inquiry, proposed)
    assert result["missing"][0]["kind"] == "fact"
    assert result["missing"][0]["reason_code"] == "applicability"
    assert "aprobados de 2019" in result["missing"][0]["description"]
    assert result["missing"][0]["resolution"]["status"] == "open"
    assert result["missing"][0]["original_description"] == raw["description"]
    delivery = apply_evidence_contract(
        request(description="Entregue copia de los planes."), proposed
    )
    assert delivery["missing"][0]["kind"] == "document"
