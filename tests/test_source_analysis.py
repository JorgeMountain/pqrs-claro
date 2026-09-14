"""Contrato de búsqueda con corpus ficticio y dobles explícitos, sin red ni claves."""

from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from pqrs_claro.models import DomainError
from pqrs_claro.source_assessment import (
    OpenAISourceAssessor,
    _declaration_passage,
    _SourceSelection,
)
from pqrs_claro.source_graph import build_source_graph
from pqrs_claro.source_retrieval import retrieve


def chunk(identifier="acta-1", **changes):
    """Metadatos de un PDF ficticio ya incorporado a la biblioteca."""
    result = {
        "chunk_id": identifier,
        "source_id": "acta-version-1",
        "document_id": "acta-document",
        "version": 1,
        "title": "Acta del comité de prácticas 14",
        "category": "case_evidence",
        "case_id": "case-a",
        "filename": "acta_comite_14.pdf",
        "origin": "Secretaría del comité. Ejemplo ficticio.",
        "review_status": "reviewed",
        "validity": "not_applicable",
        "page": 1,
        "line_start": 1,
        "line_end": 3,
        "quote": "ACTA DEL COMITÉ DE PRÁCTICAS 14\n  Fecha: 2 de septiembre.\nSe aprobó la plaza.",
        "method": "native",
        "needs_review": False,
    }
    return {**result, **changes}


def request(**changes):
    return {
        "id": "P1",
        "title": "Copia del acta",
        "description": "Solicito copia del acta 14 del comité de prácticas.",
        "case_id": "case-a",
        **changes,
    }


def selection(**changes):
    return _SourceSelection.model_validate(
        {
            "status": "references_found",
            "summary": "Se localizó el acta del comité que corresponde a la solicitud.",
            "missing": [],
            "supports": [
                {
                    "chunk_id": "acta-1",
                    "reason": "Contiene el acta 14 solicitada.",
                    "role": "document",
                }
            ],
            "warnings": [],
            **changes,
        }
    )


def api_document_coverage(alias, original):
    """Solo los dobles de Responses API deben emitir el contrato remoto actual."""
    return {
        "aspect": "Localización de la copia del acta 14 solicitada.",
        "claim": f"{alias} contiene el encabezado del acta 14 del comité de prácticas.",
        "use": "document_delivery",
        "citations": [{"chunk_id": alias, "quote": original["quote"]}],
        "explanation": (
            f"{alias} identifica el archivo solicitado mediante su encabezado. "
            "La localización del archivo no acredita su entrega al peticionario."
        ),
    }


def test_retrieval_ranks_relevant_original_fragments_and_handles_accents():
    irrelevant = chunk(
        "sport",
        document_id="sports",
        title="Calendario deportivo",
        quote="Horario de entrenamiento de fútbol y baloncesto.",
    )
    norms = chunk(
        "norm",
        document_id="rules",
        category="institutional_norm",
        validity="current",
        title="Reglamento de prácticas",
        quote="El comité establecerá los requisitos para el proceso de prácticas.",
        case_id=None,
    )
    original = chunk()
    results = retrieve(
        request(description="SOLICITO COPIA DEL ACTA 14 DEL COMITE DE PRACTICAS."),
        [irrelevant, norms, original],
    )
    assert results[0]["chunk_id"] == "acta-1"
    assert results[0]["quote"] == original["quote"]
    assert results[0]["source_id"] == original["source_id"]
    assert "comite" in results[0]["matched_terms"]
    assert all(result["score"] > 0 for result in results)
    assert "sport" not in {result["chunk_id"] for result in results}
    assert "score" not in original  # Una búsqueda no reescribe la fuente.


def test_retrieval_excludes_style_superseded_and_other_cases():
    sources = [
        chunk("old-response", category="previous_response"),
        chunk("old-norm", category="institutional_norm", validity="superseded"),
        chunk("other-case", case_id="case-b"),
        chunk("current"),
        chunk("library", category="institutional_norm", validity="current", case_id=None),
    ]
    assert {item["chunk_id"] for item in retrieve(request(), sources)} == {"current", "library"}


