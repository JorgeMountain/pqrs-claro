"""Configuración del lector y búsqueda HTTP real con Responses API simulada."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_draft_service_api import FakeDraftEngine
from test_preparation import wait as wait_preparation
from test_source_analysis import chunk, request
from test_source_passages import located
from test_source_service_api import start_search, upload_source, wait_search

from pqrs_claro import config, source_assessment
from pqrs_claro.unified_app import create_unified_app


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    local_env = tmp_path / ".env.local"
    read_env = config.dotenv_values

    def read_isolated_env(path):
        return read_env(local_env if path == config.ROOT / ".env.local" else path)

    monkeypatch.setattr(config, "dotenv_values", read_isolated_env)
    monkeypatch.setenv("PQRS_CLARO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PQRS_CLARO_KEY_FILE", str(tmp_path / "unused"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-real")
    monkeypatch.delenv("PQRS_CLARO_SOURCE_SERVICE_TIER", raising=False)
    return local_env


def test_source_tier_environment_overrides_local_config(local_config, monkeypatch):
    assert config.Settings().source_service_tier == "fast"
    local_config.write_text("PQRS_CLARO_SOURCE_SERVICE_TIER=default\n")
    assert config.Settings.load().source_service_tier == "default"
    monkeypatch.setenv("PQRS_CLARO_SOURCE_SERVICE_TIER", "fast")
    assert config.Settings.load().source_service_tier == "fast"
    monkeypatch.setenv("PQRS_CLARO_SOURCE_SERVICE_TIER", "unknown")
    with pytest.raises(ValueError, match="PQRS_CLARO_SOURCE_SERVICE_TIER"):
        config.Settings.load()


@pytest.mark.parametrize("entrypoint", ["sources/search", "preparation"])
def test_normal_source_search_uses_fast_then_honors_standard_after_restart(
    local_config, monkeypatch, entrypoint
):
    original = chunk()
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        repair = "citation_repair" in json.loads(kwargs["input"])
        # La primera respuesta cita una línea inexistente. La segunda corrige el rango.
        answer = located(original, 1, 1 if repair else 99)
        return SimpleNamespace(status="completed", output_parsed=answer)

    sdk = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    monkeypatch.setattr(source_assessment, "OpenAI", lambda **_: sdk)

    def search_new_case(app, client):
        record = app.state.store.create("solicitud ficticia.pdf", b"%PDF-ficticio")
        case_id = record["id"]
        inquiry = request(case_id=case_id, label="1", source_refs=[])
        case = app.state.store.update(
            case_id, status="confirmed", request_count=1,
            identification={"subject": inquiry["title"], "requests": [inquiry]},
        )
        upload = upload_source(
            client, case_id=case_id, category="case_evidence",
            title=original["title"], content=original["quote"],
        )
        assert upload.status_code == 201
        started = client.post(
            f"/api/cases/{case_id}/{entrypoint}", json={"version": case["version"]}
        )
        assert started.status_code == 202, started.text
        if entrypoint == "preparation":
            preparation = wait_preparation(app, client, case_id)
            assert preparation["status"] == "waiting_review", preparation
            row, = client.get(f"/api/cases/{case_id}/review").json()["requests"]
            assert {"document_delivery", "provenance"} <= {
                pending["reason_code"] for pending in row["pending"]
            }
        run = wait_search(app, client, case_id)
        assert run["status"] == "ready", run
        finding, = run["results"]
        assert finding["analysis_diagnostic"]["code"] == "validated_after_repair"
        citation, = finding["sufficiency"]["coverage"][0]["citations"]
        assert citation["quote"] == original["quote"].splitlines(keepends=True)[0]
        return case, run

    app = create_unified_app(draft_engine=FakeDraftEngine())
    with TestClient(app) as client:
        previous_case, previous_run = search_new_case(app, client)
    assert [call["service_tier"] for call in calls] == ["fast", "fast"]

    local_config.write_text("PQRS_CLARO_SOURCE_SERVICE_TIER=default\n")
    app = create_unified_app(draft_engine=FakeDraftEngine())
    with TestClient(app) as client:
        start_search(client, previous_case)
        cached = wait_search(app, client, previous_case["id"])
        assert (cached["id"], cached["status"]) == (previous_run["id"], "ready")
        assert len(calls) == 2
        search_new_case(app, client)
    assert len(calls) == 4
    assert all("service_tier" not in call for call in calls[2:])
