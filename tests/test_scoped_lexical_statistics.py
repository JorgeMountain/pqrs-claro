"""Scope, positional alignment and retention of query-local BM25 statistics."""

import pytest

from pqrs_claro import source_retrieval as retrieval


def passage(identifier, quote, **metadata):
    return {
        "chunk_id": identifier,
        "source_id": identifier,
        "document_id": identifier,
        "title": "Calendario académico",
        "filename": "calendario.pdf",
        "quote": quote,
        "page": 1,
        "line_start": 1,
        "line_end": 2,
        "category": "institutional_norm",
        "case_id": None,
        "validity": "current",
        **metadata,
    }


def body_reference(rows):
    normalized = [{**row, "title": "", "quote": retrieval._search_words(row["quote"])}
                  for row in rows]
    return retrieval.RetrievalIndex(normalized).statistics(normalized)


def test_retrieve_requests_full_authorized_statistics_once_per_petition(monkeypatch):
    question = passage("hist", "¿Cuándo es el examen? Respuesta: aún no se publicó.",
                       category="historical_response", collection_id="archivo")
    visible = [
        question,
        passage("dates", "Fecha del examen: 25/09/2027. Matrícula académica."),
        passage("contacts", "Tutor del curso: docente@example.test. Atención de inscritos."),
    ]
    hidden = passage("hidden", "Datos del examen bloqueado", collection_id="otra")
    corpus = [*visible, hidden]
    request = {
        "title": "Fecha del examen",
        "description": "Matrícula, docente@example.test",
        "allowed_collection_ids": ["archivo"],
        "case_id": "actual",
        "retrieval_queries": ["atención de inscritos", "matrícula académica", "tutor"],
    }
    expected = retrieval.retrieve(request, visible)
    index = retrieval.RetrievalIndex(corpus)
    statistics = index.statistics
    calls = []

    def signature(rows):
        return tuple((row["chunk_id"], row["quote"]) for row in rows)

    def tracked(rows, *args, **kwargs):
        calls.append(signature(rows))
        return statistics(rows, *args, **kwargs)

    monkeypatch.setattr(index, "statistics", tracked)
    for _ in range(2):
        calls.clear()
        assert retrieval.retrieve(request, corpus, index=index) == expected
        assert calls.count(signature(visible)) == 1
        assert (("hist", "¿Cuándo es el examen"),) in calls
        assert all(identifier != "hidden" for scope in calls for identifier, _ in scope)


def test_body_mode_is_independent_of_lexical_statistics_and_uses_current_positions():
    quote = "Pruebas de inscripciones y convocatorias académicas."
    chunks = [passage("first", quote), passage("second", "Duración del examen."),
              passage("third", quote)]
    index = retrieval.RetrievalIndex(chunks)
    lexical = index.statistics(chunks)
    assert "calendario" in lexical[2]
    expected = body_reference(chunks)
    assert "calendario" not in expected[2]
    assert index.body_statistics(chunks) == expected
    assert index.statistics(chunks) == lexical

    # The duplicate quote contributes its own position and term frequencies.
    for scope in (chunks[:1], chunks[1:], [chunks[1], chunks[0], chunks[2]], []):
        assert index.body_statistics(scope) == body_reference(scope)

    chunks[0]["quote"] = "Publicado el calendario de prácticas del laboratorio."
    assert index.body_statistics(chunks) == body_reference(chunks)
    assert "laboratorio" in index.body_statistics(chunks)[2]


def test_body_hit_for_identical_quotes_returns_current_source_citations():
    quote = "La duración del examen es de tres horas."
    old = passage("old", quote)
    new = passage("replacement", quote, title="Calendario académico revisado",
                  filename="revision.pdf", page=7, version=2, line_start=10, line_end=13)
    request = {"title": "Duración del examen", "context": {"subject": "Calendario académico"}}
    index = retrieval.RetrievalIndex([old, new])
    assert retrieval._document_content(request, [old], index=index) == [old]
    builds = index.diagnostics["body_statistics_builds"]
    hits = index.diagnostics["body_statistics_hits"]
    assert builds > 0
    assert retrieval._document_content(request, [new], index=index) == [new]
    assert index.diagnostics["body_statistics_builds"] == builds
    assert index.diagnostics["body_statistics_hits"] > hits


