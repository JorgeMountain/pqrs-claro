# ruff: noqa: F811
"""FIAGA: pausa real, trazabilidad, concurrencia y límites probatorios."""

import copy
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_draft_service_api import FakeDraftEngine
from test_source_service_api import (
    FakeSourceAssessor,
    TwoRequestsIdentifier,
    make_case,
    pdf_bytes,  # noqa: F401
    upload_source,
)

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.intake_engine import materialize
from pqrs_claro.intake_models import DOCUMENT_CHECKS, REQUEST_CHECKS
from pqrs_claro.storage import Conflict


class FakeIntake:
    def __init__(self):
        self.calls = 0
        self.payload = None
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def assess(self, payload):
        self.calls += 1
        self.payload = payload
        if self.block:
            self.entered.set()
            assert self.release.wait(10)

        def checks(keys):
            return [
                {
                    "key": key,
                    "state": "no_observation",
                    "summary": "Resultado simulado.",
                    "reason": "Doble de pruebas sin IA.",
                    "original_refs": [{"page": 1, "line_start": 1, "line_end": 1}],
                    "chunk_ids": [],
                    "pending": [],
                }
                for key in keys
            ]

        return {
            "document": {
                "checks": checks(DOCUMENT_CHECKS),
                "proposed_route": "continue",
                "draft": None,
                "draft_missing": [],
            },
            "requests": [
                {
                    "request_id": r["id"],
                    "summary": r["description"],
                    "petition_type": "information",
                    "topic": "Ejemplo ficticio de prácticas",
                    "checks": checks(REQUEST_CHECKS),
                    "proposed_route": "continue",
                    "draft": None,
                    "draft_missing": [],
                }
                for r in payload["identification"]["requests"]
            ],
            "special_treatment": {
                "detected": False,
                "sender": None,
                "subject": None,
                "requested_information": None,
                "stated_term": None,
                "reason": "Sin tratamiento especial en el doble.",
                "original_refs": [],
            },
            "warnings": ["Prueba explícitamente simulada."],
        }


@pytest.fixture
def fiaga(tmp_path):
    engine, assessor = FakeIntake(), FakeSourceAssessor()
    settings = Settings(
        data_dir=tmp_path / "data",
        api_key="test-not-real",
        model="fake",
        initial_review_enabled=True,
    )
    app = create_app(
        settings,
        identifier=TwoRequestsIdentifier(),
        source_assessor=assessor,
        draft_engine=FakeDraftEngine(),
        intake_engine=engine,
    )
    with TestClient(app) as client:
        yield app, client, engine, assessor


def wait_intake(app, client, case):
    deadline = time.monotonic() + 10
    while (
        case["id"] in app.state.service.active or case["id"] in app.state.initial_review.active
    ) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert case["id"] not in app.state.initial_review.active
    return client.get(f"/api/cases/{case['id']}/initial-review").json()


def analyze(fiaga, pdf, source=False):
    app, client, _, _ = fiaga
    case = make_case(client, pdf)
    row = wait_intake(app, client, case)
    if source:
        upload_source(client)
        prefix = f"/api/cases/{case['id']}/initial-review"
        response = client.post(
            prefix + "/analyze", json={"version": case["version"], "revision": row["revision"]}
        )
        assert response.status_code == 202, response.text
        row = wait_intake(app, client, case)
    assert row["status"] == "needs_review", row
    return case, row


def decision(row, route="continue"):
    return {
        "revision": row["revision"],
        "reviewed_by": "Revisora ficticia",
        "document": {
            "route": "continue",
            "note": "Comprobación global ficticia de datos y lenguaje.",
            "reviewed": True,
        },
        "requests": [
            {
                "request_id": r["request_id"],
                "route": route,
                "petition_type": "documents",
                "note": "Comprobación humana ficticia para probar el flujo.",
                "reviewed": True,
            }
            for r in row["report"]["requests"]
        ],
    }


