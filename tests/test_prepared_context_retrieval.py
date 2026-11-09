"""Prepared context must preserve original passages and query-local ranking."""

from collections import Counter
from copy import deepcopy

import pytest

from pqrs_claro import source_retrieval as retrieval


def piece(source, page, quote, **changes):
    return {
        "source_id": source,
        "document_id": source,
        "chunk_id": f"{source}:{page}",
        "title": "Guía del examen de admisión 2027",
        "filename": "guia.pdf",
        "quote": quote,
        "page": page,
        "line_start": 1,
        "line_end": 2,
        "version": 1,
        "category": "institutional_norm",
        "collection_id": "admisiones",
        "case_id": None,
        "validity": "current",
        **changes,
    }


def request(title, description=""):
    return {
        "id": "P1",
        "title": title,
        "description": description,
        "case_id": "current",
        "allowed_collection_ids": ["admisiones"],
        "context": {"subject": "Consulta sobre el examen de admisión 2027"},
    }


def date_corpus():
    return [
        piece("multiple", 1,
              "Matrículas: 12 de septiembre de 2027.\n"
              "Examen de admisión: 20 y 21 de octubre de 2027.\n"
              "Publicación de resultados: 30/10/2027."),
        piece("split-tokens", 1,
              "curso2027examen curso2028evaluacion: 20 de octubre de 2027."),
        piece("separate-tokens", 1, "Examen evaluación: 20 de octubre de 2027."),
        piece("repeated", 1,
              "Examen examen examen: 21.10.2027.\n"
              "Evaluación de admisión: 22-10-2027."),
        piece("far", 1,
              "Examen evaluación " + "palabra " * 70 + "20 de octubre de 2027."),
        piece("bare-year", 1, "Examen de admisión en 2027."),
    ]


@pytest.mark.parametrize("title", [
    "Fecha del examen de admisión",
    "Fechas de examen evaluación",
    "Calendario de curso",
    "Cuándo se publican resultados",
])
def test_compact_calendar_preserves_multiple_dates_and_multi_token_words(title):
    chunks = date_corpus()
    original = deepcopy(chunks)
    q = request(title)
    expected = retrieval._date_passages(q, chunks)
    assert expected
    features = retrieval._calendar_features(chunks[1]["quote"])
    assert any(len(tokens) > 1 for words in features for tokens, _ in words)
    index = retrieval.RetrievalIndex(chunks)

    assert retrieval._date_passages(q, chunks, index=index) == expected
    assert retrieval._date_passages(q, chunks, index=index) == expected
    assert chunks == original


def test_calendar_equal_proximity_keeps_bm25_id_order_and_current_citations():
    quote = "Examen de admisión: 20 de octubre de 2027."
    chunks = [piece(source, 1, quote) for source in ("z", "b", "a")]
    q = request("Fecha del examen de admisión")
    index = retrieval.RetrievalIndex(chunks)
    expected = retrieval._date_passages(q, chunks)
    assert [row["chunk_id"] for row in expected] == ["a:1", "b:1"]
    assert retrieval._date_passages(q, chunks, index=index) == expected

    chunks.reverse()
    chunks[0].update(version=2, page=7, line_start=9, line_end=12, reviewed_by="Revisor")
    assert retrieval._date_passages(q, chunks, index=index) == retrieval._date_passages(q, chunks)
    assert retrieval._date_passages(q, chunks, index=index)[0]["page"] == 7


def test_calendar_shared_event_token_retains_every_original_first_token():
    chunks = [
        piece("a-plain", 1, "Examen: 20 de octubre de 2027."),
        piece("b-plain", 1, "Examen: 20 de octubre de 2027."),
        piece("z-mixed", 1, "curso2027examen examen: 20 de octubre de 2027."),
    ]
    q = request("Fecha del examen")
    expected = retrieval._date_passages(q, chunks)
    # Both words match "examen", but the legacy relation counts "curso" and "examen".
    assert expected[0]["source_id"] == "z-mixed"
    index = retrieval.RetrievalIndex(chunks)
    assert retrieval._date_passages(q, chunks, index=index) == expected


def test_calendar_does_not_merge_event_coverage_across_distinct_dates():
    chunks = [
        piece("a-separated", 1,
              "Examen: 20 de octubre de 2027. " + "relleno " * 80
              + "Evaluación: 15 de noviembre de 2027."),
        piece("z-together", 1, "Examen y evaluación: 20 de octubre de 2027."),
    ]
    q = request("Fechas del examen evaluación")
    expected = retrieval._date_passages(q, chunks)
    assert expected[0]["source_id"] == "z-together"
    index = retrieval.RetrievalIndex(chunks)
    assert retrieval._date_passages(q, chunks, index=index) == expected


def test_calendar_preparation_observes_quote_replacement_with_same_identifier():
    chunks = [piece("guide", 1, "Examen de admisión: 20 de octubre de 2027.")]
    q = request("Fecha del examen de admisión")
    index = retrieval.RetrievalIndex(chunks)
    assert retrieval._date_passages(q, chunks, index=index)

    chunks[0]["quote"] = "El examen de admisión todavía no tiene fecha definida."
    assert retrieval._date_passages(q, chunks, index=index) == []
    chunks[0]["quote"] = "La nueva fecha del examen es el 15 de noviembre de 2027."
    assert retrieval._date_passages(q, chunks, index=index) == retrieval._date_passages(q, chunks)
    assert "noviembre" in retrieval._date_passages(q, chunks, index=index)[0]["quote"]