def test_reused_scope_tracks_permission_content_order_and_title_changes():
    public = passage("public", "La duración del examen de física es de tres horas.")
    private = passage("private", "El examen de física del laboratorio dura dos horas.",
                      collection_id="labs", case_id="actual")
    corpus = [public, private]
    request = {"title": "Duración del examen de física", "allowed_collection_ids": ["labs"],
               "case_id": "actual", "context": {"subject": "Calendario académico"}}
    index = retrieval.RetrievalIndex(corpus)

    def check(current_request, permitted):
        expected = retrieval.retrieve(current_request, permitted)
        assert {row["chunk_id"] for row in expected} == {row["chunk_id"] for row in permitted}
        assert retrieval.retrieve(current_request, corpus, index=index) == expected

    check(request, corpus)
    check({**request, "allowed_collection_ids": []}, [public])
    check({**request, "case_id": "other"}, [public])
    corpus.reverse()
    check(request, corpus)
    private.update(title="Calendario de física", quote="Examen de física: seis horas.",
                   version=3, page=8)
    check(request, corpus)
    public["validity"] = "superseded"
    check(request, [private])
    private["category"] = "archive_only"
    check(request, [])


@pytest.mark.parametrize("changes", [
    {"filename": "oficio_71.pdf"},
    {"quote": "El anexo menciona el oficio 72."},
    {"title": "Correo de archivo"},
])
def test_document_identity_rechecks_current_evidence_for_same_request_and_id(changes):
    document = passage("document", "Oficio 72\nNota sobre física.",
                       title="Serie institucional", filename="oficio_72.pdf")
    competitor = passage("mention", "Se entrega copia del oficio 72 para consulta.")
    rows = [document, competitor]
    request = {"title": "Entregar copia del oficio 72"}
    index = retrieval.RetrievalIndex(rows)

    def identity_rank(results):
        return next(row["document_identity_rank"] for row in results
                    if row["chunk_id"] == document["chunk_id"])

    warm = retrieval._rank(request, rows, index=index)
    assert identity_rank(warm) == 2
    document.update(changes)
    expected = retrieval._rank(request, rows)
    assert identity_rank(expected) == 0
    assert retrieval._rank(request, rows, index=index) == expected


@pytest.mark.parametrize("budget", [0, 1])
def test_body_statistics_over_budget_is_returned_without_retention(budget):
    rows = [passage("one", "Duración del examen de matemáticas.")]
    index = retrieval.RetrievalIndex(rows, body_statistics_cache_bytes=budget)
    for count in (1, 2):
        assert index.body_statistics(rows) == body_reference(rows)
        assert index.diagnostics["body_statistics_builds"] == count
        assert index.diagnostics["body_statistics_hits"] == 0
        assert index.diagnostics["body_statistics_cache_bytes"] == 0


def test_body_statistics_evicts_least_recently_used_scope():
    scopes = [[passage(key, f"Examen {key}")] for key in ("aa", "bb", "cc")]
    sizes = []
    for scope in scopes:
        probe = retrieval.RetrievalIndex(scope)
        probe.body_statistics(scope)
        sizes.append(probe.diagnostics["body_statistics_cache_bytes"])

    # Derive a two-entry budget from the running interpreter's object sizes.
    budget = max(sizes) * 2
    assert 0 < budget < sum(sizes)
    index = retrieval.RetrievalIndex([], body_statistics_cache_bytes=budget)
    first, second, third = scopes
    for scope, builds, hits in [(first, 1, 0), (second, 2, 0), (first, 2, 1),
                                (third, 3, 1), (first, 3, 2), (second, 4, 2)]:
        assert index.body_statistics(scope) == body_reference(scope)
        assert index.diagnostics["body_statistics_builds"] == builds
        assert index.diagnostics["body_statistics_hits"] == hits
        assert 0 < index.diagnostics["body_statistics_cache_bytes"] <= budget