def test_retrieval_diversifies_documents_and_never_returns_zero_matches():
    corpus = [chunk(f"acta-{index}") for index in range(10)]
    corpus.extend(
        chunk(f"annex-{index}", document_id=f"annex-{index}", title="Anexo del acta 14")
        for index in range(7)
    )
    results = retrieve(request(), corpus, limit=8)
    assert len(results) == 8
    assert max(Counter(item["document_id"] for item in results).values()) <= 3
    assert (
        retrieve(request(title="", description="Favor informar sobre la solicitud"), corpus) == []
    )
    assert retrieve(request(title="", description="Radiotelescopio fotométrico"), corpus) == []
    assert retrieve(request(), corpus, limit=0) == []


def test_assessment_uses_structured_responses_and_literal_references():
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        proposed = selection(
            coverage_complete=True,
            coverage=[api_document_coverage("C1", original)],
        )
        proposed.supports[0].chunk_id = "C1"
        return SimpleNamespace(status="completed", output_parsed=proposed)

    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=fake_parse))
    original = chunk()
    result = assessor.assess(request(), [original])
    assert calls[0]["store"] is False
    assert calls[0]["truncation"] == "disabled"
    sent = json.loads(calls[0]["input"])["candidates"][0]
    from pqrs_claro.source_passages import numbered_lines
    assert sent == {**{k: v for k, v in original.items() if k != "quote"}, "chunk_id": "C1",
                    "allowed_roles": ["fact", "document"],
                    "numbered_lines": numbered_lines(original["quote"])}
    assert original["chunk_id"] == "acta-1"
    assert result["request_id"] == "P1"
    assert result["supports"][0]["quote"] == original["quote"]
    assert result["supports"][0]["chunk_id"] == original["chunk_id"]
    assert result["supports"][0]["line_start"] == 1
    assert result["sufficiency"]["coverage"][0]["citations"] == [
        {"chunk_id": original["chunk_id"], "quote": original["quote"]}
    ]
    assert result["status"] == "references_found"
    assert result["missing"] == []
    assert "preliminar" in result["summary"]


@pytest.mark.parametrize("count", [8, 24])
def test_assessor_maps_closed_aliases_to_exact_original_chunks_in_selection_order(count):
    originals = [
        chunk(
            f"long-identifier-{index}:1:1:3",
            source_id=f"source-{index}",
            document_id=f"document-{index}",
            quote=f"ACTA DEL COMITÉ DE PRÁCTICAS 14\nFragmento ficticio {index}.",
        )
        for index in range(count)
    ]
    proposed = selection(
        coverage_complete=True,
        coverage=[
            api_document_coverage(f"C{count}", originals[-1]),
            api_document_coverage("C1", originals[0]),
        ],
    )
    proposed.supports[0].chunk_id = f"C{count}"
    proposed.supports.append(proposed.supports[0].model_copy(update={"chunk_id": "C1"}))
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=proposed)

    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=fake_parse))
    result = assessor.assess(request(), originals)
    sent = json.loads(calls[0]["input"])["candidates"]
    from pqrs_claro.source_passages import numbered_lines
    assert sent == [
        {**{k: v for k, v in source.items() if k != "quote"}, "chunk_id": f"C{i}",
         "allowed_roles": ["fact", "document"], "numbered_lines": numbered_lines(source["quote"])}
        for i, source in enumerate(originals, 1)
    ]
    assert [support["chunk_id"] for support in result["supports"]] == [
        originals[-1]["chunk_id"], originals[0]["chunk_id"]
    ]
    assert [support["quote"] for support in result["supports"]] == [
        originals[-1]["quote"], originals[0]["quote"]
    ]
    assert [support.chunk_id for support in proposed.supports] == [f"C{count}", "C1"]
    assert [
        item["citations"][0]["chunk_id"] for item in result["sufficiency"]["coverage"]
    ] == [originals[-1]["chunk_id"], originals[0]["chunk_id"]]
    assert [item.citations[0].chunk_id for item in proposed.coverage] == [f"C{count}", "C1"]


