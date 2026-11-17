"""Resolve a copy's object from the petition, never from the only available file."""

import json
from types import SimpleNamespace

import pytest
from test_normative_document_requests import norm, request, selection

from pqrs_claro.models import DomainError
from pqrs_claro.source_assessment import OpenAISourceAssessor, _allowed_roles
from pqrs_claro.source_documents import (
    delivery_document_target,
    document_matches,
    normative_copy_matches,
    numbered_document_references,
    requested_document,
    requested_document_number,
)


@pytest.mark.parametrize("denomination", ["Instructivo", "Protocolo", "Boletín", "Tablilla"])
@pytest.mark.parametrize("lowercase", [False, True])
def test_explicit_numbered_copy_uses_open_denomination_not_case_specific_types(denomination,
                                                                           lowercase):
    named = denomination.lower() if lowercase else denomination
    item = request(description=f"Faciliten una copia íntegra del {named} 432 de 2026 disponible.")
    source = norm(title=f"{denomination} 432 de 2026", filename="archivo_consulta.pdf",
                  quote=f"{denomination.upper()} 432 DE 2026\nEl ejemplar tiene una página.")
    target = delivery_document_target(item)
    assert target["status"] == "explicit" and target["open_identity"] is True
    assert target["kind"] == denomination.casefold().replace("í", "i")
    assert normative_copy_matches(item, source, target["kind"])
    result = OpenAISourceAssessor._materialize(selection(source), item, [source])
    assert result["missing"] == []
    assert result["actions"][0]["reason_code"] == "document_delivery"
    assert not result["actions"][0]["blocks_approval"]


def test_unknown_named_anaphora_keeps_scope_and_does_not_use_sibling_document():
    item = request(description="Según el Protocolo 721 de 2025, ¿qué se consulta? "
                   "Faciliten una copia del ejemplar disponible.", context=original_context())
    target = delivery_document_target(item)
    assert target["status"] == "resolved" and target["kind"] == "protocolo"
    assert target["references"] == ["protocolo 721 de 2025"]
    item["description"] = ("Compare el Protocolo 721 de 2025 y el Boletín 722 de 2026. "
                           "Faciliten una copia del ejemplar disponible.")
    assert delivery_document_target(item)["status"] == "ambiguous"


def test_two_explicit_copy_commands_do_not_silently_select_the_first_target():
    item = request(description="Adjunte copia del Protocolo 721 de 2025; "
                   "adjunte copia de la Circular 402 de 2025.")
    assert delivery_document_target(item)["status"] == "ambiguous"
    assert not normative_copy_matches(item, norm(), "circular")


@pytest.mark.parametrize("kind", ["Circular", "Protocolo"])
def test_document_identifier_letter_suffix_is_preserved_and_cannot_match_another_act(kind):
    item = request(description=f"Faciliten copia del {kind} 615-B de 2026.")
    target = delivery_document_target(item)
    source = norm(title=f"{kind} 615-B de 2026", filename="archivo.pdf",
                  quote=f"{kind.upper()} 615-B DE 2026\nContenido del acto identificado.")
    assert requested_document_number(item, target["kind"]) == "615-b"
    assert numbered_document_references(item["description"]) == [f"{kind.lower()} 615-b"]
    assert normative_copy_matches(item, source, target["kind"])
    wrong = {**source, "title": f"{kind} 615-A de 2026",
             "quote": f"{kind.upper()} 615-A DE 2026\nMenciona el 615-B en su texto."}
    assert not normative_copy_matches(item, wrong, target["kind"])


def test_open_document_name_still_requires_own_header_and_original_metadata():
    item = request(description="Remitan copia del Instructivo 432 de 2026.")
    source = norm(title="Correo que menciona Instructivo 432 de 2026",
                  quote="CORREO DE REMISIÓN\nSe menciona el Instructivo 432 de 2026.")
    assert not normative_copy_matches(item, source, "instructivo")
    assert "document" not in _allowed_roles("institutional_norm", "instructivo",
                                            request=item, source=source)


