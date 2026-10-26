"""Interactive cache reuse cannot accidentally trigger a corpus-wide backfill."""

import threading

import pytest
from test_source_semantic import CountingModel, chunk

from pqrs_claro import source_semantic
from pqrs_claro.source_semantic import SemanticIndex


def test_zero_budget_loads_all_authorized_cached_vectors_without_encoding_missing(tmp_path):
    cached = [chunk("a", "El docente"), chunk("b", "La nómina")]
    hidden = chunk("hidden", "Documento ajeno", collection="otro")
    assert SemanticIndex(tmp_path, model_factory=lambda _: CountingModel()).prepare(
        [*cached, hidden])
    model = CountingModel()
    index = SemanticIndex(tmp_path, model_factory=lambda _: model, preparation_budget_seconds=0)
    pending = chunk("pending", "La respuesta aún sin vector")
    progress = []
    assert not index.prepare([*cached, pending], progress=progress.append)
    assert model.calls == []
    assert index.diagnostics["total"] == 3
    assert index.diagnostics["prepared"] == 2
    assert index.diagnostics["pending"] == 1
    assert not index.diagnostics["complete"]
    assert index.diagnostics["budget_exhausted"]
    assert "cobertura parcial" in index.warning
    assert progress[-1] == index.diagnostics
    result = index.rank("docente", [cached[0], pending])
    assert [r["chunk_id"] for r in result] == ["a"]
    assert all(text.startswith("query: ") for text in model.calls)
    assert len(index._vectors) == 2  # No vector from the unrelated cached collection.


def test_empty_zero_budget_never_loads_model_and_rank_does_not_restart_backfill(tmp_path):
    def forbidden(_):
        pytest.fail("A missing corpus must not load the model at zero preparation budget")

    index = SemanticIndex(tmp_path, model_factory=forbidden, preparation_budget_seconds=0)
    pieces = [chunk("a", "El docente")]
    assert not index.prepare(pieces)
    assert index.rank("docente", pieces) == []
    assert index.rank("docente", pieces) == []
    assert index.diagnostics["encoded"] == 0
    assert index.diagnostics["pending"] == 1


def test_deadline_stops_between_committed_batches_and_reports_unique_total(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(source_semantic.time, "monotonic", lambda: clock[0])

    class SlowModel(CountingModel):
        def embed(self, texts, batch_size=32):
            yield from super().embed(texts, batch_size=batch_size)
            clock[0] += 2

    pieces = [chunk(str(i), f"El docente {i}") for i in range(5)]
    model = SlowModel()
    index = SemanticIndex(tmp_path, model_factory=lambda _: model,
                          preparation_budget_seconds=1, batch_size=2)
    progress = []
    assert not index.prepare([*pieces, pieces[0]], progress=progress.append)
    assert progress[0]["prepared"] == 0 and progress[0]["pending"] == 5
    assert index.diagnostics["total"] == 5
    assert index.diagnostics["prepared"] == 2 and index.diagnostics["pending"] == 3
    assert index.diagnostics["encoded"] == 2
    index.rank("docente", pieces)
    index.rank("nómina", pieces)
    assert len([t for t in model.calls if t.startswith("passage:")]) == 2

    resumed_model = CountingModel()
    resumed = SemanticIndex(tmp_path, model_factory=lambda _: resumed_model)
    assert resumed.prepare(pieces)
    assert resumed.diagnostics["cached"] == 2
    assert resumed.diagnostics["encoded"] == 3
    assert resumed.diagnostics["complete"] and resumed.diagnostics["pending"] == 0
    fresh = SemanticIndex(tmp_path / "fresh", model_factory=lambda _: CountingModel())
    # Loading persisted float32 vectors renormalizes them; tied scores can differ
    # by one rounding unit. Check complete coverage and the actual cosine scores.
    def scores(rows):
        return {row["chunk_id"]: row["semantic_score"] for row in rows}
    assert scores(resumed.rank("docente", pieces)) == pytest.approx(
        scores(fresh.rank("docente", pieces)), abs=1e-6)


def test_deadline_is_shared_across_explicit_prepare_calls(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(source_semantic.time, "monotonic", lambda: clock[0])
    model = CountingModel()
    index = SemanticIndex(tmp_path, model_factory=lambda _: model, preparation_budget_seconds=1)
    first = chunk("first", "El docente")
    assert index.prepare([first])
    clock[0] = 2
    assert not index.prepare([first, chunk("second", "La nómina")])
    assert len(model.calls) == 1
    assert index.diagnostics["prepared"] == 1 and index.diagnostics["pending"] == 1


def test_cancellation_preserves_the_committed_batch_for_full_resume(tmp_path):
    stop = threading.Event()

    class CancellingModel(CountingModel):
        def embed(self, texts, batch_size=32):
            yield from super().embed(texts, batch_size=batch_size)
            stop.set()

    pieces = [chunk("a", "El docente"), chunk("b", "La nómina")]
    index = SemanticIndex(tmp_path, model_factory=lambda _: CancellingModel(),
                          stop_event=stop, batch_size=1)
    assert not index.prepare(pieces)
    assert index.diagnostics["cancelled"] and not index.diagnostics["budget_exhausted"]
    assert index.rank("docente", pieces) == []
    resumed = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel())
    assert resumed.prepare(pieces)
    assert resumed.diagnostics["cached"] == 1 and resumed.diagnostics["encoded"] == 1


def test_all_cached_scope_is_complete_even_with_zero_budget(tmp_path):
    pieces = [chunk("a", "El docente")]
    assert SemanticIndex(tmp_path, model_factory=lambda _: CountingModel()).prepare(pieces)
    index = SemanticIndex(tmp_path, model_factory=lambda _: CountingModel(),
                          preparation_budget_seconds=0)
    assert index.prepare(pieces)
    assert index.warning is None and index.diagnostics["complete"]
    assert index.diagnostics["pending"] == 0
    assert index.rank("docente", pieces)[0]["chunk_id"] == "a"


@pytest.mark.parametrize("budget", [-1, float("nan"), float("inf")])
def test_invalid_budget_rejected(tmp_path, budget):
    with pytest.raises(ValueError):
        SemanticIndex(tmp_path, preparation_budget_seconds=budget)
