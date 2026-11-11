import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_source_semantic import CountingModel, chunk

from pqrs_claro import source_semantic as semantic
from pqrs_claro.source_service import SourceService


@pytest.fixture
def installed(tmp_path):
    directory = tmp_path / "models" / semantic.MODEL_REVISION
    (directory / "onnx").mkdir(parents=True)
    for part in (semantic.MODEL_FILE, "tokenizer.json", "tokenizer_config.json",
                 "special_tokens_map.json", "config.json"):
        (directory / part).write_bytes(b"old")
    return directory


@pytest.fixture
def loads(monkeypatch):
    instances = []

    def create(path, *, threads):
        instances.append(CountingModel())
        return instances[-1]

    monkeypatch.setattr(semantic, "_load_model", create)
    return instances


@pytest.mark.parametrize("part", [semantic.MODEL_FILE, "tokenizer.json", "config.json",
                                  "tokenizer_config.json", "special_tokens_map.json"])
def test_replacement_with_same_timestamp_is_detected(tmp_path, installed, loads, part):
    engine = semantic.ResidentSemanticModel()
    first = engine(tmp_path)
    assert first is engine(tmp_path)
    path = installed / part
    old = path.stat()
    path.write_bytes(b"new")
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert engine(tmp_path) is not first
    assert len(loads) == 2


def test_clearing_and_missing_artifacts_never_reuse_an_old_instance(tmp_path, installed, loads):
    engine = semantic.ResidentSemanticModel()
    first = engine(tmp_path)
    sidecar = installed / "tokenizer.json"
    sidecar.unlink()
    with pytest.raises(FileNotFoundError):
        engine(tmp_path)
    sidecar.write_bytes(b"old")
    second = engine(tmp_path)
    assert first is not second
    engine.clear()
    assert engine(tmp_path) is not second
    assert len(loads) == 3


def test_concurrent_first_use_and_separate_scoped_indexes(tmp_path, installed, loads):
    service = SourceService(None, None, None)
    first = semantic.SemanticIndex(tmp_path, model_factory=service.semantic_model)
    second = semantic.SemanticIndex(tmp_path, model_factory=service.semantic_model)
    try:
        with ThreadPoolExecutor(4) as workers:
            models = list(workers.map(service.semantic_model, [tmp_path] * 8))
        assert all(obj is models[0] for obj in models)
        rows_a, rows_b = [chunk("A", "docente", "A")], [chunk("B", "nómina", "B")]
        assert [r["chunk_id"] for r in first.rank("docente", rows_a)] == ["A"]
        assert [r["chunk_id"] for r in second.rank("docente", rows_b)] == ["B"]
        assert not (first._queries is second._queries or first._matrices is second._matrices)
        assert len(loads) == 1
    finally:
        service.close()
    assert service.semantic_model(tmp_path) is not models[0]


def test_concurrent_change_during_load_retries_on_next_index(tmp_path, installed, monkeypatch):
    def changing_loader(path, *, threads):
        (installed / "config.json").write_bytes(b"new")
        return CountingModel()

    engine = semantic.ResidentSemanticModel()
    monkeypatch.setattr(semantic, "_load_model", changing_loader)
    first = semantic.SemanticIndex(tmp_path, model_factory=engine)
    piece = [chunk("a", "docente")]
    assert not first.prepare(piece)
    assert "cambiaron durante la carga" in first.warning
    second = semantic.SemanticIndex(tmp_path, model_factory=engine)
    assert second.prepare(piece) and not second.warning


def test_corrupt_onnx_uses_original_loader_and_lexical_fallback(tmp_path, installed, monkeypatch):
    from pqrs_claro.source_retrieval import retrieve

    original = semantic._load_model
    engine = semantic.ResidentSemanticModel()
    monkeypatch.setattr(semantic, "_load_model", lambda *a, **kw: CountingModel())
    engine(tmp_path)
    (installed / semantic.MODEL_FILE).write_bytes(b"not the official version")
    monkeypatch.setattr(semantic, "_load_model", original)
    fresh_index = semantic.SemanticIndex(tmp_path, model_factory=engine)
    pieces = [{**chunk("a", "constancia de docente", None), "category": "case_evidence",
               "document_id": "doc-a", "case_id": "A", "page": 1, "line_start": 1, "line_end": 1}]
    request = dict(id="P1", case_id="A", title="constancia de docente", description="docente")
    matches = retrieve(request, pieces, semantic=fresh_index)
    assert [s["chunk_id"] for s in matches] == ["a"]
    assert "huella del modelo" in fresh_index.warning


def test_failed_inference_keeps_lexical_evidence_then_reloads_and_reuses_e5(
    tmp_path, installed, loads, monkeypatch,
):
    from pqrs_claro.source_retrieval import retrieve

    engine = semantic.ResidentSemanticModel()
    broken = engine(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("Sesión defectuosa simulada")

    monkeypatch.setattr(broken, "embed", fail)
    for case_id, expected_loads in (("A", 1), ("B", 2), ("C", 2)):
        text = f"El expediente {case_id} incluye la constancia docente."
        piece = {
            **chunk(case_id, text, None), "case_id": case_id, "category": "case_evidence",
            "document_id": case_id, "page": 1, "line_start": 1, "line_end": 1,
        }
        request = dict(id="P1", case_id=case_id, title="Constancia docente", description="docente")
        index = semantic.SemanticIndex(tmp_path, model_factory=engine)
        results = retrieve(request, [piece], semantic=index)
        assert [(r["chunk_id"], r["case_id"], r["quote"]) for r in results] == [
            (case_id, case_id, text)
        ]
        if case_id == "A":
            assert "Sesión defectuosa simulada" in index.warning
            assert index.diagnostics["queries"] == 0
        else:
            assert not index.warning
            assert index.diagnostics["queries"] == 1
        assert len(loads) == expected_loads


def test_late_failure_of_old_engine_cannot_discard_healthy_replacement(tmp_path, installed, loads):
    engine = semantic.ResidentSemanticModel()
    first = engine(tmp_path)
    engine.discard(first)
    replacement = engine(tmp_path)
    engine.discard(first)
    assert engine(tmp_path) is replacement
    assert replacement is not first
    assert len(loads) == 2
