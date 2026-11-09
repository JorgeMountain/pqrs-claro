"""Exact semantic selection must retain ties, original citations and scope."""

import sqlite3
from contextlib import closing
from copy import deepcopy

import numpy as np
import pytest

from pqrs_claro.source_retrieval import retrieve
from pqrs_claro.source_semantic import SemanticIndex


def passage(number, *, chunk_id=None, quote=None):
    return {
        "chunk_id": str(number) if chunk_id is None else chunk_id,
        "source_id": f"source-{number}",
        "title": "Documento",
        "quote": quote or f"Fragmento original {number}",
        "collection_id": "allowed",
        "page": 1,
        "line_start": 1,
        "line_end": 1,
        "version": 1,
    }


class FixedModel:
    def __init__(self, passages, vectors, query):
        self.documents = {
            f"passage: {row['title']}\n{row['quote']}": np.asarray(vector, dtype=np.float32)
            for row, vector in zip(passages, vectors, strict=True)
        }
        self.query = np.asarray(query, dtype=np.float32)

    def embed(self, texts, batch_size=32):
        for text in texts:
            yield self.query.copy() if text.startswith("query: ") else self.documents[text].copy()


def exact_reference(passages, vectors, query, limit):
    stored = [
        (value := np.asarray(vector, dtype=np.float32)) / np.linalg.norm(value)
        for vector in vectors
    ]
    # Reproduce the historical SQLite reader's normalization before the full sort.
    normalized = [vector / np.linalg.norm(vector) for vector in stored]
    query = np.asarray(query, dtype=np.float32)
    scores = np.stack(normalized) @ (query / np.linalg.norm(query))
    positions = sorted(
        range(len(passages)),
        key=lambda i: (-float(scores[i]), str(passages[i].get("chunk_id", ""))),
    )[:limit]
    return [
        {**passages[i], "semantic_score": round(float(scores[i]), 8)} for i in positions
    ]


def test_reopened_and_new_equal_embeddings_keep_the_historical_score_and_top_citation(tmp_path):
    rows = [{**passage(i, chunk_id=key), "document_id": key, "category": "institutional_norm"}
            for i, key in enumerate(("z", "a"))]
    vector = np.array([1, 1, 1], dtype=np.float32)
    vectors = [vector, vector]
    model = FixedModel(rows, vectors, vector)
    stored = vector / np.linalg.norm(vector)
    assert np.linalg.norm(stored) != np.float32(1)
    expected = exact_reference(rows, vectors, vector, 2)
    assert [row["chunk_id"] for row in expected] == ["a", "z"]

    def index(name):
        return SemanticIndex(tmp_path / name, model_factory=lambda _: model)

    fresh = index("fresh")
    assert fresh.prepare(rows)
    # The on-disk format remains the normalized float32 blob used by earlier releases.
    with closing(sqlite3.connect(tmp_path / "fresh" / "embeddings.sqlite")) as db:
        assert db.execute("SELECT vector FROM embeddings").fetchall() == [
            (stored.astype("<f4").tobytes(),)
        ] * 2
    seeded = index("mixed")
    assert seeded.prepare(rows[:1])
    mixed = index("mixed")
    assert mixed.prepare(rows)
    assert mixed.diagnostics["cached"] == mixed.diagnostics["encoded"] == 1
    reopened = index("fresh")
    assert reopened.prepare(rows)
    assert reopened.diagnostics["cached"] == 2 and reopened.diagnostics["encoded"] == 0
    for instance in (fresh, mixed, reopened):
        assert instance.rank("quásar", rows) == expected
        assert retrieve({"title": "quásar", "allowed_collection_ids": ["allowed"]},
                        rows, semantic=instance, limit=1) == [
            {**expected[0], "retrieval_channel": "semantic"}
        ]


@pytest.mark.parametrize("limit", [1, 7, 24, 256, 257, 300])
def test_partial_selection_matches_exact_reference_for_random_vectors(tmp_path, limit):
    rng = np.random.default_rng(20261106)
    pieces = [passage(i) for i in range(257)]
    vectors = rng.normal(size=(len(pieces), 16)).astype(np.float32)
    query = rng.normal(size=16).astype(np.float32)
    model = FixedModel(pieces, vectors, query)
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)

    assert index.rank("consulta", pieces, limit=limit) == exact_reference(
        pieces, vectors, query, limit
    )
    assert index.warning is None


