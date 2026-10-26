from collections import Counter

import pytest

from pqrs_claro import source_retrieval as retrieval

DATE = "20 de octubre de 2027"


def piece(identity, quote, *, title="Archivo"):
    return {
        "chunk_id": identity, "source_id": identity, "document_id": identity,
        "title": title, "quote": quote, "category": "institutional_norm",
        "case_id": None, "page": 1, "line_start": 1, "line_end": 1,
    }


def compare(event, chunks, *, prepared=False):
    request = {"title": f"Fecha de {event}", "description": "Consulta de prueba"}
    terms = {
        retrieval.terms_key(chunk): Counter(retrieval.tokenize(
            f"{chunk['title']} {chunk['quote']}")) for chunk in chunks
    } if prepared else None
    index = retrieval.RetrievalIndex(chunks, prepared_terms=terms)
    expected = retrieval._date_passages(request, chunks)
    actual = retrieval._date_passages(request, chunks, index=index)
    assert actual == expected
    return actual


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize(("event", "quote"), [
    ("admision", f"Fecha de admisiones: {DATE}."),
    ("examen", f"Fecha del examen: {DATE}."),
    ("admi", f"Fecha de admi\u0301sion: {DATE}."),
    ("admi", f"Fecha de admi\u1ab0sion: {DATE}."),
    ("infor", f"Fecha de infor\u0301mación: {DATE}."),
    ("atent", f"Fecha de atent\u0301amente: {DATE}."),
    # Left boundary cuts "preexamen" to "examen"; the complete token differs.
    ("examen", "preexamen" + " " * 174 + DATE + " fecha"),
    # Right boundary cuts "examenes" to "examen".
    ("examen", "fecha 20 de octubre" + " " * 174 + "examenes"),
    ("oficina", f"Fecha de oﬁcina: {DATE}."),
    ("examen", f"Fecha de ＥＸＡＭＥＮ: {DATE}."),
    ("examen", f"Fecha de examen²: {DATE}."),
    ("strasse", f"Fecha de Straße: {DATE}."),
    # Casefold expansion precedes the date and changes its offsets in old code.
    ("examen", f"ßßß fecha del examen: {DATE}."),
    ("examen", f"Fecha de examen2027: {DATE}."),
    ("examen", f"Fecha de pre_examen: {DATE}."),
])
def test_date_prefilter_preserves_raw_words_clipped_windows_and_unicode(event, quote, prepared):
    result = compare(event, [piece("hit", quote)], prepared=prepared)
    assert [row["chunk_id"] for row in result] == ["hit"]


def test_date_prefilter_preserves_full_results_order_and_proximity():
    chunks = [
        piece("far", "Fecha del examen " + "palabra " * 30 + DATE),
        piece("near", f"Fecha del examen {DATE}."),
        piece("near-copy", f"Fecha del examen {DATE}."),
        piece("other-event", f"Fecha de matrículas {DATE}."),
        piece("metadata-only", f"Fecha de matrículas {DATE}.", title="Examen"),
        piece("no-date", "Fecha del examen pendiente de confirmación."),
        piece("numeric-date", "Fecha del examen 22/10/2027."),
    ]
    result = compare("examen", chunks, prepared=True)
    assert len(result) == 2
    assert all(row["chunk_id"] not in {"far", "other-event", "metadata-only", "no-date"}
               for row in result)


def test_date_prefilter_skips_features_for_impossible_bodies(monkeypatch):
    chunks = [piece("irrelevant", f"Fecha de pagos {DATE}."),
              piece("found", f"Fecha del examen {DATE}.")]
    index = retrieval.RetrievalIndex(chunks)
    index.statistics(chunks)
    features = retrieval._calendar_features
    visited = []

    def counted(quote):
        visited.append(quote)
        return features(quote)

    monkeypatch.setattr(retrieval, "_calendar_features", counted)
    result = retrieval._date_passages({"title": "Fecha del examen"}, chunks, index=index)
    assert [row["chunk_id"] for row in result] == ["found"]
    assert visited == [chunks[1]["quote"]]


def test_date_prefilter_falls_back_for_event_inside_omitted_stopword():
    quote = f"Fecha de infor\u0301mación: {DATE}."
    chunks = [piece("partial-stopword", quote)]
    index = retrieval.RetrievalIndex(chunks)
    postings = index.statistics(chunks)[2]
    assert not any("infor" in term for term in postings)
    assert list(retrieval._calendar_candidates({"infor"}, chunks, index)) == chunks
    assert retrieval._date_passages({"title": "Fecha de infor"}, chunks, index=index)


def test_date_prefilter_observes_scope_and_text_changes_with_reused_index():
    visible = piece("visible", f"Fecha del examen: {DATE}.")
    private = {**piece("private", visible["quote"]), "collection_id": "unlinked"}
    foreign = {**piece("foreign", visible["quote"]), "case_id": "other"}
    chunks = [private, foreign, visible]
    request = {"title": "Fecha del examen", "description": "Consulta.",
               "case_id": "current", "allowed_collection_ids": []}
    index = retrieval.RetrievalIndex(chunks)
    actual = retrieval.retrieve(request, chunks, index=index)
    assert actual == retrieval.retrieve(request, [visible])
    assert {row["source_id"] for row in actual} == {"visible"}
    visible["quote"] = "Fecha del examen pendiente; no se ha anunciado."
    assert retrieval.retrieve(request, chunks, index=index) == retrieval.retrieve(request, chunks)