@pytest.mark.parametrize(
    "category,description,expected_roles,forbidden_role",
    [
        ("national_norm", "Explique los requisitos.", ["rule"], "fact"),
        ("institutional_norm", "Explique los requisitos.", ["rule"], "document"),
        ("case_evidence", "Explique el hecho.", ["fact", "document"], "rule"),
        ("historical_response", "Explique el antecedente.", ["antecedent"], "fact"),
        ("historical_response", "Adjunte el oficio 14.", ["antecedent", "document"], "fact"),
        ("historical_petition", "Explique lo preguntado.", ["antecedent"], "fact"),
        (
            "historical_attachment", "Adjunte el acta 14.",
            ["historical_evidence", "document"], "fact",
        ),
    ],
)
def test_api_allowed_roles_and_local_rejection_share_the_same_contract(
    category, description, expected_roles, forbidden_role
):
    source = chunk(category=category, collection_id="historia-equipo")
    inquiry = request(title="Consulta", description=description,
                      allowed_collection_ids=["historia-equipo"])
    proposed = selection()
    proposed.supports[0].chunk_id = "C1"
    proposed.supports[0].role = forbidden_role
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=proposed)

    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=fake_parse))
    with pytest.raises(DomainError, match="tipo de fuente"):
        assessor.assess(inquiry, [source])
    sent = json.loads(calls[0]["input"])["candidates"][0]
    assert sent["allowed_roles"] == expected_roles
    assert "".join(line["text"] for line in sent["numbered_lines"]) == source["quote"]
    assert "allowed_roles" not in source


@pytest.mark.parametrize("alias", ["C2", "c1", " C1", "C01", "acta-1", "acta-version-1"])
def test_assessor_rejects_unknown_aliases_without_fuzzy_or_source_id_fallback(alias):
    proposed = selection()
    proposed.supports[0].chunk_id = alias
    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(status="completed", output_parsed=proposed)
        )
    )
    with pytest.raises(DomainError, match="alias de fragmento que no existe"):
        assessor.assess(request(), [chunk()])


def test_assessor_rejects_repeated_alias_instead_of_silently_deduplicating_selection():
    proposed = selection()
    proposed.supports[0].chunk_id = "C1"
    proposed.supports.append(proposed.supports[0].model_copy())
    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(status="completed", output_parsed=proposed)
        )
    )
    with pytest.raises(DomainError, match="repitió"):
        assessor.assess(request(), [chunk()])


def test_remote_aliases_in_prose_become_readable_file_and_page_references():
    proposed = selection(
        summary="La referencia C1 permite localizar el documento.",
        missing=[{
            "kind": "clarification",
            "description": "Cotejar la identidad en C1.",
            "reason_code": "source_identity",
            "basis": "content_gap",
            "source_chunk_ids": ["C1"],
            "affected_claim": "Correspondencia entre C1 y la copia concreta solicitada.",
            "why_unresolved": "Falta cotejar la identidad de C1 con el objeto de la solicitud.",
        }],
        warnings=["C1 conserva su atribución."],
        coverage_complete=False,
        coverage=[api_document_coverage("C1", chunk())],
    )
    proposed.supports[0].chunk_id = "C1"
    proposed.supports[0].reason = "C1 contiene el acta solicitada."
    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(
        parse=lambda **_: SimpleNamespace(status="completed", output_parsed=proposed)
    ))
    result = assessor.assess(request(), [chunk()])
    visible = json.dumps(result, ensure_ascii=False)
    assert "C1" not in visible
    assert "página 1, líneas 1–3" in visible
    assert result["supports"][0]["chunk_id"] == "acta-1"
    assert result["supports"][0]["quote"] == chunk()["quote"]


def test_assessor_rejects_ambiguous_candidate_alias_mapping_before_the_api_call():
    calls = []
    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **kwargs: calls.append(kwargs))
    )
    with pytest.raises(DomainError, match="identificadores repetidos"):
        assessor.assess(request(), [chunk(), chunk(quote="Otro texto con el mismo identificador.")])
    with pytest.raises(DomainError, match="veinticuatro fragmentos"):
        assessor.assess(request(), [chunk(f"chunk-{index}") for index in range(25)])
    assert calls == []


def test_assessment_rejects_invented_and_duplicate_references():
    bad = selection()
    bad.supports[0].chunk_id = "invented-source"
    with pytest.raises(DomainError, match="no existe"):
        OpenAISourceAssessor._materialize(bad, request(), [chunk()])
    bad = selection()
    bad.supports.append(bad.supports[0].model_copy())
    with pytest.raises(DomainError, match="repitió"):
        OpenAISourceAssessor._materialize(bad, request(), [chunk()])