def test_cutoff_ties_keep_id_order_and_original_order_of_duplicate_ids(tmp_path):
    pieces = [
        passage(0, chunk_id="winner"),
        passage(1, chunk_id="z"),
        passage(2, chunk_id="a"),
        passage(3, chunk_id="a"),
        passage(4, chunk_id="b"),
        passage(5, chunk_id="loser"),
    ]
    vectors = np.array([[1, 0], [0, 1], [0, -1], [0, 1], [0, -1], [-1, 0]],
                       dtype=np.float32)
    query = np.array([1, 0], dtype=np.float32)
    model = FixedModel(pieces, vectors, query)
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)

    for limit in (1, 3, 4, 6, 10):
        assert index.rank("consulta", pieces, limit=limit) == exact_reference(
            pieces, vectors, query, limit
        )
    selected = index.rank("consulta", pieces, limit=3)
    assert [row["source_id"] for row in selected] == ["source-0", "source-2", "source-3"]
    # Reversing the input must also reverse the stable order of identical IDs.
    reversed_pieces = list(reversed(pieces))
    assert index.rank("consulta", reversed_pieces, limit=3) == exact_reference(
        reversed_pieces, vectors[::-1], query, 3
    )


def test_all_equal_scores_preserve_stable_top_k(tmp_path):
    pieces = [passage(i, chunk_id=f"id-{i % 17:02}") for i in range(513)]
    vectors = np.tile(np.array([0, 1], dtype=np.float32), (len(pieces), 1))
    query = np.array([1, 0], dtype=np.float32)
    model = FixedModel(pieces, vectors, query)
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)

    assert index.rank("consulta", pieces, limit=24) == exact_reference(
        pieces, vectors, query, 24
    )


def test_ranking_uses_unrounded_scores_even_when_displayed_scores_match(tmp_path):
    first = np.float32(0.01)
    second = np.nextafter(first, np.float32(1))
    third = np.nextafter(second, np.float32(1))
    pieces = [passage(0, chunk_id="a"), passage(1, chunk_id="m"), passage(2, chunk_id="z")]
    vectors = np.array([[value, np.sqrt(np.float32(1) - value * value)]
                        for value in (first, second, third)], dtype=np.float32)
    query = np.array([1, 0], dtype=np.float32)
    expected = exact_reference(pieces, vectors, query, 3)
    assert len({row["semantic_score"] for row in expected}) == 1
    assert [row["chunk_id"] for row in expected] == ["z", "m", "a"]
    model = FixedModel(pieces, vectors, query)
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)

    assert index.rank("consulta", pieces, limit=2) == expected[:2]


def test_cached_matrix_keeps_current_metadata_and_never_restores_revoked_passages(tmp_path):
    pieces = [passage(i) for i in range(4)]
    vectors = np.array([[1, 0], [0.8, 0.6], [0, 1], [-1, 0]], dtype=np.float32)
    query = np.array([1, 0], dtype=np.float32)
    model = FixedModel(pieces, vectors, query)
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)
    assert index.rank("consulta", pieces, limit=2) == exact_reference(pieces, vectors, query, 2)

    current = deepcopy(pieces)
    current[0].update(source_id="new-source", version=2, page=9, review_status="reviewed")
    assert index.rank("consulta", current, limit=2) == exact_reference(current, vectors, query, 2)
    assert index.diagnostics["matrix_builds"] == 1
    allowed = current[1:]
    assert index.rank("consulta", allowed, limit=2) == exact_reference(
        allowed, vectors[1:], query, 2
    )
    assert all(row["source_id"] != "new-source" for row in index.rank("consulta", allowed))


def test_cache_evicts_before_allocating_a_replacement_matrix(tmp_path, monkeypatch):
    first = [passage(i) for i in range(2)]
    second = [passage(i) for i in range(2, 4)]
    vectors = np.array([[1, 0], [0, 1], [-1, 0], [0, -1]], dtype=np.float32)
    query = np.array([1, 0], dtype=np.float32)
    model = FixedModel([*first, *second], vectors, query)
    sizing = SemanticIndex(tmp_path / "sizing", model_factory=lambda _: model)
    assert sizing.rank("consulta", first)
    budget = sizing.diagnostics["matrix_cache_bytes"]
    index = SemanticIndex(tmp_path / "bounded", model_factory=lambda _: model,
                          matrix_cache_bytes=budget)
    assert index.rank("consulta", first)
    assert index.diagnostics["matrix_cache_bytes"] == budget
    original_stack = np.stack
    allocations = []

    def checked_stack(*args, **kwargs):
        allocations.append(index.diagnostics["matrix_cache_bytes"])
        assert index.diagnostics["matrix_cache_bytes"] == 0
        return original_stack(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(np, "stack", checked_stack)
        selected = index.rank("consulta", second)
    assert allocations == [0]
    assert selected == exact_reference(second, vectors[2:], query, len(second))
    assert index.diagnostics["matrix_cache_bytes"] <= budget
    assert index.warning is None
