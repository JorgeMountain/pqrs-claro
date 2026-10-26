"""Reutilización real SQLite/LangGraph/API con contador, sin red ni expediente vivo."""

import time
from collections import Counter
from copy import deepcopy

import pytest
import test_source_verifications as verification_helpers
from test_draft_service_api import FakeDraftEngine, generate
from test_review_service_api import FakeReviewEngine, approve, assess, url, wait_drafts
from test_source_verifications import human_payload

from pqrs_claro.evidence_contract import apply_evidence_contract
from pqrs_claro.source_context import build_source_requests
from pqrs_claro.verification_policy import application_matches_check

environment = verification_helpers.environment


class CountingAssessor:
    def __init__(self):
        self.calls = Counter()

    def assess(self, request, candidates):
        self.calls[request["id"]] += 1
        assert candidates, "La prueba requiere un soporte realmente recuperado."
        support = {**candidates[0], "role": "rule", "reason": "Soporte ficticio de prueba."}
        return {
            "request_id": request["id"], "status": "references_found",
            "supports": [support], "warnings": [], "summary": "Doble explícito sin IA.",
            "missing": [{
                "kind": "clarification", "reason_code": "provenance",
                "description": f"Comprobar la procedencia de «{support['title']}».",
                # Una IA que intente cerrar o asignar la clave no puede hacerlo.
                "check_key": "check-" + "f" * 24, "resolution": {"status": "resolved"},
            }],
        }


class NoSemantic:
    warning = None
    diagnostics = {"status": "test-double"}

    def __init__(self, _path, **kwargs):
        pass

    def prepare(self, _chunks, **kwargs):
        return True

    def rank(self, _query, _eligible, **kwargs):
        return []


@pytest.fixture
def reuse_environment(environment, monkeypatch):
    app = environment[0]
    assessor = CountingAssessor()
    app.state.sources.assessor = assessor
    monkeypatch.setattr("pqrs_claro.source_service.SemanticIndex", NoSemantic)
    return *environment, assessor


def search(env):
    app, client, case, *_ = env
    response = client.post(f"/api/cases/{case['id']}/sources/search",
                           json={"version": case["version"]})
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if case["id"] not in app.state.sources.active:
            result = client.get(f"/api/cases/{case['id']}/sources").json()
            assert result["status"] == "ready", result
            return result
        time.sleep(0.01)
    pytest.fail("El grafo local de fuentes no terminó.")