@pytest.mark.parametrize(
    "source_changes,role,message",
    [
        ({"category": "national_norm", "validity": "current"}, "fact", "tipo de fuente"),
        ({"category": "institutional_norm", "validity": "current"}, "document", "tipo de fuente"),
        ({"category": "case_evidence"}, "rule", "tipo de fuente"),
        ({"category": "previous_response"}, "fact", "oficio anterior"),
        ({"validity": "superseded"}, "document", "reemplazada"),
        ({"case_id": "case-b"}, "document", "otro expediente"),
    ],
)
def test_assessment_enforces_source_scope_and_evidence_roles(source_changes, role, message):
    proposed = selection()
    proposed.supports[0].role = role
    with pytest.raises(DomainError, match=message):
        OpenAISourceAssessor._materialize(proposed, request(), [chunk(**source_changes)])


def test_norm_describing_actas_cannot_satisfy_request_for_actual_file():
    proposed = selection(
        supports=[
            {"chunk_id": "acta-1", "reason": "Regula la elaboración de actas.", "role": "rule"}
        ]
    )
    norm = chunk(
        category="institutional_norm",
        validity="current",
        title="Reglamento del comité de prácticas",
        quote="El comité levantará un acta de cada sesión y conservará las copias.",
        case_id=None,
    )
    result = OpenAISourceAssessor._materialize(proposed, request(), [norm])
    assert result["status"] == "needs_evidence"
    assert result["supports"][0]["role"] == "rule"
    assert any(item["kind"] == "document" for item in result["missing"])
    assert any("no sustituye" in item for item in result["warnings"])


def test_unreviewed_source_unknown_norm_and_ocr_create_actionable_pending_items():
    proposed = selection(
        supports=[{"chunk_id": "acta-1", "reason": "Contiene los requisitos.", "role": "rule"}]
    )
    norm = chunk(
        category="institutional_norm",
        validity="unknown",
        review_status="pending",
        method="ocr",
        needs_review=True,
        title="Reglamento de prácticas",
        case_id=None,
    )
    inquiry = request(title="Requisitos", description="Indique los requisitos de prácticas.")
    result = OpenAISourceAssessor._materialize(proposed, inquiry, [norm])
    assert result["status"] == "needs_evidence"
    descriptions = " ".join(item["description"] for item in result["missing"])
    assert (
        "procedencia" in descriptions and "vigencia" in descriptions and "página 1" in descriptions
    )
    assert result["supports"][0]["quote"] == norm["quote"]


def test_no_candidates_cannot_become_successful_evidence_even_if_model_says_so():
    result = OpenAISourceAssessor._materialize(selection(supports=[]), request(), [])
    assert result["status"] == "no_matches"
    assert result["supports"] == []
    assert result["missing"]
    assert "No se localizaron" in result["summary"]
    assert any("no demuestra" in warning for warning in result["warnings"])


def test_existing_document_pending_item_is_preserved_without_duplicate_guardrail():
    pending = {"kind": "document", "description": "Aportar el acta 14 del comité de prácticas."}
    proposed = selection(
        status="needs_evidence",
        missing=[pending],
        supports=[{"chunk_id": "acta-1", "reason": "Regula las actas.", "role": "rule"}],
    )
    norm = chunk(category="institutional_norm", validity="current", case_id=None)
    result = OpenAISourceAssessor._materialize(proposed, request(), [norm])
    assert result["status"] == "needs_evidence"
    documents = [item for item in result["missing"] if item["kind"] == "document"]
    assert [{key: item[key] for key in ("kind", "description")} for item in documents] == [pending]
    assert documents[0]["state"] == "confirmation_pending"
    assert documents[0]["check_key"].startswith("check-")
    assert any("no sustituye" in warning for warning in result["warnings"])


def test_transcription_pending_item_labels_document_sections_without_inventing_pages():
    source = chunk(location_kind="section", needs_review=True)
    result = OpenAISourceAssessor._materialize(selection(), request(), [source])
    assert result["status"] == "needs_evidence"
    descriptions = " ".join(item["description"] for item in result["missing"])
    assert "sección 1" in descriptions
    assert "página" not in descriptions