def test_confirm_stops_before_any_sources_or_drafts(fiaga, pdf_bytes):
    app, client, engine, assessor = fiaga
    case = make_case(client, pdf_bytes, confirm=False)
    prefix = f"/api/cases/{case['id']}"
    first = client.post(prefix + "/confirm-and-prepare", json={"version": case["version"]})
    assert first.status_code == 202, first.text
    assert first.json()["preparation"]["status"] == "waiting_initial_review"
    repeat = client.post(prefix + "/confirm-and-prepare", json={"version": case["version"]})
    assert repeat.json() == first.json()
    version = first.json()["case"]["version"]
    assert client.post(prefix + "/preparation", json={"version": version}).status_code == 409
    with pytest.raises(Conflict, match="revisión inicial"):
        app.state.drafts.start(case["id"], version)
    with pytest.raises(Conflict, match="revisión inicial"):
        app.state.reviews.approved(case["id"])
    wait_intake(app, client, case)
    assert engine.calls == 1 and not assessor.calls and not app.state.preparation.active


def test_automatic_analysis_then_single_human_confirmation(fiaga, pdf_bytes):
    app, client, engine, assessor = fiaga
    case = make_case(client, pdf_bytes, confirm=False)
    prefix = f"/api/cases/{case['id']}"
    row = wait_intake(app, client, case)
    assert row["status"] == "needs_review" and not row["can_prepare"]
    assert engine.calls == 1 and not assessor.calls
    before = client.get(prefix).json()
    assert before["status"] == "needs_review" and before["confirmed_at"] is None
    assert (
        client.post(prefix + "/preparation", json={"version": before["version"]}).status_code == 409
    )
    invalid = decision(row)
    invalid["document"]["reviewed"] = False
    assert client.put(prefix + "/initial-review/decision", json=invalid).status_code == 422
    assert client.get(prefix).json()["confirmed_at"] is None
    response = client.put(prefix + "/initial-review/decision", json=decision(row))
    assert response.status_code == 200, response.text
    assert response.json()["can_prepare"] and not response.json()["stale"]
    after = client.get(prefix).json()
    assert after["status"] == "confirmed" and after["version"] > before["version"]
    assert engine.calls == 1  # Confirmation does not repeat paid analysis.