def register_and_apply(env, run, request_ids):
    app, client, case, source, passage, _ = env
    record = client.post(f"/api/cases/{case['id']}/verifications",
                         json=human_payload(case, source, passage))
    assert record.status_code == 201, record.text
    assert app.state.sources.get(case["id"])["stale"] is False
    check = run["results"][0]["checks"][0]
    response = client.post(
        f"/api/cases/{case['id']}/verifications/{record.json()['id']}/applications",
        json={"version": case["version"], "request_ids": request_ids,
              "check_key": check["check_key"], "basis": "Revisé la procedencia de esta versión.",
              "recorded_by": "Responsable ficticia de la revisión"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_apply_and_revoke_reuse_checkpoint_without_new_assessor_calls(reuse_environment):
    app, client, case, _, _, assessor = reuse_environment
    original = search(reuse_environment)
    assert dict(assessor.calls) == {"P1": 1, "P2": 1, "P3": 1}
    assert all(result["missing"] for result in original["results"])
    assert all(result["checks"][0]["check_key"] != "check-" + "f" * 24
               for result in original["results"])
    application = register_and_apply(reuse_environment, original, ["P2"])
    assert app.state.sources.get(case["id"])["stale"]
    applied = search(reuse_environment)
    assert applied["analysis_fingerprint"] == original["analysis_fingerprint"]
    assert applied["fingerprint"] != original["fingerprint"]
    assert dict(assessor.calls) == {"P1": 1, "P2": 1, "P3": 1}
    findings = {result["request_id"]: result for result in applied["results"]}
    assert findings["P2"]["missing"] == []
    assert findings["P1"]["missing"] and findings["P3"]["missing"]
    response = client.post(
        f"/api/cases/{case['id']}/verification-applications/{application['id']}/revoke",
        json={"version": case["version"], "reason": "El periodo requiere revisar su aplicación.",
              "recorded_by": "Responsable ficticia"},
    )
    assert response.status_code == 201
    reopened = search(reuse_environment)
    assert all(result["missing"] for result in reopened["results"])
    assert dict(assessor.calls) == {"P1": 1, "P2": 1, "P3": 1}


def test_revoking_applied_evidence_invalidates_existing_approval(reuse_environment):
    app, client, case, _, _, assessor = reuse_environment
    original = search(reuse_environment)
    application = register_and_apply(reuse_environment, original, ["P1", "P2", "P3"])
    search(reuse_environment)
    app.state.drafts.engine = FakeDraftEngine()
    app.state.reviews.engine = FakeReviewEngine()
    assert generate(client, case).status_code == 202
    assert wait_drafts(app, client, case)["status"] == "ready"
    response = client.post(url(case, "/start"), json={"version": case["version"]})
    assert response.status_code == 200, response.text
    for row in response.json()["requests"]:
        checked = assess(app, client, case, row)
        assert checked["status"] == "ready", checked
        approved = approve(client, case, checked)
        assert approved.status_code == 200, approved.text
    assert client.get(url(case, "/approved")).status_code == 200
    response = client.post(
        f"/api/cases/{case['id']}/verification-applications/{application['id']}/revoke",
        json={"version": case["version"], "reason": "Encontré una diferencia en el soporte.",
              "recorded_by": "Responsable ficticia"},
    )
    assert response.status_code == 201
    reviews = client.get(url(case)).json()
    assert reviews["status"] == "stale"
    assert all(row["approval"] is None and row["assessment"] is None
               for row in reviews["requests"])
    assert client.get(url(case, "/approved")).status_code == 409
    assert dict(assessor.calls) == {"P1": 1, "P2": 1, "P3": 1}


@pytest.mark.parametrize("mutation", [
    lambda item: item.pop("record"),
    lambda item: item.update(scope_key="another-scope"),
    lambda item: item.update(check_reason="fact_confirmation"),
    lambda item: item["record"].update(source_id="another-source"),
    lambda item: item["record"].update(source_sha256="another-hash"),
    lambda item: item["record"].update(extraction_revision=200),
    lambda item: item["record"].update(kind="antecedent_declared",
                                         recording_method="model_extraction"),
])
def test_application_key_alone_never_closes_a_check(reuse_environment, mutation):
    app, _, case, *_ = reuse_environment
    original = search(reuse_environment)
    register_and_apply(reuse_environment, original, ["P2"])
    application = app.state.verifications.active_applications(case)[0]
    finding = next(result for result in original["results"] if result["request_id"] == "P2")
    request = next(item for item in build_source_requests(case) if item["id"] == "P2")
    assert application_matches_check(application, finding["checks"][0], "P2")
    changed = deepcopy(application)
    mutation(changed)
    assert not application_matches_check(changed, finding["checks"][0], "P2")
    result = apply_evidence_contract(request, finding, applications=[changed])
    assert result["missing"]
    assert result["checks"][0]["resolution"]["status"] == "open"


def test_transcription_review_must_cover_the_actual_page_and_lines(environment):
    app, _, case, source, passage = environment
    record = app.state.verifications.record_human(
        case["id"], **human_payload(case, source, passage)
    )
    version = {"source_id": source["id"], "document_id": source["document_id"],
               "version": source["version"], "sha256": source["sha256"],
               "extraction_revision": None}
    check = {"check_key": "check-" + "1" * 24, "scope_key": "page-scope", "stage": "evidence",
             "state": "confirmation_pending", "reason_code": "transcription",
             "linked_source_ids": [source["id"]], "source_versions": [version],
             "linked_chunk_ids": [passage["chunk_id"]]}
    application = {"case_id": case["id"], "record": record, "verification_id": record["id"],
                   "check_key": check["check_key"], "request_ids": ["P2"],
                   "scope_key": check["scope_key"], "check_reason": "transcription"}
    assert application_matches_check(application, check, "P2")
    check["linked_chunk_ids"] = [f"{source['id']}:2:1:2"]
    assert not application_matches_check(application, check, "P2")
