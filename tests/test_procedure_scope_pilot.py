"""Procedure contrast is opt-in; citation-bound detail coverage applies in both modes."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_review_service_api as service_tests
from test_review_engine import engine, inquiry, review
from test_review_procedure_scope import CLEAR, response, worker
from test_review_service_api import approve, assess, current, prepare

from pqrs_claro import config, draft_engine, review_engine, review_service
from pqrs_claro.answer_coverage import DETAIL_CHECK_GUIDANCE, DETAIL_PLAN_GUIDANCE
from pqrs_claro.procedure_scope import PROCEDURE_SCOPE_CHECK_INSTRUCTIONS

review_app = service_tests.review_app


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("PQRS_CLARO_KEY_FILE", str(tmp_path / "unused"))
    monkeypatch.delenv("PQRS_PROCEDURE_SCOPE_PILOT", raising=False)
    return tmp_path / ".env.local"


def test_pilot_is_disabled_in_constructor_and_loaded_settings(isolated_config):
    assert config.Settings().procedure_scope_pilot is False
    assert config.Settings.load().procedure_scope_pilot is False


def test_pilot_setting_is_explicit_and_environment_overrides_local(isolated_config, monkeypatch):
    isolated_config.write_text("PQRS_PROCEDURE_SCOPE_PILOT=true\n", encoding="utf8")
    assert config.Settings.load().procedure_scope_pilot is True
    monkeypatch.setenv("PQRS_PROCEDURE_SCOPE_PILOT", "false")
    assert config.Settings.load().procedure_scope_pilot is False
    monkeypatch.setenv("PQRS_PROCEDURE_SCOPE_PILOT", "1")
    assert config.Settings.load().procedure_scope_pilot is True
    monkeypatch.setenv("PQRS_PROCEDURE_SCOPE_PILOT", "perhaps")
    with pytest.raises(ValueError, match="PQRS_PROCEDURE_SCOPE_PILOT"):
        config.Settings.load()


def test_default_review_keeps_single_call_without_pilot_payload_or_schema():
    reviewer, calls = engine()

    def rejected_pilot(*_):
        pytest.fail("The disabled pilot must never call its blind reader")

    reviewer._procedure_scope = rejected_pilot
    result = reviewer.assess(inquiry(), review())
    assert reviewer.procedure_scope_pilot is False
    assert result["status"] == "passed" and len(calls) == 1
    assert "procedure_scope_readings" not in json.loads(calls[0]["input"])
    assert "procedure_scope_checks" not in calls[0]["text_format"].model_fields
    assert not any(c["code"] == "procedure_scope_review" for c in result["local_checks"])


def test_explicit_pilot_keeps_two_calls_and_source_backed_reading_checks():
    reviewer, calls = worker()
    result = reviewer.assess(inquiry(), response(text=CLEAR, controls=False))
    assert reviewer.procedure_scope_pilot is True
    assert result["status"] == "passed" and len(calls) == 2
    assert "request_scope" in calls[0][1]
    assert calls[1][1]["procedure_scope_readings"]
    assert "procedure_scope_checks" in calls[1][0].model_fields


def test_both_modes_require_details_but_only_opt_in_requires_procedure_readings():
    # The general detail contract intentionally supersedes the frozen v2/v6 hashes.
    # Compare the complete shared schema, not only existence of a convenient field.
    for baseline, pilot in (
        (review_engine._Assessment, review_engine._ProcedureAssessment),
        (draft_engine._Checks, draft_engine._PILOT_CHECK_SCHEMA),
    ):
        ordinary = baseline.model_json_schema()
        extended = pilot.model_json_schema()
        assert set(extended["properties"]) == set(ordinary["properties"]) | {
            "procedure_scope_checks",
        }
        assert "detail_checks" in ordinary["properties"]
        for key, value in ordinary["properties"].items():
            assert extended["properties"][key] == value
        for key, value in ordinary["$defs"].items():
            assert extended["$defs"][key] == value
        assert ordinary["additionalProperties"] is False
        assert extended["additionalProperties"] is False
    for instructions in (
        review_engine._INSTRUCTIONS, review_engine._PILOT_INSTRUCTIONS,
        draft_engine._CHECK_INSTRUCTIONS, draft_engine._PILOT_CHECK_INSTRUCTIONS,
    ):
        assert DETAIL_CHECK_GUIDANCE in instructions
    assert DETAIL_PLAN_GUIDANCE in draft_engine._PLAN_INSTRUCTIONS
    plan_schema = draft_engine._PlanSelection.model_json_schema()
    details = plan_schema["$defs"]["DetailedPlanUnitProposal"]
    assert {"details", "no_details_reason"} <= set(details["required"])
    assert PROCEDURE_SCOPE_CHECK_INSTRUCTIONS not in review_engine._INSTRUCTIONS
    assert PROCEDURE_SCOPE_CHECK_INSTRUCTIONS in review_engine._PILOT_INSTRUCTIONS
    assert PROCEDURE_SCOPE_CHECK_INSTRUCTIONS not in draft_engine._CHECK_INSTRUCTIONS
    assert PROCEDURE_SCOPE_CHECK_INSTRUCTIONS in draft_engine._PILOT_CHECK_INSTRUCTIONS


@pytest.mark.parametrize("enabled", [False, True])
def test_review_factory_forwards_explicit_setting(enabled, monkeypatch):
    calls = []

    def constructor(api_key, model, *, procedure_scope_pilot=False):
        calls.append((api_key, model, procedure_scope_pilot))
        return SimpleNamespace(procedure_scope_pilot=procedure_scope_pilot)

    monkeypatch.setattr(review_engine, "OpenAIReviewEngine", constructor)
    service = object.__new__(review_service.ReviewService)
    service.settings = config.Settings(procedure_scope_pilot=enabled)
    service.engine = None
    assert service._engine().procedure_scope_pilot is enabled
    assert calls == [(service.settings.api_key, service.settings.model, enabled)]


@pytest.mark.parametrize("initial_mode", [False, True])
def test_mode_switch_invalidates_approval_both_directions_without_losing_work(
    review_app, initial_mode,
):
    app, client, _, _ = review_app
    service = app.state.reviews
    service.settings = replace(service.settings, procedure_scope_pilot=initial_mode)
    case, _, row = prepare(app, client)
    checked = assess(app, client, case, row)
    accepted = approve(client, case, checked)
    assert accepted.status_code == 200
    before = accepted.json()
    service.settings = replace(service.settings, procedure_scope_pilot=not initial_mode)
    stale = current(client, case)
    assert stale["stale"] and stale["assessment"] is None and stale["approval"] is None
    assert stale["paragraphs"] == before["paragraphs"] and stale["pending"] == before["pending"]
    assert approve(client, case, before).status_code == 409


def test_disabled_pilot_policy_changes_do_not_invalidate_accepted_baseline(review_app, monkeypatch):
    app, client, _, _ = review_app
    case, _, row = prepare(app, client)
    checked = assess(app, client, case, row)
    accepted = approve(client, case, checked)
    assert accepted.status_code == 200
    monkeypatch.setattr(review_service, "PROCEDURE_SCOPE_POLICY_HASH", "c" * 64)
    unchanged = current(client, case)
    assert not unchanged["stale"]
    assert unchanged["assessment"] == accepted.json()["assessment"]
    assert unchanged["approval"] == accepted.json()["approval"]


@pytest.mark.parametrize("enabled", [False, True])
def test_detail_policy_changes_invalidate_both_modes(review_app, monkeypatch, enabled):
    app, client, _, _ = review_app
    service = app.state.reviews
    service.settings = replace(service.settings, procedure_scope_pilot=enabled)
    case, _, row = prepare(app, client)
    accepted = approve(client, case, assess(app, client, case, row))
    assert accepted.status_code == 200, accepted.text
    monkeypatch.setattr(review_service, "DETAIL_POLICY_HASH", "d" * 64)
    stale = current(client, case)
    assert stale["stale"] and stale["assessment"] is None and stale["approval"] is None
    assert stale["paragraphs"] == accepted.json()["paragraphs"]
    assert stale["pending"] == accepted.json()["pending"]
    assert approve(client, case, accepted.json()).status_code == 409
