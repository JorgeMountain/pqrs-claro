from collections import Counter

import pytest

from pqrs_claro import source_retrieval as retrieval


def piece(identity, quote, *, title="Archivo", document=None):
    return {
        "chunk_id": identity, "source_id": identity,
        "document_id": document or identity, "title": title, "quote": quote,
        "category": "institutional_norm", "case_id": None,
        "page": 1, "line_start": 1, "line_end": 1,
    }


def compare(title, chunks, *, prepared=False):
    request = {"title": title, "description": "Consulta de prueba"}
    terms = {
        retrieval.terms_key(chunk): Counter(retrieval.tokenize(
            f"{chunk['title']} {chunk['quote']}")) for chunk in chunks
    } if prepared else None
    index = retrieval.RetrievalIndex(chunks, prepared_terms=terms)
    expected = retrieval._topic_passages(request, chunks)
    actual = retrieval._topic_passages(request, chunks, index=index)
    assert actual == expected
    return actual


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("title", [
    "Constancia académica", "Certificaciones económicas", "Oficios públicos",
    "Consultas técnicas", "Plan 2026", "Plan 1", "ICA ICO",
    "Uno dos tres cuatro cinco seis siete", "Plán α académico",
])
def test_prefilter_preserves_phrase_variants_boundaries_and_order(title, prepared):
    bodies = [
        "Los certificados académicos se expiden aquí.",
        "Las constancias de información académica se solicitan aquí.",
        "Certificaciones económicas y certificados económicos.",
        "Una consulta técnica y varios oficios públicos.",
        "Oficio publico; consulta tecnica.",
        "Plan 2026.", "Plan2026.", "_plan 2026.", "αplan 2026.",
        "Plan ２０２６.", "ＰＬＡＮ ２０２６.", "Plan 1.", "Plan ¼.",
        "Plan ١.", "Plan 1α.", "Plan 1_ académico.",
        "Constancia_academica.", "Constanciaacadémica.",
        "Constancia académicaα.", "Constancia α académica.",
        "Constancia 学生 académica.", "Constancia _ académica.",
        "Constancia ٢ académica.", "CONSTANCIA ACADE\u0301MICA.",
        "ＣＯＮＳＴＡＮＣＩＡ ＡＣＡＤＥＭＩＣＡ.",
        "Ica ico icas icos.", "Dos tres cuatro.", "Seis siete.",
        *["Constancia " + "palabra " * gap + "académica." for gap in range(6)],
    ]
    chunks = [piece(f"item-{i:03}", body) for i, body in enumerate(bodies)]
    # An identical body must retain the first original, even if IDs sort differently.
    chunks = [piece("z-first", bodies[0]), *chunks, piece("a-last", bodies[0])]
    chunks.append(piece("metadata-only", "No trata del tema.", title=title))
    compare(title, chunks, prepared=prepared)


def test_prefilter_falls_back_if_tokenization_drops_a_variant(monkeypatch):
    monkeypatch.setattr(retrieval, "_STOPWORDS", retrieval._STOPWORDS | {"oficio"})
    chunks = [piece("singular", "El oficio público debe conservarse.")]
    result = compare("Oficios públicos", chunks, prepared=True)
    assert [row["chunk_id"] for row in result] == ["singular"]


def test_prefilter_uses_any_of_first_four_pairs_and_original_document_budgets():
    chunks = [piece(f"shared-{i}", f"Dos tres asunto {i}.", document="shared")
              for i in range(15)]
    chunks.extend(piece(f"unique-{i}", f"Cuatro cinco tema {i}.") for i in range(18))
    chunks.append(piece("after-fourth-pair", "Seis siete."))
    result = compare("Uno dos tres cuatro cinco seis siete", chunks, prepared=True)
    assert len(result) == 12
    assert sum(row["document_id"] == "shared" for row in result) <= 3
    assert "after-fourth-pair" not in {row["chunk_id"] for row in result}


def test_prefilter_skips_normalizing_irrelevant_bodies(monkeypatch):
    noise = "Un texto sin ninguna palabra del tema solicitado."
    chunks = [piece("irrelevant", noise), piece("found", "Certificados académicos.")]
    index = retrieval.RetrievalIndex(chunks)
    index.statistics(chunks)
    normalize = retrieval.unicodedata.normalize
    visited = []

    def counted(form, text):
        visited.append(text)
        return normalize(form, text)

    monkeypatch.setattr(retrieval.unicodedata, "normalize", counted)
    result = retrieval._topic_passages({"title": "Constancia académica"}, chunks, index=index)
    assert [row["chunk_id"] for row in result] == ["found"]
    assert noise.casefold() not in visited


def test_prefilter_keeps_authorized_subset_and_does_not_reuse_stale_text():
    visible = piece("visible", "Certificados académicos.")
    private = {**piece("private", visible["quote"]), "collection_id": "unlinked"}
    foreign = {**piece("foreign", visible["quote"]), "case_id": "other"}
    chunks = [private, foreign, visible]
    request = {"title": "Constancia académica", "description": "Consulta.",
               "case_id": "current", "allowed_collection_ids": []}
    index = retrieval.RetrievalIndex(chunks)
    actual = retrieval.retrieve(request, chunks, index=index)
    assert actual == retrieval.retrieve(request, [visible])
    assert {row["source_id"] for row in actual} == {"visible"}
    visible["quote"] = "Esta versión no contiene información del trámite."
    assert retrieval.retrieve(request, chunks, index=index) == retrieval.retrieve(request, chunks)
