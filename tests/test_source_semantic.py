from pathlib import Path

import numpy as np
import pytest

from pqrs_claro.source_semantic import (
    DEFAULT_CACHE_DIR,
    MODEL_FILE,
    MODEL_REVISION,
    SemanticIndex,
)


class CountingModel:
    def __init__(self):
        self.calls = []

    def embed(self, texts, batch_size=32):
        self.calls.extend(texts)
        for text in texts:
            yield np.array([1.0, float("docente" in text), float("nómina" in text)])


def chunk(identity, text, collection="onman"):
    return {
        "chunk_id": identity,
        "source_id": identity,
        "title": "Antecedente",
        "quote": text,
        "collection_id": collection,
    }


def test_vectors_persist_and_only_changed_content_is_recomputed(tmp_path):
    first_model = CountingModel()
    original = chunk("a", "El docente")
    first = SemanticIndex(tmp_path, model_factory=lambda _: first_model)
    assert first.prepare([original])
    assert len(first_model.calls) == 1
    first.rank("docente", [original])
    first.rank("docente", [original])
    assert len(first_model.calls) == 2  # Un documento y una consulta, una sola vez.

    second_model = CountingModel()
    second = SemanticIndex(tmp_path, model_factory=lambda _: second_model)
    assert second.prepare([original])
    assert second_model.calls == []
    assert second.diagnostics["cached"] == 1
    assert second.prepare([{**original, "review_status": "reviewed"}])
    assert second_model.calls == []  # Revisión humana no altera el contenido del vector.
    assert second.prepare([{**original, "quote": "El docente actualizó su informe"}])
    assert len(second_model.calls) == 1


def test_model_revision_has_a_separate_cache_namespace(tmp_path):
    model = CountingModel()
    pieces = [chunk("a", "El docente")]
    assert SemanticIndex(tmp_path, model_factory=lambda _: model, model_key="v1").prepare(pieces)
    assert SemanticIndex(tmp_path, model_factory=lambda _: model, model_key="v2").prepare(pieces)
    assert len(model.calls) == 2


def test_cached_other_case_is_never_returned_or_used_to_expand_scope(tmp_path):
    model = CountingModel()
    hidden = chunk("private", "El docente", collection="otro-expediente")
    allowed = chunk("allowed", "La nómina", collection="onman")
    index = SemanticIndex(tmp_path, model_factory=lambda _: model)
    assert index.prepare([hidden, allowed])
    results = index.rank("docente", [allowed])
    assert [item["chunk_id"] for item in results] == ["allowed"]
    assert results[0]["quote"] == allowed["quote"]
    assert "semantic_score" in results[0]


def test_unavailable_model_exposes_warning_and_does_not_retry_per_question(tmp_path):
    attempts = []

    def unavailable(_):
        attempts.append(True)
        raise FileNotFoundError("modelo ausente")

    index = SemanticIndex(tmp_path, model_factory=unavailable)
    pieces = [chunk("a", "El docente")]
    assert index.rank("uno", pieces) == []
    assert index.rank("dos", pieces) == []
    assert index.warning and "búsqueda por texto" in index.warning
    assert len(attempts) == 1


def test_partial_index_can_resume_without_reencoding_committed_batches(tmp_path):
    class InterruptedModel(CountingModel):
        def embed(self, texts, batch_size=32):
            if self.calls:
                raise RuntimeError("interrupción")
            yield from super().embed(texts, batch_size=batch_size)

    pieces = [chunk("a", "El docente"), chunk("b", "La nómina")]
    interrupted = SemanticIndex(tmp_path, model_factory=lambda _: InterruptedModel(), batch_size=1)
    assert not interrupted.prepare(pieces)
    resumed_model = CountingModel()
    resumed = SemanticIndex(tmp_path, model_factory=lambda _: resumed_model, batch_size=1)
    assert resumed.prepare(pieces)
    assert resumed.diagnostics["cached"] == 1
    assert resumed.diagnostics["encoded"] == 1
    assert len(resumed_model.calls) == 1


def test_nan_embedding_disables_channel_instead_of_returning_arbitrary_candidates(tmp_path):
    class BrokenModel:
        def embed(self, texts, batch_size=32):
            return [np.array([np.nan, 1.0]) for _ in texts]

    index = SemanticIndex(tmp_path, model_factory=lambda _: BrokenModel())
    assert index.rank("docente", [chunk("a", "El docente")]) == []
    assert index.warning


@pytest.mark.skipif(
    not (DEFAULT_CACHE_DIR / "models" / MODEL_REVISION / MODEL_FILE).is_file(),
    reason="Modelo local no instalado; esta prueba nunca descarga archivos",
)
def test_real_multilingual_model_recovers_a_spanish_paraphrase(tmp_path, monkeypatch):
    """Control real de significado: palabras discriminantes distintas en pregunta/respuesta."""
    import socket

    from pqrs_claro.source_retrieval import tokenize
    from pqrs_claro.source_semantic import _load_model

    def network_forbidden(*args, **kwargs):
        raise AssertionError("La inferencia local no debe abrir conexiones de red")

    monkeypatch.setattr(socket.socket, "connect", network_forbidden)

    query = "¿Quién dictó el curso?"
    expected = chunk("teacher", "El responsable de la asignatura fue el profesor Carlos Ruiz.")
    assert not set(tokenize(query)).intersection(tokenize(expected["quote"]))
    index = SemanticIndex(tmp_path, model_factory=lambda _: _load_model(Path(DEFAULT_CACHE_DIR)))
    result = index.rank(
        query,
        [
            chunk("finance", "La devolución del dinero fue aprobada por el banco."),
            chunk("food", "El restaurante entregó los almuerzos del contrato."),
            expected,
        ],
        limit=1,
    )
    assert index.warning is None
    assert result[0]["chunk_id"] == "teacher"
