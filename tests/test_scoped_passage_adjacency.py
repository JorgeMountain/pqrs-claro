"""Ordering, document boundaries and current citations in prepared passage groups."""

import pytest

from pqrs_claro import source_retrieval as retrieval


def piece(chunk_id, page, start, quote, *, source="pdf", **changes):
    return {
        "chunk_id": chunk_id, "source_id": source, "document_id": "lineage",
        "page": page, "line_start": start, "line_end": start,
        "quote": quote, "title": "Oficio 72-2027", "filename": f"Oficio 72-2027.{source}",
        "category": "historical_response", "collection_id": "archivo", "case_id": None,
        "location_kind": "page" if source == "pdf" else "section", **changes,
    }


def test_equal_coordinates_keep_input_order_and_duplicate_ids_keep_first_position():
    anchor = piece("anchor", 3, 1, "¿Cuándo se presenta?")
    first = piece("z", 3, 2, "Primera respuesta.")
    second = piece("a", 3, 2, "Segunda respuesta.")
    other = piece("different-file", 3, 2, "Otra versión en Word.", source="docx")
    duplicate = piece("anchor", 3, 7, "¿Otra pregunta con el mismo ID?")
    rows = [other, first, anchor, second, duplicate]
    groups = retrieval._PassageGroups(rows)
    assert groups.by_id["anchor"] == duplicate
    assert list(groups.following(duplicate, 2)) == [first, second]
    assert retrieval._adjacent_answer(anchor, rows, passages=groups) == [anchor, first, second]
    assert rows == [other, first, anchor, second, duplicate]


@pytest.mark.parametrize("source", ["pdf", "docx"])
def test_contiguous_passages_honor_the_page_gap_and_the_two_inclusive_limits(source):
    anchor = piece("q", 3, 1, "¿Qué ocurrió?", source=source)
    tail = [piece(str(n), 4, n, f"Respuesta {n}.", source=source) for n in range(1, 9)]
    rows = [anchor, *reversed(tail)]
    groups = retrieval._PassageGroups(rows)
    assert retrieval._adjacent_answer(anchor, rows, passages=groups) == [anchor, *tail[:7]]

    exact = {**tail[0], "quote": "x" * (6500 - len(anchor["quote"]))}
    distant = piece("gap", 6, 1, "Continuación posterior.", source=source)
    for neighbor, following, expected in [
        (exact, tail[1], [anchor, exact]),
        ({**exact, "quote": exact["quote"] + "x"}, tail[1], []),
        (tail[0], distant, [anchor, tail[0]]),
        (tail[0], {**tail[1], "quote": "SEGUNDO: Otro asunto."}, [anchor, tail[0]]),
    ]:
        scope = [following, neighbor, anchor]
        groups = retrieval._PassageGroups(scope)
        assert retrieval._adjacent_answer(anchor, scope, passages=groups) == expected


def test_targeted_neighbor_and_header_use_different_tie_breakers():
    anchor = piece("literal", 3, 1, "Contexto.\na) ¿En qué consistió?", line_end=2)
    first = piece("z-neighbor", 3, 3, "Primera continuación.")
    second = piece("a-neighbor", 3, 3, "Otra continuación.")
    other = piece("docx", 3, 2, "Contenido de otra fuente.", source="docx")
    last_header = piece("z-header", 1, 1, "Oficio 72-2027\nFirmado.")
    header = piece("a-header", 1, 1, "Oficio 72-2027\nUniversidad.")
    rows = [other, first, last_header, header, anchor, second]
    request = {"title": "Contenido del literal a del Oficio 72-2027"}
    result = retrieval._targeted_passages(request, rows, index=retrieval.RetrievalIndex(rows),
                                         passages=retrieval._PassageGroups(rows))
    assert result == [(anchor, "requested_passage"),
                      ({**first, "adjacent_to": "literal"}, "adjacent_answer"),
                      (header, "document_identity")]


def test_answer_boundaries_use_document_id_line_end_and_original_order():
    marker = piece("start", 2, 10, "Portada.\nDamos respuesta a su solicitud.", line_end=11)
    early = piece("before", 2, 10, "Antes del marcador.")
    reaches = piece("overlap", 2, 9, "Fragmento que alcanza la respuesta.", line_end=11)
    other_source = piece("after", 3, 1, "Mismo documento lógico.", source="docx",
                         category="historical_attachment")
    reproduced = piece("request", 3, 2, "En el numeral tercero usted solicita lo siguiente.")
    unrelated = piece("different-document", 5, 1, "Sin marcador.", document_id="other")
    rows = [other_source, early, unrelated, reaches, reproduced, marker]
    groups = retrieval._PassageGroups(rows)
    assert retrieval._answer_chunks(rows, historical=groups.historical) == [
        other_source, reaches, marker,
    ]


