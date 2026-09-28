from pqrs_claro.source_retrieval import RetrievalIndex, retrieve


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
