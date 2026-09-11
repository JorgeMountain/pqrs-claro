"""Páginas y literales explícitos recuperan texto original e identidad por separado."""

from copy import deepcopy

import pytest

from pqrs_claro.source_retrieval import retrieve


def request(text="Qué dice el Oficio 0174-2025 en el literal a de la página 9 sobre docencia"):
    return {
        "id": "P1", "case_id": "case", "title": "Consulta del antecedente",
        "description": text, "allowed_collection_ids": ["collection"],
    }


def chunk(page, start, end, quote, **changes):
    return {
        "source_id": "document", "document_id": "document", "version": 1,
        "chunk_id": f"document:{page}:{start}:{end}",
        "category": "historical_response", "collection_id": "collection", "case_id": None,
        "title": "Oficio 0174-2025", "filename": "Oficio_0174-2025.pdf",
        "page": page, "line_start": start, "line_end": end, "quote": quote,
        "review_status": "pending", "document_status": "unknown", "method": "native",
        "needs_review": False, "validity": "not_applicable", **changes,
    }


def test_literal_inside_a_pdf_fragment_survives_stronger_other_numerals():
    answer = chunk(9, 28, 33, "Fin del contexto.\na) ¿Correspondió a ese período?\nRespuesta: No.")
    corpus = [chunk(i, 1, 3, "docencia " * 35) for i in range(2, 9)] + [
        chunk(9, 1, 29, "Docencia en distintos períodos. " * 30), answer,
        chunk(1, 1, 2, "Oficio 0174-2025\nCiudad de prueba"),
    ]
    before = deepcopy(corpus)
    results = retrieve(request(), corpus)
    assert results[0]["chunk_id"] == answer["chunk_id"]
    assert results[0]["quote"] == answer["quote"]
    assert results[0]["retrieval_channel"] == "requested_passage"
    assert corpus == before
    assert len(results) <= 24


def test_literal_without_page_can_retrieve_an_answer_that_begins_after_the_question():
    anchor = chunk(4, 10, 11, "Contexto previo.\na) ¿Fue asignada?")
    following = chunk(4, 12, 12, "Respuesta: Sí.")
    next_question = chunk(4, 13, 13, "b) ¿Otra consulta?")
    results = retrieve(request("Qué dice el literal a del Oficio 0174-2025"),
                       [anchor, following, next_question])
    answer = next(row for row in results if row["chunk_id"] == following["chunk_id"])
    assert answer["adjacent_to"] == anchor["chunk_id"]
    assert not any(row.get("adjacent_to") for row in results
                   if row["chunk_id"] == next_question["chunk_id"])


@pytest.mark.parametrize("location", ["página 6", "pagina 6", "pág. 6"])
def test_exact_full_identifier_header_is_a_separate_unchanged_candidate(location):
    title = "Oficio 0174_Respuesta a comunicación"
    header = chunk(1, 1, 2, "21360001-0174-2025\nCiudad de prueba",
                   title=title, filename=title + ".pdf")
    passage = chunk(6, 1, 2, "El curso se ofertó como espejo de otro curso.",
                    title=title, filename=title + ".pdf")
    results = retrieve(request(f"Qué describe el Oficio 21360001-0174-2025 en la {location}"),
                       [header, passage])
    assert results[0]["chunk_id"] == passage["chunk_id"]
    assert results[0]["quote"] == passage["quote"]
    identity = next(row for row in results if row["chunk_id"] == header["chunk_id"])
    assert identity["retrieval_channel"] == "document_identity"
    assert identity["quote"] == header["quote"]
    assert identity["document_status"] == "unknown"
    assert identity["review_status"] == "pending"


@pytest.mark.parametrize("change", [
    {"collection_id": "private"}, {"case_id": "different"},
    {"category": "previous_response"}, {"validity": "superseded"},
])
def test_targeted_location_never_overrides_scope_or_category(change):
    private = chunk(9, 1, 2, "a) ¿Docencia?\nRespuesta: No.", **change)
    assert retrieve(request(), [private]) == []


def test_same_number_from_another_year_is_not_a_targeted_location():
    wrong = chunk(9, 1, 2, "a) ¿Docencia?\nRespuesta: Sí.",
                  title="Oficio 0174-2024", filename="Oficio_0174-2024.pdf")
    correct = chunk(9, 1, 2, "a) ¿Docencia?\nRespuesta: No.",
                    chunk_id="current:9:1:2", source_id="current", document_id="current")
    result = retrieve(request(), [wrong, correct])
    assert result[0]["source_id"] == "current"
    assert all(row["source_id"] == "current" for row in result
               if row["retrieval_channel"] == "requested_passage")


def test_ambiguous_pages_for_two_named_offices_do_not_assign_one_location_to_both():
    result = retrieve(request("Compare Oficio 0174-2025 página 9 con Oficio 0185-2025 página 4"),
                      [chunk(9, 1, 2, "a) ¿Docencia?\nRespuesta: No.")])
    assert not any(row["retrieval_channel"] == "requested_passage" for row in result)


@pytest.mark.parametrize("limit", [1, 2, 24, 80])
def test_targeted_candidates_respect_the_total_limit(limit):
    corpus = [chunk(9, i, i, f"a) Docencia {i}.") for i in range(1, 30)]
    result = retrieve(request(), corpus, limit=limit)
    assert len(result) <= min(limit, 24)
    assert len({row["chunk_id"] for row in result}) == len(result)


def test_document_merely_mentioned_in_a_different_file_is_not_targeted():
    mention = chunk(9, 1, 2, "El Oficio 0174-2025 dice: a) Docencia.",
                    title="Oficio 0002-2025", filename="Oficio_0002-2025.pdf")
    result = retrieve(request(), [mention])
    assert not any(row["retrieval_channel"] == "requested_passage" for row in result)