@pytest.mark.parametrize("change", [
    {"collection_id": "private"},
    {"case_id": "another-case"},
    {"validity": "superseded"},
    {"category": "archive_only"},
])
def test_populated_context_cache_does_not_restore_revoked_sources(change):
    shared = piece("shared", 1, "Examen de admisión: 20 de octubre de 2027.")
    revocable = piece("revocable", 1, shared["quote"])
    chunks = [revocable, shared]
    q = request("Fecha del examen de admisión")
    index = retrieval.RetrievalIndex(chunks)
    assert retrieval.retrieve(q, chunks, index=index) == retrieval.retrieve(q, chunks)

    revocable.update(change)
    expected = retrieval.retrieve(q, [shared])
    assert retrieval.retrieve(q, chunks, index=index) == expected
    assert {row["source_id"] for row in expected} == {"shared"}


def document_corpus():
    return [
        piece("guide-a", 1, "Guía de aspirantes. Examen de admisión 2027."),
        piece("guide-a", 2, "El examen tendrá una duración de tres horas."),
        piece("guide-a", 3, "Las competencias evaluadas tienen igual ponderación."),
        piece("guide-b", 1, "La duración máxima del examen será de dos horas."),
        piece("guide-c", 1, "Examen de admisión: publicación del calendario."),
        piece("other", 1, "La duración del examen será de cuatro horas.",
              title="Registro de pagos", filename="pagos.pdf"),
    ]


@pytest.mark.parametrize("title,description", [
    ("Tiempo del examen", "Cuánto tiempo tienen los aspirantes para resolverlo"),
    ("Competencias evaluadas", "Cuáles son las competencias y sus porcentajes"),
    ("Publicación del calendario", "Dónde se publica el calendario"),
])
def test_prepared_document_content_preserves_subset_statistics_and_originals(title, description):
    chunks = document_corpus()
    original = deepcopy(chunks)
    q = request(title, description)
    expected = retrieval._document_content(q, chunks)
    assert expected
    index = retrieval.RetrievalIndex(chunks)

    assert retrieval._document_content(q, chunks, index=index) == expected
    # The same prepared texts must also work with a changed authorized subset.
    for selected in (chunks[:3], list(reversed(chunks)), chunks[3:]):
        assert retrieval._document_content(q, selected, index=index) == (
            retrieval._document_content(q, selected)
        )
    assert chunks == original


@pytest.mark.parametrize("field,value", [
    ("title", "Archivo de trámites sin relación"),
    ("filename", "examen_admision_2027_anexo.pdf"),
    ("quote", "La duración máxima del examen será de cinco horas."),
    ("historical_group", "Examen admisión 2027"),
])
def test_prepared_document_content_observes_metadata_and_body_changes(field, value):
    chunks = document_corpus()
    q = request("Duración máxima del examen")
    index = retrieval.RetrievalIndex(chunks)
    assert retrieval._document_content(q, chunks, index=index) == (
        retrieval._document_content(q, chunks)
    )

    chunks[3][field] = value
    chunks[3].update(version=2, page=8)
    assert retrieval._document_content(q, chunks, index=index) == (
        retrieval._document_content(q, chunks)
    )


def test_normalized_context_cache_reuses_text_across_passages():
    text = "EXÁMENES de admisión: 20 de octubre de 2027."
    index = retrieval.RetrievalIndex([])
    expected = retrieval._search_words(text)
    first = index.normalized_text(text)
    computed = index.diagnostics["context_computed"]
    hits = index.diagnostics["context_hits"]
    second = index.normalized_text(text)

    assert first == second == (expected, Counter(retrieval.tokenize(expected)))
    assert index.diagnostics["context_computed"] == computed
    assert index.diagnostics["context_hits"] == hits + 1
    assert index.diagnostics["context_cache_bytes"] > 0


@pytest.mark.parametrize("budget", [0, 400, 2048])
def test_context_cache_budget_keeps_results_equivalent_when_entries_are_evicted(budget):
    index = retrieval.RetrievalIndex([], context_cache_bytes=budget)
    texts = [f"Examen número {number}: fecha 20 de octubre de 2027." for number in range(12)]
    for text in [*texts, *reversed(texts)]:
        normalized = retrieval._search_words(text)
        assert index.normalized_text(text) == (normalized, Counter(retrieval.tokenize(normalized)))
        assert 0 <= index.diagnostics["context_cache_bytes"] <= budget
    if budget == 0:
        assert not index._context
        assert index.diagnostics["context_hits"] == 0


