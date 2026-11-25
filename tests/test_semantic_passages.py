import numpy as np

from pqrs_claro.source_semantic import SemanticIndex


class Model:
    def __init__(self):
        self.calls = []

    def embed(self, texts, batch_size=32):
        self.calls.extend(texts)
        for text in texts:
            yield np.array([1.0, float("calendario" in text), float("firma" in text)])


def chunk(identity, text, **metadata):
    return {"chunk_id": identity, "source_id": identity, "quote": text, **metadata}


def test_local_ranking_reuses_query_and_preserves_full_library_matrix(tmp_path):
    model = Model()
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)
    pieces = [chunk(str(i), f"calendario {i}") for i in range(8)]
    index.prepare(pieces)
    expected = index.rank("calendario", pieces)
    matrices = dict(index._matrices)
    cache_bytes = index.diagnostics["matrix_cache_bytes"]
    calls = list(model.calls)
    for piece in pieces:
        assert index.rank_passages("calendario", [piece])[0]["chunk_id"] == piece["chunk_id"]
    assert index.rank_passages("calendario", pieces) == expected
    assert model.calls == calls
    assert list(index._matrices) == list(matrices)
    assert all(index._matrices[key] is matrix for key, matrix in matrices.items())
    assert index.diagnostics["matrix_cache_bytes"] == cache_bytes
    assert index.diagnostics["matrix_builds"] == 1


def test_local_ranking_uses_current_scope_and_metadata_and_ignores_unprepared_changes(tmp_path):
    model = Model()
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)
    hidden = chunk("hidden", "calendario oculto", collection_id="revoked")
    old = chunk("allowed", "firma", version=1)
    index.prepare([hidden, old])
    index.rank("firma", [hidden, old])
    calls = list(model.calls)
    current = {**old, "review_status": "reviewed", "version": 2}
    result = index.rank_passages("firma", [current])
    assert [item["chunk_id"] for item in result] == ["allowed"]
    assert result[0]["version"] == 2
    assert result[0]["review_status"] == "reviewed"
    assert index.rank_passages("firma", [{**current, "quote": "firma corregida"}]) == []
    assert model.calls == calls
    index.prepare([{**current, "quote": "firma corregida"}])
    assert (
        index.rank_passages("firma", [{**current, "quote": "firma corregida"}])[0]["quote"]
        == "firma corregida"
    )


def test_local_stack_failure_preserves_prepared_global_channel(tmp_path, monkeypatch):
    index = SemanticIndex(tmp_path, model_factory=lambda _: Model())
    pieces = [chunk(str(i), f"calendario {i}") for i in range(6)]
    index.prepare(pieces)
    expected = index.rank("calendario", pieces)

    def fail_stack(*args):
        raise MemoryError("failed to allocate a local matrix")

    monkeypatch.setattr(np, "stack", fail_stack)
    assert index.rank_passages("calendario", pieces[:3]) == []
    assert index.diagnostics["passage_rank_errors"] == 1
    assert index.rank("calendario", pieces) == expected