@pytest.mark.parametrize("kind,number,year,quote", [
    ("Circular", "2025", "2026", "CIRCULAR 2025 DE 2026\nContenido del documento."),
    ("Circular", "402", "2025", "CIRCULAR 402\n15 de agosto de 2025\nContenido."),
    ("Circular", "402", "2025", "CIRCULAR 402\nFecha: 15/08/2025\nContenido."),
    ("Circular", "402", "2025", "CIRCULAR 402\n2025-08-15\nContenido."),
    ("Protocolo", "615-2", None, "PROTOCOLO\n615-2\nContenido del documento."),
])
def test_complete_identity_accepts_its_own_year_and_exact_numeric_suffix(kind, number, year, quote):
    identity = f"{kind} {number}" + (f" de {year}" if year else "")
    item = request(title="", description=f"Faciliten copia del {identity}.")
    source = norm(title=identity, filename="archivo.pdf", quote=quote)
    assert normative_copy_matches(item, source, kind.lower())
    result = OpenAISourceAssessor._materialize(selection(source), item, [source])
    assert result["missing"] == []
    assert result["supports"][0]["quote"] == quote


def test_primary_identity_can_mention_another_document_without_borrowing_its_year():
    item = request(description="Faciliten copia de la Circular 402 de 2025.")
    source = norm(title="Circular 402 de 2025 que modifica la Circular 5 de 2024",
                  quote="CIRCULAR 402 DE 2025\nModifica la Circular 5 de 2024.")
    assert normative_copy_matches(item, source, "circular")
    wrong = {**source, "quote": "CIRCULAR 402 DE 2024\nModifica la Circular 5 de 2025."}
    assert not normative_copy_matches(item, wrong, "circular")


@pytest.mark.parametrize("separator", [" y del ", ", el "])
def test_copy_list_keeps_every_explicit_object_but_not_a_later_information_command(separator):
    item = request(description="Faciliten copia de la Circular 402 de 2025"
                   + separator + "Manual 881 de 2026.")
    target = delivery_document_target(item)
    assert target["status"] == "ambiguous"
    assert set(target["references"]) == {"circular 402 de 2025", "manual 881 de 2026"}
    item["description"] = ("Faciliten copia de la Circular 402 de 2025 "
                           "y expliquen el Manual 881 de 2026.")
    assert delivery_document_target(item)["status"] == "explicit"
    assert normative_copy_matches(item, norm(), "circular")


def test_authority_modifier_is_bound_to_its_header_not_another_reference():
    item = request(description="Remitan copia del Decreto Municipal 724 de 2023.")
    source = norm(title="Decreto Departamental 724 de 2023", filename="decreto_724_2023.pdf",
                  quote="DECRETO DEPARTAMENTAL 724 DE 2023\nModifica el Decreto Municipal 5.")
    assert not normative_copy_matches(item, source, "decreto")
    item["description"] = ("Remitan copia del Decreto Municipal 724 de 2023 "
                           "y del Decreto Departamental 724 de 2023.")
    assert delivery_document_target(item)["status"] == "ambiguous"


@pytest.mark.parametrize("kind,number,year", [
    ("Guía", "907", "2026"), ("Manual", "881", "2023"),
    ("Acuerdo", "56", "2024"), ("Circular", "402", "2025"),
])
@pytest.mark.parametrize("role,use", [("document", "document_delivery"),
                                     ("rule", "attributed_content")])