def test_prepared_calendar_and_document_content_reuse_normalization_between_queries():
    chunks = [
        piece("guide", 1, "Examen de admisión: 20 de octubre de 2027."),
        piece("guide", 2, "La duración máxima del examen será de tres horas."),
    ]
    index = retrieval.RetrievalIndex(chunks)
    date_q = request("Fecha del examen de admisión")
    duration_q = request("Duración del examen")
    expected_dates = retrieval._date_passages(date_q, chunks)
    expected_content = retrieval._document_content(duration_q, chunks)
    assert retrieval._date_passages(date_q, chunks, index=index) == expected_dates
    assert retrieval._document_content(duration_q, chunks, index=index) == expected_content
    computed = index.diagnostics["context_computed"]
    hits = index.diagnostics["context_hits"]

    assert retrieval._date_passages(date_q, chunks, index=index) == expected_dates
    assert retrieval._document_content(duration_q, chunks, index=index) == expected_content
    assert index.diagnostics["context_computed"] == computed
    assert index.diagnostics["context_hits"] > hits


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("title,quote", [
    ("Cursos cursos", "Cursos, cursos, admisiones, inscripciones y canciones."),
    ("A2027 MATRÍCULA", "A2027 B3: matrícula y examen2027curso; examen2027curso."),
    ("Straße oﬁcina", "Straße, oﬁcina, ＥＸＡＭＥＮ y admi\u0301sion admi\u1ab0sion."),
    ("Información de consulta", "Los procesos y las relaciones son para las personas."),
    ("Calendario 2027", "12/10/2027; 12.10.2027; 12-10-2027 y veinte días."),
    ("Título presente sin cuerpo", ""),
    ("Solicitud para todos", "la de por que esta ese cuando atentamente"),
    (None, "None figura en el texto original y none se repite."),
])
def test_body_counts_equal_full_normalization_without_mutating_prepared_terms(
    prepared, title, quote
):
    row = piece("body", 1, quote, title=title)
    counts = {
        retrieval.terms_key(row): dict(Counter(retrieval.tokenize(f"{title} {quote}")))
    } if prepared else {}
    before = deepcopy(counts)
    index = retrieval.RetrievalIndex([row], prepared_terms=counts)

    assert index.body_context_terms(row) == Counter(
        retrieval.tokenize(retrieval._search_words(quote))
    )
    assert counts == before
    assert not index._context
    assert index.diagnostics["context_body_prepared_hits"] == int(prepared)
    assert index.diagnostics["context_body_computed"] == int(not prepared)


@pytest.mark.parametrize("field,value", [
    ("title", "Nuevo título de convocatorias y calendarios"),
    ("quote", "Exámenes y evaluaciones cambiaron al 15 de noviembre de 2027."),
])
def test_body_counts_fall_back_when_title_or_quote_changes(field, value):
    row = piece("body", 1, "Exámenes y evaluaciones: 20 de octubre de 2027.")
    prepared = {retrieval.terms_key(row): dict(Counter(
        retrieval.tokenize(f"{row['title']} {row['quote']}")))}
    before = deepcopy(prepared)
    index = retrieval.RetrievalIndex([row], prepared_terms=prepared)
    assert index.body_context_terms(row) == Counter(
        retrieval.tokenize(retrieval._search_words(row["quote"]))
    )
    row[field] = value

    assert index.body_context_terms(row) == Counter(
        retrieval.tokenize(retrieval._search_words(row["quote"]))
    )
    assert index.diagnostics["context_body_prepared_hits"] == 1
    assert index.diagnostics["context_body_computed"] == 1
    assert prepared == before


def test_body_counts_never_displace_cached_document_metadata():
    rows = [piece("guide", number, f"Exámenes y cursos del grupo {number}.")
            for number in range(200)]
    prepared = {retrieval.terms_key(row): dict(Counter(
        retrieval.tokenize(f"{row['title']} {row['quote']}"))) for row in rows}
    index = retrieval.RetrievalIndex(rows, prepared_terms=prepared, context_cache_bytes=2048)
    metadata = "Guía del examen de admisión 2027 guia.pdf"
    index.normalized_text(metadata)
    retained = dict(index._context)
    retained_bytes = index.diagnostics["context_cache_bytes"]
    assert retained

    for row in rows:
        assert index.body_context_terms(row) == Counter(
            retrieval.tokenize(retrieval._search_words(row["quote"]))
        )
    assert dict(index._context) == retained
    assert index.diagnostics["context_cache_bytes"] == retained_bytes
    assert index.diagnostics["context_body_prepared_hits"] == len(rows)


@pytest.mark.parametrize("kind", ["dates", "content"])
def test_prepared_body_ranking_matches_legacy_subset_statistics(kind):
    chunks = date_corpus() if kind == "dates" else document_corpus()
    q = request("Fechas del examen evaluación") if kind == "dates" else request(
        "Duración máxima del examen")
    function = retrieval._date_passages if kind == "dates" else retrieval._document_content
    prepared = {retrieval.terms_key(row): dict(Counter(
        retrieval.tokenize(f"{row['title']} {row['quote']}"))) for row in chunks}
    index = retrieval.RetrievalIndex(chunks, prepared_terms=prepared)

    assert function(q, chunks)
    for selected in (chunks, list(reversed(chunks)), chunks[:3], chunks[2:]):
        assert function(q, selected, index=index) == function(q, selected)
