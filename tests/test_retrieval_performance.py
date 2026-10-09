from pqrs_claro.source_retrieval import RetrievalIndex, retrieve


def test_unicode_normalization_preserves_all_combining_marks_and_token_boundaries():
    import re
    import unicodedata

    from pqrs_claro.source_retrieval import _STOPWORDS, tokenize

    text = "Matrícula Nº27 A2027 año 中文 ﬃ A\u1ab0x e\u0301q " + "".join(
        "x" + chr(code) for code in range(0x110000) if unicodedata.combining(chr(code))
    )
    old = "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                  if not unicodedata.combining(c))
    old = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", old)
    expected = [t for t in re.findall(r"[a-z0-9]+", old)
                if t not in _STOPWORDS and (len(t) > 1 or t.isdigit())]
    assert tokenize(text) == expected


def test_statistics_cache_observes_title_changes_with_same_id_and_quote():
    chunk = dict(chunk_id="one", title="Calendario", quote="Texto original sin cambios.")
    index = RetrievalIndex([chunk])
    assert "calendario" in index.statistics([chunk])[2]
    chunk["title"] = "Matrícula"
    assert index.statistics([chunk]) == RetrievalIndex([chunk]).statistics([chunk])
    assert "calendario" not in index.statistics([chunk])[2]


def test_posting_storage_stays_compact_for_a_large_repeated_vocabulary():
    import sys

    chunks = [dict(chunk_id=str(i), title="Normativa universitaria",
                   quote="Matrícula inscripción evaluación docente semestre calendario")
              for i in range(3000)]
    postings = RetrievalIndex(chunks).statistics(chunks)[2]
    occurrences = sum(len(positions) for positions, _ in postings.values())
    storage = sum(sys.getsizeof(positions) + sys.getsizeof(counts)
                  for positions, counts in postings.values())
    # Two compact numbers per occurrence; a Python tuple/list per hit exceeds this budget.
    assert storage < occurrences * 12


def test_calendar_cache_preserves_results_and_scope(monkeypatch):
    from pqrs_claro import source_retrieval as module

    chunks = [
        dict(
            chunk_id="public",
            source_id="public",
            document_id="public",
            title="Calendario",
            quote="El examen se presenta el 20 de octubre de 2027.",
            category="institutional_norm",
            validity="current",
            page=1,
            line_start=1,
            line_end=1,
        ),
        dict(
            chunk_id="private",
            source_id="private",
            document_id="private",
            title="Calendario",
            quote="El examen se presenta el 21 de octubre de 2027.",
            category="historical_response",
            collection_id="private",
            validity="current",
            page=1,
            line_start=1,
            line_end=1,
        ),
    ]
    query = dict(
        title="Fecha del examen",
        description="Cuándo se presenta el examen",
        case_id="example",
        allowed_collection_ids=[],
    )
    expected = retrieve(query, chunks)
    original = module._calendar_features
    calls = []

    def counted(quote):
        calls.append(quote)
        return original(quote)

    monkeypatch.setattr(module, "_calendar_features", counted)
    index = RetrievalIndex(chunks)
    assert retrieve(query, chunks, index=index) == expected
    assert retrieve(query, chunks, index=index) == expected
    assert len(calls) == 1
    assert all(row["source_id"] != "private" for row in expected)
    # Un cambio de texto con el mismo id no recupera las fechas antiguas.
    chunks[0]["quote"] = "Este documento no indica fechas de examen."
    assert retrieve(query, chunks, index=index) == retrieve(query, chunks)
