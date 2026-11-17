"""Mandatos e identidad documental generales; archivos ficticios, sin API ni datos vivos."""

import json
from types import SimpleNamespace

import pytest

from pqrs_claro.draft_engine import _supports
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError
from pqrs_claro.request_intent import classify_request_intent, fulfillment_actions
from pqrs_claro.source_assessment import (
    OpenAISourceAssessor,
    _allowed_roles,
    _SourceSelection,
)
from pqrs_claro.source_documents import (
    named_document_candidates,
    normative_copy_matches,
    requested_document,
    requested_document_number,
)
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.source_sufficiency import coverage_uses


@pytest.mark.parametrize("text", [
    "Enumerar los requisitos y anexos que debía reunir cada aspirante para entregar su aval.",
    "Describa qué documentos debe entregar la familia para solicitar la ayuda de vivienda.",
    "Detalle el procedimiento para remitir el informe ambiental al municipio.",
    "Liste los documentos que debe anexar y remitir el proveedor en su oferta.",
    "Señale las condiciones para que el paciente adjunte y remita los soportes médicos.",
    "Solicito información sobre cómo entregar el formulario de licencia comercial.",
    "¿Qué documentos debe entregar el interesado para renovar su matrícula mercantil?",
    "¿Cuántos certificados puede expedir la oficina de empleo?",
    "No solicito copia de la circular; solo explique sus requisitos.",
    "No adjuntar documentos; indique únicamente el trámite para recibir la beca.",
    "Explique el procedimiento; no solicito copia de la resolución.",
    "No necesito copia, solamente describa el proceso de reconocimiento.",
])
def test_described_procedure_or_excluded_delivery_never_becomes_own_action(text):
    item = {"description": text}
    assert classify_request_intent(item)["intents"] == ["information"]
    assert fulfillment_actions(item) == []
    assert requested_document(item) is None


@pytest.mark.parametrize("text", [
    "Explique el horario y adjunte copia de la Circular 402 de 2025.",
    "Informar el horario y remitir copia de la Circular 402 de 2025.",
    "Explique qué requisitos debe cumplir el solicitante y adjunte copia de la Circular 402.",
    "Explique el horario; adjunte copia de la Circular 402 de 2025.",
    "Adjunte copia de la Circular 402 de 2025 y explique el horario.",
    "Faciliten copia de la Circular 402 de 2025; indiquen el horario.",
    "Entreguen copia de la Circular 402 de 2025; describan el horario.",
])
def test_distinct_copy_command_survives_a_compound_information_request(text):
    item = {"description": text}
    assert classify_request_intent(item)["intents"] == ["information", "document_delivery"]
    actions = fulfillment_actions(item)
    assert [action["reason_code"] for action in actions] == ["document_delivery"]
    assert all(not action["blocks_approval"] and action["stage"] == "fulfillment"
               for action in actions)
    assert requested_document(item) == "circular"


@pytest.mark.parametrize("text", [
    "Explique el reglamento de becas y adjunte copia de la Circular 402 de 2025.",
    "Explique la Circular 100 de 2024 y adjunte copia de la Circular 402 de 2025.",
    "No solicito copia del reglamento. Remita copia de la Circular 402 de 2025.",
])
def test_copy_identity_comes_from_delivery_command_not_information_or_excluded_clause(text):
    item = request(description=text)
    assert requested_document(item) == "circular"
    assert requested_document_number(item, "circular") == "402"
    assert normative_copy_matches(item, norm(), "circular")


def request(**updates):
    return {"id": "P1", "case_id": "case-a", "title": "Copia de la circular de movilidad",
            "description": "Solicito copia de la Circular 402 de 2025.", **updates}


def norm(**updates):
    return {
        "chunk_id": "circular-v1:1:1:3", "source_id": "circular-v1",
        "document_id": "circular-document", "version": 1, "sha256": "ab" * 32,
        "is_latest": True, "category": "institutional_norm", "case_id": None,
        "title": "Circular 402 de movilidad", "filename": "circular_402_2025.pdf",
        "origin": "Fuente ficticia de la unidad de movilidad", "review_status": "reviewed",
        "validity": "current", "page": 1, "line_start": 1, "line_end": 3,
        "quote": "CIRCULAR 402\n15 de agosto de 2025\nHorarios de atención de movilidad.",
        "method": "native", "needs_review": False, **updates,
    }


def selection(source, *, use="document_delivery", role="document", **updates):
    return _SourceSelection.model_validate({
        "status": "references_found", "summary": "Se localizó el original solicitado.",
        "missing": [], "warnings": [], "supports": [{"chunk_id": source["chunk_id"],
            "role": role, "reason": "El encabezado identifica el archivo solicitado."}],
        "coverage_complete": True,
        "coverage": [{"aspect": "Copia de la circular", "claim": "El archivo está localizado.",
            "use": use, "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
            "application": {"status": "not_requested", "uncertainty_indexes": [],
                            "explanation": "Se identifica el original cuya copia se solicita."},
            "explanation": "El original permite preparar su copia; no acredita envío."}],
        **updates,
    })


