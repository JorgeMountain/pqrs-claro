import pytest

from pqrs_claro import config


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("PQRS_CLARO_DRAFT_CONCURRENCY", raising=False)
    monkeypatch.delenv("PQRS_CLARO_KEY_FILE", raising=False)
    return tmp_path


def test_default_and_local_concurrency_with_environment_override(isolated, monkeypatch):
    assert config.Settings.load().draft_concurrency == 3
    (isolated / ".env.local").write_text("PQRS_CLARO_DRAFT_CONCURRENCY=5\n")
    assert config.Settings.load().draft_concurrency == 5
    monkeypatch.setenv("PQRS_CLARO_DRAFT_CONCURRENCY", "2")
    assert config.Settings.load().draft_concurrency == 2


@pytest.mark.parametrize("value", ["0", "7", "-1", "many"])
def test_reject_invalid_concurrency(isolated, monkeypatch, value):
    monkeypatch.setenv("PQRS_CLARO_DRAFT_CONCURRENCY", value)
    with pytest.raises(ValueError):
        config.Settings.load()
