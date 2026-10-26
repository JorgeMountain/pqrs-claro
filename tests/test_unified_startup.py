from pathlib import Path

import pytest

from pqrs_claro import unified_app
from pqrs_claro.config import Settings


@pytest.mark.parametrize("provider", ["openai", "jev"])
def test_main_enables_review_and_preserves_configured_provider(monkeypatch, provider):
    import uvicorn

    settings = Settings(data_dir=Path('original-data'), initial_classification_provider=provider)
    captured = {}
    monkeypatch.setattr(Settings, 'load', lambda: settings)
    monkeypatch.setattr('sys.argv', ['pqrs', '--port', '8772'])
    monkeypatch.setattr(
        unified_app, 'create_unified_app', lambda s: captured.setdefault('settings', s)
    )
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: captured.update(kwargs))
    unified_app.main()
    assert captured['settings'].data_dir == settings.data_dir
    assert captured['settings'].initial_review_enabled
    assert captured['settings'].management_enabled
    assert captured['settings'].initial_classification_provider == provider
    assert captured['host'] == '127.0.0.1'
    assert captured['port'] == 8772
