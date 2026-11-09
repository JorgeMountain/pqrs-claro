import pytest

from pqrs_claro import config
from pqrs_claro.source_semantic import DEFAULT_MATRIX_CACHE_BYTES


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB", raising=False)
    monkeypatch.delenv("PQRS_CLARO_KEY_FILE", raising=False)
    return tmp_path


def test_matrix_cache_default_local_override_and_zero_environment(isolated, monkeypatch):
    assert config.Settings.load().semantic_matrix_cache_mb * 1024**2 == DEFAULT_MATRIX_CACHE_BYTES
    (isolated / ".env.local").write_text("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB=128\n")
    assert config.Settings.load().semantic_matrix_cache_mb == 128
    monkeypatch.setenv("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB", "0")
    assert config.Settings.load().semantic_matrix_cache_mb == 0


@pytest.mark.parametrize("value", ["-1", "1025", "1.5", "many"])
def test_matrix_cache_rejects_invalid_limits(isolated, monkeypatch, value):
    monkeypatch.setenv("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB", value)
    with pytest.raises(ValueError):
        config.Settings.load()