def test_standalone_baseline_filters_unauthorized_markers_before_selecting_answers():
    ordinary = piece("general", 3, 1, "Arancel de matrícula.")
    hidden = piece("hidden", 2, 1, "Damos respuesta a su solicitud. Arancel de matrícula.",
                   collection_id="revocable")
    rows = [hidden, ordinary]
    request = {"title": "Arancel de matrícula", "allowed_collection_ids": ["archivo"]}
    index = retrieval.RetrievalIndex(rows)
    allowed = [ordinary]
    expected = retrieval._rank(request, allowed)
    assert [row["chunk_id"] for row in expected] == ["general"]
    assert retrieval._baseline(request, rows, index=index) == expected
    assert retrieval._baseline(request, allowed, index=index,
                               passages=retrieval._PassageGroups(allowed)) == expected


def test_document_metadata_uses_first_row_per_source_before_ordering_for_adjacency():
    cover = piece("cover", 8, 1, "Convocatoria.", title="Admisión primavera")
    answer = piece("answer", 2, 1, "El examen dura cinco horas.")
    other = piece("docx", 2, 1, "El examen dura seis horas.", source="docx")
    request = {"title": "Duración del examen", "context": {"subject": "Admisión primavera"}}
    for rows, expected in [([cover, other, answer], [answer]), ([answer, other, cover], [])]:
        groups = retrieval._PassageGroups(rows)
        assert not list(groups.following(cover, 1))
        assert retrieval._document_content(request, rows, index=retrieval.RetrievalIndex(rows),
                                           passages=groups) == expected


def test_reused_index_refreshes_scope_and_current_line_boundaries_and_citations():
    anchor = piece("literal", 4, 3, "Nota.\na) ¿Cuál es el contenido?", line_end=4)
    reply = piece("answer", 4, 5, "Respuesta original.", version=1)
    foreign = piece("foreign", 4, 4, "Oficio 72-2027 del otro expediente.",
                    source="docx", collection_id="revocable")
    rows = [foreign, reply, anchor]
    request = {"title": "Contenido del literal a del Oficio 72-2027",
               "allowed_collection_ids": ["archivo", "revocable"], "case_id": "actual"}
    index = retrieval.RetrievalIndex(rows)
    original = retrieval.retrieve(request, rows, index=index)
    assert any(r.get("adjacent_to") == "literal" and r["quote"] == reply["quote"]
               for r in original)
    assert any(r["chunk_id"] == "foreign" for r in original)

    permitted = {**request, "allowed_collection_ids": ["archivo"]}
    updated = {**reply, "page": 5, "line_start": 11, "line_end": 13,
               "quote": "Respuesta reemplazada.", "version": 2, "review_status": "reviewed"}
    # The same IDs now refer to new row objects and updated citation coordinates.
    current_anchor = {**anchor, "page": 5, "line_start": 8, "line_end": 10}
    for end, attached in [(10, True), (9, False)]:
        current_anchor["line_end"] = end
        expected = retrieval.retrieve(permitted, [updated, current_anchor])
        actual = retrieval.retrieve(permitted, [foreign, updated, current_anchor], index=index)
        assert actual == expected
        assert all(row["chunk_id"] != "foreign" for row in actual)
        neighbors = [row for row in actual if row.get("adjacent_to") == "literal"]
        assert [row["chunk_id"] for row in neighbors] == (["answer"] if attached else [])
        if attached:
            assert {key: neighbors[0][key] for key in updated} == updated


def test_answer_marker_cache_rechecks_text_and_current_document_coordinates():
    marker = piece("marker", 2, 10, "Portada.\nDamos respuesta a su solicitud.", line_end=11)
    after = piece("answer", 2, 12, "Condiciones de inscripción.")
    index = retrieval.RetrievalIndex([marker, after])
    assert retrieval._answer_chunks([marker, after], index=index) == [marker, after]

    moved = {**marker, "line_start": 15, "line_end": 16}
    assert retrieval._answer_chunks([moved, after], index=index) == [moved]
    assert index._answer_line_cache.cache_info().hits == 2
    edited = {**moved, "quote": "Una portada sin marcador."}
    assert retrieval._answer_chunks([edited, after], index=index) == []

    large = {**marker, "quote": "Damos respuesta a su solicitud." + "z" * 9000}
    before = index._answer_line_cache.cache_info()
    assert retrieval._answer_chunks([large, after], index=index) == [large, after]
    assert index._answer_line_cache.cache_info().misses == before.misses
