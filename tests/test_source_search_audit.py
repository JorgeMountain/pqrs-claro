"""Ausencia local requiere buscar nombres y contenido completo autorizado."""

from copy import deepcopy

import pytest

from pqrs_claro.source_search_audit import target_document_search


def request(description="Entregue copia del acta 15."):
    return {"id": "P1", "case_id": "case", "description": description,
            "allowed_collection_ids": ["history"]}


def source(**changes):
    return {"id": "one", "source_id": "one", "document_id": "doc", "version": 1,
            "filename": "anexo.pdf", "title": "Anexo", "category": "historical_attachment",
            "collection_id": "history", "case_id": None, "sha256": "sha-one",
            "extraction_status": "ready", **changes}


def chunk(quote, item=None, **changes):
    item = item or source()
    return {**item, "chunk_id": item["source_id"] + ":1", "page": 1,
            "line_start": 1, "line_end": 2, "quote": quote, "location_kind": "page", **changes}


def test_generic_filename_with_document_header_is_found_in_full_text():
    original = source()
    full_text = chunk("ACTA No. 15\nEl comité estudió el asunto.")
    before = deepcopy((original, full_text))
    result = target_document_search(request(), {}, [original], [full_text])
    assert (original, full_text) == before
    match = result["catalog_matches"][0]
    assert match["filename"] == "anexo.pdf" and match["matched_references"] == ["acta 15"]
    assert match["match_basis"] == ["document_header"]
    assert match["matching_chunks"][0]["quote"] == full_text["quote"]
    assert result["search_audit"]["negative_sufficient_references"] == []


def test_no_numbered_target_keeps_readability_audit_without_rescanning_headers(monkeypatch):
    from pqrs_claro import source_search_audit

    def unexpected_scan(*args):
        pytest.fail("No hay referencias numeradas que justifiquen recorrer encabezados")

    monkeypatch.setattr(source_search_audit, "_header_references", unexpected_scan)
    monkeypatch.setattr(source_search_audit, "_email", unexpected_scan)
    unread = source(id="unread", source_id="unread", document_id="unread",
                    extraction_status="error")
    result = target_document_search(request("Informe los pasos para solicitar una constancia."),
                                    {}, [source(), unread], [chunk("Trámite de constancias.")])
    assert result["catalog_matches"] == []
    assert result["search_audit"]["targeted_references"] == []
    assert result["search_audit"]["unread_source_ids"] == ["unread"]
    assert not result["search_audit"]["content_search_complete"]


@pytest.mark.parametrize("quote", [
    "ACTA DEL CONSEJO DE FACULTAD No. 15\nContenido.",
    "ACTA 0015\nContenido.",
])
def test_header_variants_keep_exact_numeric_identity(quote):
    result = target_document_search(request(), {}, [source()], [chunk(quote)])
    assert result["catalog_matches"][0]["source_id"] == "one"


@pytest.mark.parametrize("status", ["pending", "partial", "unsupported", "error"])
def test_unread_generic_file_prevents_a_sufficient_negative_search(status):
    result = target_document_search(request(), {}, [source(extraction_status=status)], [])
    audit = result["search_audit"]
    assert audit["unread_source_ids"] == ["one"]
    assert not audit["catalog_complete"]
    assert audit["negative_sufficient_references"] == []


def test_unread_target_named_file_is_located_instead_of_marked_absent():
    result = target_document_search(request(), {}, [source(
        filename="Acta 15.pdf", extraction_status="pending",
    )], [])
    match = result["catalog_matches"][0]
    assert match["source_id"] == "one" and match["extraction_status"] == "pending"
    assert match["matched_references"] == ["acta 15"]
    assert result["search_audit"]["negative_sufficient_references"] == []


def test_all_authorized_text_is_searched_not_only_the_retrieved_candidates():
    finding = {"supports": [], "candidate_documents": [], "missing": [
        {"kind": "document", "description": "Localizar el acta 15."},
    ]}
    result = target_document_search(request(), finding, [source()], [chunk("ACTA 15\nTexto.")])
    assert result["catalog_matches"][0]["matching_chunks"][0]["chunk_id"] == "one:1"


def test_scope_and_current_version_filter_precedes_search_and_unread_blockers():
    own = source()
    foreign = source(id="foreign", source_id="foreign", document_id="foreign", case_id="other",
                     extraction_status="pending")
    unlinked = source(id="secret", source_id="secret", document_id="secret", collection_id="secret")
    old = source(id="old", source_id="old", version=0, extraction_status="pending")
    result = target_document_search(request(), {}, [own, foreign, unlinked, old], [
        chunk("Documento diferente."), chunk("ACTA 15", foreign), chunk("ACTA 15", unlinked),
        chunk("ACTA 15", old),
    ])
    assert result["catalog_matches"] == []
    audit = result["search_audit"]
    assert audit["catalog_count"] == 1 and audit["unread_source_ids"] == []
    assert audit["negative_sufficient_references"] == ["acta 15"]
    assert "secret" not in str(audit) and "foreign" not in str(audit)


def test_stale_chunk_cannot_make_content_search_complete():
    result = target_document_search(request(), {}, [source(version=2)], [chunk("ACTA 15")])
    assert result["catalog_matches"] == []
    assert result["search_audit"]["unread_source_ids"] == ["one"]


def test_simple_reference_in_email_does_not_locate_the_attached_document():
    message = source(filename="correo.pdf", title="Correo de remisión")
    result = target_document_search(request(), {}, [message], [chunk(
        "Para: persona@example.test\nSe adjunta el acta 15.", message,
    )])
    assert result["catalog_matches"] == []
    assert result["search_audit"]["negative_sufficient_references"] == ["acta 15"]


def test_document_header_quoted_in_email_requires_inspection_of_the_container():
    message = source(filename="correo.pdf", title="Correo de remisión")
    result = target_document_search(request(), {}, [message], [chunk(
        "Para: persona@example.test\nACTA 15\nTexto citado en el mensaje.", message,
    )])
    assert result["catalog_matches"] == []
    assert result["search_audit"]["negative_sufficient_references"] == []
    assert result["search_audit"]["targets"][0]["container_reference_source_ids"] == ["one"]


def test_same_office_number_in_different_year_does_not_match_header():
    result = target_document_search(request("Entregue el oficio 1436-2024."), {}, [source()], [
        chunk("21360001-1436-2025\nEste oficio menciona el anterior oficio 1436-2024."),
    ])
    assert result["catalog_matches"] == []
    assert result["search_audit"]["negative_sufficient_references"] == ["oficio 1436-2024"]


@pytest.mark.parametrize("description", [
    "Entregue los documentos del expediente.", "Entregue el acta 15 almacenada en OnBase.",
])
def test_generic_request_or_unsearched_external_scope_never_proves_absence(description):
    result = target_document_search(request(description), {}, [source()], [chunk("Otro asunto.")])
    assert result["search_audit"]["negative_sufficient_references"] == []
    assert result["search_audit"]["external_systems_searched"] == []


def test_archive_without_extraction_may_hide_a_target_document():
    archive = source(
        filename="anexos.zip", category="archive_only", extraction_status="unsupported"
    )
    result = target_document_search(request(), {}, [archive], [])
    assert result["search_audit"]["negative_sufficient_references"] == []
    assert result["search_audit"]["unread_source_ids"] == ["one"]