def test_partial_model_output_is_not_saved_as_a_completed_assessment():
    assessor = OpenAISourceAssessor(api_key="test-not-real", model="test-model")
    assessor.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(status="incomplete", output_parsed=selection())
        )
    )
    with pytest.raises(DomainError, match="parcial"):
        assessor.assess(request(), [chunk()])


def test_declared_check_accepts_pdf_whitespace_and_keeps_original_passage():
    source = chunk(category="historical_response", collection_id="history",
                   document_status="issued", verification_status="reported_by_user",
                   quote="Se verificó el periodo\n   con el plan docente de 2015.")
    proposed = selection(
        supports=[{"chunk_id": "acta-1", "role": "antecedent", "reason": "Relata un cotejo."}],
        declared_checks=[{"chunk_id": "acta-1", "fact": "Se cotejó el periodo.",
                          "declaration_quote": (
                              "Se verificó el periodo con el plan docente de 2015."),
                          "basis": "El oficio menciona el plan docente."}],
    )
    result = OpenAISourceAssessor._materialize(
        proposed, request(description="Explique el periodo.", allowed_collection_ids=["history"]),
        [source],
    )
    assert result["verifications"][0]["kind"] == "antecedent_declared"
    assert result["verifications"][0]["passage"]["quote"] == source["quote"]
    assert "human_review" not in str(result["verifications"])


def test_numbered_selection_restores_full_context_but_never_accepts_invented_words():
    original = ("2. Se cotejó el plan de trabajo de 2015.\n"
                "3. El resultado no corresponde a periodos posteriores.\n"
                "4. Las actas de notas son documentos independientes.")
    selection = ("2. Se cotejó el plan de trabajo de 2015.\n"
                 "4. Las actas de notas son documentos independientes.")
    assert _declaration_passage(selection, original) == (True, True)
    assert _declaration_passage(selection.replace("2015", "2019"), original) == (False, False)
    reordered = ("4. Las actas de notas son documentos independientes. "
                 "2. Se cotejó el plan de trabajo de 2015.")
    assert _declaration_passage(reordered, original) == (False, False)


def test_invalid_declared_check_does_not_discard_valid_supports_or_invent_a_fact():
    source = chunk(category="historical_response", collection_id="history",
                   document_status="issued", verification_status="reported_by_user")
    proposed = selection(
        supports=[{"chunk_id": "acta-1", "role": "antecedent", "reason": "Contenido anterior."}],
        declared_checks=[{"chunk_id": "acta-1", "fact": "Dato inventado.",
                          "declaration_quote": "Este texto no existe.", "basis": "No consta."}],
    )
    result = OpenAISourceAssessor._materialize(
        proposed, request(description="Explique el periodo.", allowed_collection_ids=["history"]),
        [source],
    )
    assert result["supports"][0]["quote"] == source["quote"]
    assert result["verifications"] == []
    assert set(result["evidence_states"]) == {"support_found"}
    assert result["analysis_notices"][0]["code"] == "optional_declaration_citation_rejected"
    assert not result["missing"]


def test_source_graph_recovers_after_failure_without_repeating_retrieval(tmp_path):
    counts = {"retrieve": 0, "assess": 0}

    def fake_retriever(inquiry, chunks):
        counts["retrieve"] += 1
        return retrieve(inquiry, chunks)

    class FailsOnceAssessor:
        def assess(self, inquiry, candidates):
            counts["assess"] += 1
            if counts["assess"] == 1:
                raise DomainError("Conexión interrumpida simulada")
            return OpenAISourceAssessor._materialize(selection(), inquiry, candidates)

    checkpoint = str(tmp_path / "sources.sqlite")
    config = {"configurable": {"thread_id": "case-a:P1:inputs-version-1"}}
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        graph = build_source_graph(fake_retriever, FailsOnceAssessor(), saver)
        with pytest.raises(DomainError, match="simulada"):
            graph.invoke({"request": request(), "chunks": [chunk()]}, config)
        assert graph.get_state(config).next == ("assess_sources",)
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        graph = build_source_graph(fake_retriever, FailsOnceAssessor(), saver)
        result = graph.invoke(None, config)
        assert result["finding"]["status"] == "references_found"
        assert graph.get_state(config).next == ()
    assert counts == {"retrieve": 1, "assess": 2}
