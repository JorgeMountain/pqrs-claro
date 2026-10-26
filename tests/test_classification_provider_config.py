"""Provider selection changes only classification, with explicit local configuration."""

import pytest

from pqrs_claro import config


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    for key in ("PQRS_CLARO_CLASSIFICATION_PROVIDER", "PQRS_CLARO_KEY_FILE",
                "PQRS_CLARO_MODEL", "PQRS_CLARO_DRAFT_CONCURRENCY"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_local_provider_and_environment_override_preserve_luna(isolated, monkeypatch):
    (isolated / ".env.local").write_text(
        "PQRS_CLARO_CLASSIFICATION_PROVIDER=jev\nPQRS_CLARO_MODEL=gpt-6-luna\n",
        encoding="utf-8",
    )
    settings = config.Settings.load()
    assert settings.initial_classification_provider == "jev"
    assert settings.model == "gpt-6-luna"
    monkeypatch.setenv("PQRS_CLARO_CLASSIFICATION_PROVIDER", "openai")
    assert config.Settings.load().initial_classification_provider == "openai"
    assert config.Settings.load().model == "gpt-6-luna"


def test_unconfigured_installation_does_not_silently_change_provider(isolated):
    assert config.Settings.load().initial_classification_provider == "openai"


def test_invalid_provider_rejected_instead_of_falling_back(isolated, monkeypatch):
    monkeypatch.setenv("PQRS_CLARO_CLASSIFICATION_PROVIDER", "automatic")
    with pytest.raises(ValueError, match="openai o jev"):
        config.Settings.load()
