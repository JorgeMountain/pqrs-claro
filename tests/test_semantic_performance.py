import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from test_source_semantic import CountingModel, chunk

from pqrs_claro.source_semantic import SemanticIndex


def test_matrix_reuse_preserves_scores_and_current_metadata(tmp_path):
    pieces = [chunk("a", "El docente"), chunk("b", "La nómina")]
    cached = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel())
    uncached = SemanticIndex(tmp_path / "uncached", model_factory=lambda _: CountingModel(),
                             matrix_cache_bytes=0)
    for query in ("docente", "nómina", "docente"):
        assert cached.rank(query, pieces) == uncached.rank(query, pieces)
    assert cached.diagnostics["matrix_builds"] == 1
    assert cached.diagnostics["matrix_hits"] == 2
    pieces[0].update(review_status="reviewed", source_id="new-source")
    assert cached.rank("docente", pieces) == uncached.rank("docente", pieces)
    assert cached.diagnostics["matrix_builds"] == 1


@pytest.mark.parametrize("change", ["quote", "title", "reorder", "revoke", "duplicates"])
def test_mutations_and_scope_changes_match_fresh_search(tmp_path, change):
    pieces = [chunk("a", "El docente"), chunk("b", "La nómina")]
    cached = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel())
    cached.rank("docente", pieces)
    if change in {"quote", "title"}:
        pieces[0][change] = "La nómina"
    elif change == "reorder":
        pieces.reverse()
    elif change == "revoke":
        pieces.pop(0)
    else:
        pieces.append({**pieces[0], "chunk_id": "duplicate"})
    fresh = SemanticIndex(tmp_path / "fresh", model_factory=lambda _: CountingModel(),
                          matrix_cache_bytes=0)
    assert cached.rank("docente", pieces) == fresh.rank("docente", pieces)


def test_matrix_memory_budget_evicts_and_oversize_still_returns_results(tmp_path):
    index = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel(), matrix_cache_bytes=280)
    for i in range(8):
        assert index.rank("docente", [chunk(str(i), f"El docente {i}")])
        assert index.diagnostics["matrix_cache_bytes"] <= 280
    assert len(index._matrices) == 1
    pieces = [chunk(str(i), f"El docente {i}") for i in range(8)]
    assert len(index.rank("docente", pieces)) == 8
    assert index.diagnostics["matrix_cache_bytes"] <= 280


def test_concurrent_queries_do_not_mix_scope_or_duplicate_matrix_builds(tmp_path):
    index = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel())
    pieces = [chunk("a", "El docente"), chunk("b", "La nómina")]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: index.rank("docente", deepcopy(pieces)), range(12)))
    assert all(r == results[0] for r in results)
    assert index.diagnostics["matrix_builds"] == 1


def test_disk_cache_queries_only_requested_keys_and_keeps_model_namespace(tmp_path, monkeypatch):
    index = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel(), model_key="one")
    index.prepare([chunk(str(i), f"El docente {i}") for i in range(450)])
    statements = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    fresh = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel(), model_key="one")
    assert fresh.prepare([chunk("0", "El docente 0")])
    selects = [s for s in statements if s.startswith("SELECT text_key")]
    assert len(selects) == 1 and "text_key IN (" in selects[0]
    assert fresh.diagnostics["cached"] == 1
    assert len(fresh._vectors) == 1
    # A different embedding model must never reuse the first model's vectors.
    different = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel(), model_key="two")
    assert different.prepare([chunk("0", "El docente 0")])
    assert different.diagnostics["cached"] == 0


def test_query_cache_is_bounded_without_changing_ranking(tmp_path):
    index = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel())
    pieces = [chunk("a", "El docente")]
    expected = index.rank("docente 0", pieces)
    for i in range(140):
        index.rank(f"docente {i}", pieces)
    assert len(index._queries) == 128
    assert index.rank("docente 0", pieces) == expected