def test_unique_named_object_allows_copy_even_when_model_keeps_rule_role(kind, number, year,
                                                                       role, use):
    item = request(description=f"Según la {kind} {number} de {year}, ¿cómo se reserva el equipo? "
                   "Faciliten también una copia íntegra del ejemplar disponible, "
                   "indicando lo que aún deba comprobarse de esa copia.")
    source = norm(title=f"{kind} {number}", filename=f"{kind}_{number}_{year}.pdf",
                  quote=f"{kind.upper()} {number} DE {year}\nLa reserva requiere confirmación.",
                  review_status="pending", validity="unknown")
    target = delivery_document_target(item)
    assert target["status"] == "resolved" and target["origin"] == "request"
    assert requested_document_number(item, target["kind"]) == number
    assert normative_copy_matches(item, source, target["kind"])
    assert "document" in _allowed_roles("institutional_norm", target["kind"],
                                        request=item, source=source)
    result = OpenAISourceAssessor._materialize(
        selection(source, role=role, use=use), item, [source])
    assert result["supports"][0]["role"] == role  # No invented promotion of evidence.
    assert result["supports"][0]["quote"] == source["quote"]
    assert result["missing"] == []
    assert any(d["original"]["reason_code"] == "provenance" for d in result["gap_decisions"])
    assert result["actions"][0]["reason_code"] == "document_delivery"
    assert not result["actions"][0]["blocks_approval"]
    assert result["actions"][0]["resolution"]["status"] == "open"
    assert "document_missing" not in result["evidence_states"]