@pytest.mark.parametrize("category", ["national_norm", "institutional_norm"])
def test_normative_original_can_be_a_copy_without_proving_delivery_or_case_facts(category):
    source = norm(category=category)
    item = request()
    assert _allowed_roles(category, "circular", request=item, source=source) == ("rule", "document")
    result = OpenAISourceAssessor._materialize(selection(source), item, [source])
    assert result["status"] == "references_found"
    assert result["missing"] == []
    assert result["supports"][0]["role"] == "document"
    assert result["supports"][0]["quote"] == source["quote"]
    assert result["evidence_states"] == ["support_found"]
    assert [action["reason_code"] for action in result["actions"]] == ["document_delivery"]
    assert result["actions"][0]["resolution"]["status"] == "open"
    assert _supports(item, result)[source["chunk_id"]]["sha256"] == source["sha256"]
    assert coverage_uses(source, "document") == ["attributed_content", "document_delivery", "rule"]
    for use in ("official_status", "verified_fact"):
        with pytest.raises(DomainError, match="norma no acredita"):
            OpenAISourceAssessor._materialize(selection(source, use=use), item, [source])
    with pytest.raises(DomainError, match="tipo de fuente"):
        OpenAISourceAssessor._materialize(selection(source, role="fact"), item, [source])


def test_assessor_sends_and_enforces_same_conditional_norm_roles():
    source = norm()
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        proposed = selection({**source, "chunk_id": "C1"})
        return SimpleNamespace(status="completed", output_parsed=proposed)

    assessor = OpenAISourceAssessor(api_key="fictitious-no-network", model="local-test-double")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = assessor.assess(request(), [source])
    sent = json.loads(calls[0]["input"])["candidates"][0]
    assert sent["allowed_roles"] == ["rule", "document"]
    assert sent["allowed_coverage_uses"]["document"] == [
        "attributed_content", "document_delivery", "rule",
    ]
    assert result["supports"][0]["source_id"] == source["source_id"]


@pytest.mark.parametrize("validity", ["current", "unknown"])
def test_one_normative_copy_support_also_covers_rule_without_waiving_validity(validity):
    source = norm(validity=validity)
    item = request(description="Adjunte copia de la Circular 402 de 2025 y explique el horario.")
    proposed = selection(source)
    rule = proposed.coverage[0].model_copy(update={
        "aspect": "Horario de atención indicado en la circular", "use": "rule",
        "claim": "El archivo contiene las reglas del horario de atención.",
        "explanation": "La misma norma identifica el documento y regula su horario.",
    })
    proposed.coverage.append(rule)
    result = OpenAISourceAssessor._materialize(proposed, item, [source])
    assert len(result["supports"]) == 1
    assert result["supports"][0]["role"] == "document"
    assert result["sufficiency"]["source_uses"][source["source_id"]] == [
        "document_delivery", "rule",
    ]
    assert any(p["reason_code"] == "validity" for p in result["missing"]) == (
        validity == "unknown"
    )
    assert "verified_fact" not in coverage_uses(source, "document")
    assert "official_status" not in coverage_uses(source, "document")


@pytest.mark.parametrize("updates", [
    {"sha256": None}, {"sha256": "not-an-integrity-hash"}, {"document_id": None},
    {"source_id": None}, {"version": 0}, {"version": True}, {"is_latest": False},
    {"is_latest": None},
    {"validity": "superseded"}, {"quote": "Otra circular menciona la Circular 402 de 2025."},
    {"quote": "CIRCULAR 402\n15 de agosto de 2024\nHorarios de atención."},
    {"quote": "CIRCULAR 402\n15 de agosto de 2024\nContenido.\nContenido.\nVer acuerdo de 2025."},
    {"filename": "correo_remision_circular_402.pdf", "title": "Correo de remisión de Circular 402"},
    {"filename": "circular_403.pdf", "title": "Circular 403"},
    {"quote": "CIRCULAR 403\n15 de agosto de 2025\nSe menciona la circular 402."},
    {"collection_id": "unlinked"}, {"case_id": "another-case"},
])
def test_copy_role_requires_current_scoped_identity_and_original_header(updates):
    source = norm(**updates)
    assert _allowed_roles(source["category"], "circular", request=request(), source=source) == (
        "rule",
    )
    with pytest.raises(DomainError):
        _supports(request(), {"request_id": "P1", "supports": [{**source, "role": "document"}]})


def test_norm_mentions_and_procedural_questions_do_not_receive_document_role():
    source = norm()
    item = request(description="Enumere qué documentos debe entregar según la Circular 402.")
    assert requested_document(item) is None
    assert _allowed_roles("institutional_norm", "circular", request=item, source=source) == (
        "rule",
    )
    assert _allowed_roles("institutional_norm", "circular") == ("rule",)


