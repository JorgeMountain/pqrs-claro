# ruff: noqa: F811
"""Selective retries through the preparation API, against isolated SQLite stores."""

from copy import deepcopy

from test_draft_service_api import FakeDraftEngine
from test_preparation import wait
from test_source_service_api import make_case, pdf_bytes, source_app, upload_source  # noqa: F401

from pqrs_claro.source_passages import SourceAnalysisError, diagnostic


def failed_preparation(app, client, assessor, pdf):
    app.state.drafts.engine = FakeDraftEngine()
    assessor.fail_once = "P2"
    case = make_case(client, pdf)
    upload_source(client)
    prefix = f"/api/cases/{case['id']}"
    response = client.post(prefix + "/preparation", json={"version": case["version"]})
    assert response.status_code == 202, response.text
    job = wait(app, client, case["id"])
    assert job["analysis_error_ids"] == ["P2"]
    return case, prefix


def test_retry_failed_only_keeps_completed_result_and_review_and_old_diagnostic(
    source_app, pdf_bytes
):
    app, client, assessor, _ = source_app
    original_assess = assessor.assess

    def assess(request, candidates):
        try:
            return original_assess(request, candidates)
        except ValueError:
            raise SourceAnalysisError("Ubicación inválida de una cita.", diagnostic(
                "citation_validation_failed", attempts=2,
                errors=[dict(reason="invalid_passage_range", chunk_id="C1",
                             line_start=4, line_end=2)])) from None

    assessor.assess = assess
    case, prefix = failed_preparation(app, client, assessor, pdf_bytes)
    failed = client.get(prefix + "/sources").json()
    previous = deepcopy(failed)
    row = client.get(prefix + "/review").json()["requests"][0]
    assert failed["results"][1]["analysis_diagnostic"]["attempts"] == 2
    result = client.post(prefix + "/preparation", json={
        "version": case["version"], "retry_failed_only": True})
    assert result.status_code == 202, result.text
    wait(app, client, case["id"])
    recovered = client.get(prefix + "/sources").json()
    assert recovered["status"] == "ready"
    assert recovered["retry_request_ids"] == ["P2"]
    assert recovered["retry_of_run_id"] == previous["id"]
    assert recovered["results"][0] == previous["results"][0]
    assert assessor.calls == {"P1": 1, "P2": 2}
    current = client.get(prefix + "/review").json()["requests"][0]
    # The review refreshes the aggregate source fingerprint; it must retain content
    # and recorded decisions, without silently approving the refreshed response.
    for key in ("paragraphs", "facts", "pending", "edited_by", "available_supports"):
        assert current.get(key) == row.get(key)
    assert current["approval"] is None
    with app.state.sources.library.connect() as conn:
        raw = conn.execute("SELECT body FROM source_runs WHERE id=?",
                           (previous["id"],)).fetchone()[0]
    import json
    assert json.loads(raw)["results"][1] == previous["results"][1]
    # A second click after completion never starts another analysis.
    assert client.post(prefix + "/preparation", json={
        "version": case["version"], "retry_failed_only": True}).status_code == 409
    assert assessor.calls == {"P1": 1, "P2": 2}


def test_changed_sources_reject_selective_retry_without_modifying_job(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case, prefix = failed_preparation(app, client, assessor, pdf_bytes)
    job = client.get(prefix + "/preparation").json()
    added = upload_source(client, content="Otro documento con requisitos distintos para prácticas.")
    assert added.status_code == 201
    response = client.post(prefix + "/preparation", json={
        "version": case["version"], "retry_failed_only": True})
    assert response.status_code == 409, response.text
    assert "cambiaron" in response.json()["detail"]
    assert client.get(prefix + "/preparation").json() == job
    assert assessor.calls == {"P1": 1, "P2": 1}


def test_retry_modes_cannot_be_combined(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case, prefix = failed_preparation(app, client, assessor, pdf_bytes)
    response = client.post(prefix + "/preparation", json={
        "version": case["version"], "retry_failed_only": True, "retry_analysis": True})
    assert response.status_code == 409
    assert assessor.calls == {"P1": 1, "P2": 1}