def test_provider_gets_original_reference_and_scoped_roles_without_rewriting_request():
    item = request(description="Según la Circular 402 de 2025, ¿cuál es el horario? "
                   "Faciliten copia del ejemplar disponible.")
    source = norm()
    calls = []

    def parse(**kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(status="completed", output_parsed=selection(
            {**source, "chunk_id": "C1"}, role="rule", use="attributed_content"))

    assessor = OpenAISourceAssessor("no-network", "fake-model")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = assessor.assess(item, [source])
    assert len(calls) == 1
    assert calls[0]["request"]["description"] == item["description"]
    assert calls[0]["requested_document_target"]["text"] == "copia de circular 402 de 2025"
    assert calls[0]["candidates"][0]["allowed_roles"] == ["rule", "document"]
    assert result["missing"] == []


@pytest.mark.parametrize("description,status", [
    ("Compare la Circular 402 de 2025 con la Guía 907 de 2026. "
     "Faciliten una copia del ejemplar disponible.", "ambiguous"),
    ("Faciliten una copia del ejemplar disponible.", "unresolved"),
    ("Según la Circular 402 de 2025, ¿cómo se solicita? "
     "Faciliten copia del documento que se menciona como adjunto.", "unresolved"),
    ("Según la Circular 402 de 2025, ¿cómo se solicita? "
     "Faciliten copia del anexo.", "unresolved"),
])
def test_ambiguous_or_other_document_is_not_resolved_from_single_available_source(description,
                                                                                   status):
    item, source = request(description=description), norm()
    assert delivery_document_target(item)["status"] == status
    assert requested_document(item) == "documento"
    assert not document_matches(item, source, "documento")
    result = OpenAISourceAssessor._materialize(
        selection(source, role="rule", use="attributed_content"), item, [source])
    assert {p["reason_code"] for p in result["missing"]} == {"source_identity"}
    assert all(p["kind"] == "clarification" for p in result["missing"])
    assert not any(p["state"] == "document_missing" for p in result["missing"])


def test_explicit_different_copy_object_keeps_priority_over_information_reference():
    item = request(description="Según la Circular 402 de 2025, ¿cuál es el horario? "
                   "Faciliten copia del informe que cita.")
    assert requested_document(item) == "informe"
    assert not normative_copy_matches(item, norm(), "informe")
    result = OpenAISourceAssessor._materialize(
        selection(norm(), role="rule", use="attributed_content"), item, [norm()])
    assert any(p["reason_code"] == "search_incomplete" for p in result["missing"])
    assert not any(p["state"] == "document_missing" for p in result["missing"])


def original_context():
    return {"document_context": {
        "origin": "original_petition", "purpose": "scope_only_not_evidence", "truncated": False,
        "excerpts": [{"page": 1, "line_start": 1, "line_end": 3,
                      "quote": "Esta consulta se refiere a la Circular 402 de 2025.\n"
                      "1. Faciliten una copia del ejemplar disponible.\n"
                      "2. Explique la Guía 907 de 2026."}],
        "question_ranges": [{"request_id": "P1", "page": 1, "line_start": 2, "line_end": 2},
                            {"request_id": "P2", "page": 1, "line_start": 3, "line_end": 3}],
    }}


def test_original_explicit_scope_can_resolve_copy_without_inheriting_other_requests():
    item = request(description="Faciliten una copia del ejemplar disponible.",
                   context=original_context())
    target = delivery_document_target(item)
    assert target["status"] == "resolved"
    assert target["origin"] == "original_petition_scope"
    assert target["references"] == ["circular 402 de 2025"]
    assert normative_copy_matches(item, norm(), "circular")


@pytest.mark.parametrize("change", ["truncated", "model_summary", "two_objects", "no_context"])
def test_unsafe_or_ambiguous_context_never_resolves_object(change):
    item = request(description="Faciliten una copia del ejemplar disponible.",
                   context=original_context())
    context = item["context"]["document_context"]
    if change == "truncated":
        context["truncated"] = True
    elif change == "model_summary":
        context["origin"] = "model_summary"
    elif change == "two_objects":
        context["question_ranges"] = []
    elif change == "no_context":
        item["context"] = {"ancestors": [{"description": "Copia de Circular 402 de 2025"}]}
    assert delivery_document_target(item)["status"] in {"ambiguous", "unresolved"}
    assert not normative_copy_matches(item, norm(), requested_document(item))


@pytest.mark.parametrize("fault", ["wrong_header", "referenced_in_other_doc", "wrong_year",
                                   "wrong_version", "no_hash", "acl", "unreadable"])
def test_resolved_reference_does_not_waive_identity_access_or_extraction_checks(fault):
    item = request(description="Según la Circular 402 de 2025, ¿cuál es el horario? "
                   "Faciliten copia del ejemplar disponible.")
    source = norm()
    if fault == "wrong_header":
        source["quote"] = "CIRCULAR 403 DE 2025\nSe menciona Circular 402."
    elif fault == "referenced_in_other_doc":
        source["quote"] = "INFORME 6 DE 2025\nLa Circular 402 de 2025 se adjuntó anteriormente."
    elif fault == "wrong_year":
        source["quote"] = "CIRCULAR 402 DE 2024\nReglas."
    elif fault == "wrong_version":
        source["is_latest"] = False
    elif fault == "no_hash":
        source["sha256"] = None
    elif fault == "acl":
        source["collection_id"] = "forbidden"
    else:
        source["extraction_status"] = "unsupported"
    if fault == "acl":
        with pytest.raises(DomainError, match="colección"):
            OpenAISourceAssessor._materialize(
                selection(source, role="rule", use="attributed_content"), item, [source])
        return
    result = OpenAISourceAssessor._materialize(
        selection(source, role="rule", use="attributed_content"), item, [source])
    assert result["missing"]
    assert not any(p["state"] == "document_missing" for p in result["missing"])
    if fault == "unreadable":
        assert any(p["state"] == "analysis_error" for p in result["missing"])
    else:
        assert not normative_copy_matches(item, source, "circular")


def test_real_absence_requires_exhaustive_authorized_negative_audit():
    item = request(description="Según la Circular 402 de 2025, ¿cuál es el horario? "
                   "Faciliten copia del ejemplar disponible.")
    proposed = selection(norm(), supports=[], coverage=[], coverage_complete=False,
                         status="no_matches")
    item["search_audit"] = {"negative_sufficient_references": ["circular 402"],
                            "catalog_complete": True, "access_limited": False,
                            "retrieval_error": None}
    result = OpenAISourceAssessor._materialize(proposed, item, [])
    assert any(p["state"] == "document_missing" for p in result["missing"])
    for fault in ("access_limited", "retrieval_error"):
        limited = {**item, "search_audit": {**item["search_audit"], fault: True}}
        result = OpenAISourceAssessor._materialize(proposed, limited, [])
        assert not any(p["state"] == "document_missing" for p in result["missing"])
        assert any(p["reason_code"] == "search_incomplete" for p in result["missing"])