def test_unnumbered_regulation_copy_preserves_subject_identity():
    item = request(title="", description="Adjunte copia del reglamento de becas de movilidad.")
    source = norm(title="Reglamento de becas de movilidad", filename="reglamento_movilidad.pdf",
                  quote="REGLAMENTO DE BECAS DE MOVILIDAD\nRequisitos de desplazamiento.")
    assert normative_copy_matches(item, source, "reglamento")
    unrelated = {**source, "title": "Reglamento de vivienda", "filename": "reglamento_vivienda.pdf",
                 "quote": "REGLAMENTO DE VIVIENDA\nRequisitos para viviendas universitarias."}
    assert not normative_copy_matches(item, unrelated, "reglamento")


@pytest.mark.parametrize("text,kind,number", [
    ("Adjunte copia de la Resolución Rectoral 642 de 2022.", "resolucion", "642"),
    ("Adjunte el Decreto municipal número 724 de 2023.", "decreto", "724"),
    ("Copia de la resolución que modifica el Acuerdo 170 de 2024.", "resolucion", None),
])
def test_number_modifier_does_not_borrow_another_document_id(text, kind, number):
    assert requested_document_number({"description": text}, kind) == number


def test_requested_normative_authority_modifier_must_match_original_header():
    item = request(description="Adjunte copia del Decreto Municipal 724 de 2023.")
    source = norm(title="Decreto 724", filename="decreto_724_2023.pdf",
                  quote="DECRETO DEPARTAMENTAL 724\n5 de julio de 2023\nReglas de transporte.")
    assert not normative_copy_matches(item, source, "decreto")
    source["quote"] = "DECRETO MUNICIPAL 724\n5 de julio de 2023\nReglas de transporte."
    assert normative_copy_matches(item, source, "decreto")


@pytest.mark.parametrize("heading", [
    "SECRETARÍA DE MOVILIDAD - CIRCULAR 402 DE 2025",
    "CONSEJO MUNICIPAL | CIRCULAR 402 DE 2025",
])
def test_original_heading_can_follow_a_short_uppercase_letterhead(heading):
    source = norm(quote=heading + "\nHorarios de atención.")
    assert normative_copy_matches(request(), source, "circular")
    assert not normative_copy_matches(request(), {**source, "page": 2}, "circular")
    assert not normative_copy_matches(request(), {**source, "line_start": 8}, "circular")
    assert not normative_copy_matches(request(), {**source, "quote": source["quote"].lower()},
                                      "circular")


@pytest.mark.parametrize("heading", [
    "REMISIÓN DE - CIRCULAR 402 DE 2025", "DOCUMENTO ADJUNTO - CIRCULAR 402 DE 2025",
    "REFERENCIA A - CIRCULAR 402 DE 2025", "SE MENCIONA - CIRCULAR 402 DE 2025",
])
def test_letterhead_rule_never_promotes_a_remission_or_mention(heading):
    assert not normative_copy_matches(request(), norm(quote=heading), "circular")


def test_inventory_uses_title_even_when_original_filename_is_generic():
    source = norm(filename="norma.txt")
    assert named_document_candidates("Falta la Circular 402.", [source]) == [source]
    source["quote"] = "El documento menciona la Circular 402 de 2025, sin su original."
    assert named_document_candidates("Falta la Circular 402.", [source]) == [source]
    assert not normative_copy_matches(request(), source, "circular")
    source["title"] = "Correo de remisión de la Circular 402 de 2025"
    assert named_document_candidates("Falta la Circular 402.", [source]) == []


def test_actual_library_version_integrity_and_revoked_scope_still_govern_copy_candidates(tmp_path):
    library = SourceLibrary(tmp_path / "isolated", PDFExtractor())
    library.save_collection({"id": "mobility", "title": "Normas de movilidad ficticias"})
    library.link_collections("case-a", ["mobility"])
    metadata = dict(title="Circular 402 de movilidad", category="institutional_norm",
                    origin="Fuente ficticia", collection_id="mobility")
    old = library.add("circular_402_2025.txt", norm()["quote"].encode(), **metadata)
    _, first = library.snapshot("case-a")
    item = request(allowed_collection_ids=["mobility"])
    assert _allowed_roles(first[0]["category"], "circular", request=item, source=first[0]) == (
        "rule", "document",
    )
    new = library.add("circular_402_2025.txt", (norm()["quote"] + "\nTexto corregido.").encode(),
                      document_id=old["document_id"], **metadata)
    _, updated = library.snapshot("case-a")
    assert {source["source_id"] for source in updated} == {new["id"]}
    assert all(source["version"] == 2 and source["sha256"] == new["sha256"] for source in updated)
    original = library.original(new["id"], case_id="case-a")
    payload = original.read_bytes()
    original.write_bytes(b"Contenido alterado fuera de la biblioteca")
    with pytest.raises(DomainError, match="original cambió"):
        library.snapshot("case-a")
    original.write_bytes(payload)
    library.link_collections("case-a", [])
    assert library.snapshot("case-a") == ([], [])
    with pytest.raises(KeyError):
        library.original(new["id"], case_id="case-a")
    revoked = request(allowed_collection_ids=[])
    with pytest.raises(DomainError, match="no vinculado"):
        _supports(revoked, {"request_id": "P1", "supports": [{**updated[0], "role": "document"}]})