def test_edit_reanalyzes_and_cannot_race_running_analysis(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    engine.block = True
    case = make_case(client, pdf_bytes, confirm=False)
    prefix = f"/api/cases/{case['id']}"
    correction = copy.deepcopy(case["identification"])
    correction["requests"][0]["title"] = "Título corregido"
    try:
        assert engine.entered.wait(5)
        assert (
            client.put(
                prefix + "/identification",
                json={
                    "version": case["version"],
                    "identification": correction,
                },
            ).status_code
            == 409
        )
    finally:
        engine.release.set()
    first = wait_intake(app, client, case)
    assert (
        client.put(
            prefix + "/identification",
            json={
                "version": case["version"],
                "identification": correction,
            },
        ).status_code
        == 200
    )
    second = wait_intake(app, client, case)
    assert second["status"] == "needs_review" and not second["stale"]
    assert second["revision"] > first["revision"] and engine.calls == 2
    assert engine.payload["identification"]["requests"][0]["title"] == "Título corregido"
    assert client.put(prefix + "/initial-review/decision", json=decision(first)).status_code == 409
    assert not second["can_prepare"]


def test_automatic_configuration_failure_keeps_identification_retryable(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    service = app.state.initial_review
    service.engine = None
    service.settings = replace(service.settings, api_key="")
    case = make_case(client, pdf_bytes, confirm=False)
    row = wait_intake(app, client, case)
    assert row["status"] == "error" and not row["can_prepare"]
    assert "Configura" in row["error"]
    assert row["analysis_scope"] == "petition_types_v1" and not row["stale"]
    prefix = f"/api/cases/{case['id']}"
    assert client.get(prefix).json()["status"] == "needs_review"
    service.engine = engine
    result = client.post(prefix + "/initial-review/analyze", json={
        "version": case["version"], "revision": row["revision"],
    })
    assert result.status_code == 202
    assert wait_intake(app, client, case)["status"] == "needs_review"


def test_classification_decisions_survive_source_changes(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    prefix = f"/api/cases/{case['id']}/initial-review"
    result = client.put(prefix + "/decision", json=decision(row))
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["can_prepare"] and saved["minimum_reference_days"] == 10
    assert client.get(prefix).json()["decisions"] == saved["decisions"]
    assert len(client.get(prefix + "/history").json()["events"]) == 3
    assert not app.state.preparation.active  # Saving never sends or starts drafting.
    upload_source(client)
    current = client.get(prefix).json()
    assert not current["stale"] and current["can_prepare"]
    assert current["decisions"] == saved["decisions"]
    assert current["revision"] == saved["revision"]


@pytest.mark.parametrize(
    "mutation",
    [
        "unchecked",
        "blank_note",
        "blank_actor",
        "duplicate",
        "missing",
        "old_revision",
        "unknown_type",
        "document_unchecked",
        "document_blank_note",
        "excluded_transfer",
        "excluded_unit",
        "unsupported_reiteration",
    ],
)
def test_invalid_decision_cannot_unlock(fiaga, pdf_bytes, mutation):
    _, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    body = decision(row)
    if mutation == "unchecked":
        body["requests"][0]["reviewed"] = False
    if mutation == "blank_note":
        body["requests"][0]["note"] = " "
    if mutation == "blank_actor":
        body["reviewed_by"] = " "
    if mutation == "duplicate":
        body["requests"][1] = body["requests"][0]
    if mutation == "missing":
        body["requests"].pop()
    if mutation == "old_revision":
        body["revision"] -= 1
    if mutation == "unknown_type":
        body["requests"][0]["petition_type"] = "undetermined"
    if mutation == "document_unchecked":
        body["document"]["reviewed"] = False
    if mutation == "document_blank_note":
        body["document"]["note"] = " "
    if mutation == "excluded_transfer":
        body["document"]["route"] = "transfer"
    if mutation == "excluded_unit":
        body["requests"][0]["assigned_unit"] = "Dependencia fuera del alcance"
    if mutation == "unsupported_reiteration":
        body["requests"][0]["route"] = "reiterate"
    prefix = f"/api/cases/{case['id']}/initial-review"
    assert client.put(prefix + "/decision", json=body).status_code in {409, 422}
    assert not client.get(prefix).json()["can_prepare"]


def test_mixed_routes_remain_pending_and_can_be_corrected(fiaga, pdf_bytes):
    _, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    body = decision(row)
    body["requests"][1]["route"] = "specialist"
    prefix = f"/api/cases/{case['id']}/initial-review"
    routed = client.put(prefix + "/decision", json=body).json()
    assert routed["status"] == "routed" and not routed["can_prepare"]
    assert client.put(prefix + "/decision", json=decision(row)).status_code == 409
    assert client.put(prefix + "/decision", json=decision(routed)).json()["can_prepare"]


def test_global_checks_and_unavailable_history_without_assignment(fiaga, pdf_bytes):
    _, _, _, _ = fiaga
    _, row = analyze(fiaga, pdf_bytes)
    report = row["report"]
    assert [c["key"] for c in report["document"]["checks"]] == DOCUMENT_CHECKS
    assert report["document"]["checks"][0]["original_refs"][0]["quote"]
    assert not report["history_available"]
    for item in report["requests"]:
        assert "suggested_unit" not in item
        checks = {c["key"]: c for c in item["checks"]}
        assert set(checks) == set(REQUEST_CHECKS)
        assert checks["repetition"]["state"] == "unavailable"
        assert not checks["repetition"]["pending"]


def test_fabricated_source_or_original_reference_is_rejected(fiaga, pdf_bytes):
    _, _, engine, _ = fiaga
    analyze(fiaga, pdf_bytes)
    payload = engine.payload
    result = engine.assess(payload)
    result["requests"][0]["checks"][0]["chunk_ids"] = ["invented"]
    with pytest.raises(ValueError, match="referencia"):
        materialize(result, payload)
    result = engine.assess(payload)
    result["requests"][0]["checks"][0]["original_refs"][0]["page"] = 99
    with pytest.raises(ValueError, match="página"):
        materialize(result, payload)


def test_model_change_during_classification_rejects_stale_result(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    engine.block = True
    case = make_case(client, pdf_bytes)
    try:
        assert engine.entered.wait(5)
        service = app.state.initial_review
        service.settings = replace(service.settings, model="changed-during-classification")
    finally:
        engine.release.set()
    row = wait_intake(app, client, case)
    assert row["status"] == "error" and not row["can_prepare"]


def test_recovery_and_new_analysis_remove_decisions(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    prefix = f"/api/cases/{case['id']}/initial-review"
    approved = client.put(prefix + "/decision", json=decision(row)).json()
    service = app.state.initial_review
    service.save(copy.deepcopy(approved), status="running", decisions=None)
    service.recover()
    result = client.get(prefix).json()
    assert result["status"] == "interrupted" and not result["can_prepare"]
    response = client.post(
        prefix + "/analyze", json={"version": case["version"], "revision": result["revision"]}
    )
    assert response.status_code == 202
    row = wait_intake(app, client, case)
    assert row["status"] == "needs_review" and row["decisions"] is None


def test_approved_review_allows_preparation(fiaga, pdf_bytes):
    app, client, _, assessor = fiaga
    case, row = analyze(fiaga, pdf_bytes, source=True)
    prefix = f"/api/cases/{case['id']}"
    assert client.put(prefix + "/initial-review/decision", json=decision(row)).json()["can_prepare"]
    response = client.post(prefix + "/preparation", json={"version": case["version"]})
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 10
    while case["id"] in app.state.preparation.active and time.monotonic() < deadline:
        time.sleep(0.05)
    assert assessor.calls
    assert client.get(prefix + "/preparation").json()["status"] in {"ready", "waiting_review"}


def test_new_initial_decision_invalidates_response_fingerprint(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    prefix = f"/api/cases/{case['id']}/initial-review"
    saved = client.put(prefix + "/decision", json=decision(row)).json()
    before = app.state.drafts._fingerprint(case, {})
    body = decision(saved)
    body["requests"][0]["petition_type"] = "consultation"
    updated = client.put(prefix + "/decision", json=body)
    assert updated.status_code == 200 and updated.json()["can_prepare"]
    assert app.state.drafts._fingerprint(case, {}) != before


def test_no_library_history_enters_identification_even_when_linked(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case = make_case(client, pdf_bytes)
    library = app.state.library
    for collection_id in ["permitted-history", "private-other-history"]:
        library.save_collection({"id": collection_id, "name": collection_id})
        library.add(
            collection_id + ".txt",
            (
                "Respuesta anterior sobre requisitos de prácticas y acta del comité. "
                + collection_id
            ).encode(),
            title=collection_id,
            category="historical_response",
            origin="Fixture de prueba",
            collection_id=collection_id,
        )
    library.link_collections(case["id"], ["permitted-history"])
    payload = app.state.initial_review.payload(case["id"])
    serialized = str(payload)
    assert "permitted-history" not in serialized
    assert "private-other-history" not in serialized
    assert payload["candidates"] == []
    assert payload["scope"]["library_search"] == "not_requested"


def test_one_document_decision_applies_to_all_requests(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    prefix = f"/api/cases/{case['id']}/initial-review"
    body = decision(row)
    body["document"]["route"] = "complement"
    routed = client.put(prefix + "/decision", json=body).json()
    assert routed["status"] == "routed" and not routed["can_prepare"]
    assert routed["document_decision"]["route"] == "complement"
    assert all(r["route"] == "continue" for r in routed["decisions"])
    with pytest.raises(Conflict):
        app.state.preparation.start(case["id"], case["version"])
    saved = client.put(prefix + "/decision", json=decision(routed)).json()
    assert saved["can_prepare"]
    assert not saved["report"]["history_available"]  # No history is not a blocking requirement.


def test_old_analysis_is_preserved_but_requires_new_scope(fiaga, pdf_bytes):
    app, client, _, _ = fiaga
    case, row = analyze(fiaga, pdf_bytes)
    service = app.state.initial_review
    legacy_report = {k: v for k, v in row["report"].items() if k != "document"}
    old = service.save(row, policy_version=1, status="approved", report=legacy_report)
    prefix = f"/api/cases/{case['id']}/initial-review"
    current = client.get(prefix).json()
    assert current["legacy_report"] and current["stale"] and not current["can_prepare"]
    assert client.put(prefix + "/decision", json=decision(row)).status_code == 409
    assert client.get(prefix + "/history").json()["events"][-1]["report"] == legacy_report
    response = client.post(
        prefix + "/analyze", json={"version": case["version"], "revision": old["revision"]}
    )
    assert response.status_code == 202
    updated = wait_intake(app, client, case)
    assert updated["policy_version"] == 2 and not updated["legacy_report"]
    assert updated["document_decision"] is None and updated["decisions"] is None
    assert client.get(prefix + "/history").json()["events"][-3]["report"] == legacy_report


@pytest.mark.parametrize("mutation", ["global_duplicate", "global_in_request", "competence"])
def test_misplaced_or_excluded_checks_are_rejected(fiaga, pdf_bytes, mutation):
    _, _, engine, _ = fiaga
    analyze(fiaga, pdf_bytes)
    payload = engine.payload
    report = engine.assess(payload)
    if mutation == "global_duplicate":
        report["document"]["checks"][1]["key"] = "requirements"
    if mutation == "global_in_request":
        report["requests"][0]["checks"][0]["key"] = "respect"
    if mutation == "competence":
        report["requests"][0]["checks"][0]["key"] = "competence"
    with pytest.raises(ValueError):
        materialize(report, payload)


def test_global_language_alert_needs_literal_evidence(fiaga, pdf_bytes):
    _, _, engine, _ = fiaga
    analyze(fiaga, pdf_bytes)
    report = engine.assess(engine.payload)
    check = report["document"]["checks"][1]
    check.update(state="attention", original_refs=[])
    with pytest.raises(ValueError, match="expresión original"):
        materialize(report, engine.payload)


def test_reiteration_cannot_be_suggested_without_history(fiaga, pdf_bytes):
    _, _, engine, _ = fiaga
    analyze(fiaga, pdf_bytes)
    report = engine.assess(engine.payload)
    report["requests"][0].update(proposed_route="reiterate", draft="Borrador no sustentado")
    result = materialize(report, engine.payload)
    assert not result["history_available"]
    assert result["requests"][0]["proposed_route"] == "continue"
    assert result["requests"][0]["draft"] is None


def test_available_history_still_requires_a_cited_comparison(fiaga, pdf_bytes):
    app, client, engine, _ = fiaga
    case = make_case(client, pdf_bytes)
    app.state.library.save_collection({"id": "history", "name": "Histórico ficticio"})
    app.state.library.link_collections(case["id"], ["history"])
    app.state.library.add(
        "antecedente.txt",
        b"Respuesta anterior sobre requisitos de practicas.",
        title="Respuesta ficticia",
        category="historical_response",
        origin="Prueba",
        collection_id="history",
    )
    payload = app.state.initial_review.payload(case["id"])
    # Historic reports still require a specific comparison. This manually
    # supplies their old contract; new identification does not search history.
    _, chunks = app.state.library.snapshot(case["id"])
    payload["candidates"] = chunks
    payload["scope"] = {"history_available": True}
    report = engine.assess(payload)
    result = materialize(report, payload)
    assert result["requests"][0]["checks"][0]["state"] == "unverified"
    candidate = next(c for c in payload["candidates"] if c["category"] == "historical_response")
    report["requests"][0]["checks"][0]["chunk_ids"] = [candidate["chunk_id"]]
    result = materialize(report, payload)
    assert result["requests"][0]["checks"][0]["state"] == "no_observation"
