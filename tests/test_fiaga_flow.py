"""Recorrido FIAGA completo: HTTP, SQLite y archivos; IA y conversión son dobles."""

import pymupdf
import pytest
from fastapi.testclient import TestClient
from test_draft_service_api import FakeDraftEngine
from test_initial_review import FakeIntake, decision, wait_intake
from test_office_service_api import FakeOfficeRenderer, generate, inputs, wait_office
from test_preparation import wait
from test_review_service_api import FakeReviewEngine, approve, assess, current, save
from test_source_service_api import (
    FakeSourceAssessor,
    TwoRequestsIdentifier,
    make_case,
    upload_source,
)

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings


class InformationIdentifier(TwoRequestsIdentifier):
    def identify(self, pages):
        result = super().identify(pages)
        result.requests[1].title = "Registro de decisiones del comité"
        result.requests[
            1
        ].description = "Informar cómo registra sus decisiones el comité de prácticas."
        return result


@pytest.fixture
def information_pdf():
    with pymupdf.open() as document:
        document.new_page().insert_text(
            (50, 80),
            "PRUEBA FICTICIA. Informar requisitos de practicas "
            "y como registra decisiones el comite.",
        )
        return document.tobytes()


@pytest.fixture
def full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pqrs_claro.office_service.pdf_capabilities",
        lambda: {
            "pdf_available": True,
            "pdf_engine": "test-double",
            "error": None,
        },
    )
    renderer = FakeOfficeRenderer()
    app = create_app(
        Settings(
            data_dir=tmp_path / "data",
            api_key="test-not-real",
            model="fake",
            initial_review_enabled=True,
        ),
        identifier=InformationIdentifier(),
        source_assessor=FakeSourceAssessor(),
        draft_engine=FakeDraftEngine(),
        intake_engine=FakeIntake(),
        review_engine=FakeReviewEngine(),
        office_renderer=renderer,
        interface="recorrido",
    )
    with TestClient(app) as client:
        yield app, client, renderer


def prepare_fiaga(full_flow, pdf):
    app, client, _ = full_flow
    case = make_case(client, pdf, confirm=False)
    automatic = wait_intake(app, client, case)
    assert automatic["status"] == "needs_review"
    assert client.get(f"/api/cases/{case['id']}").json()["confirmed_at"] is None
    assert upload_source(client).status_code == 201
    prefix = f"/api/cases/{case['id']}"
    assert (
        client.post(prefix + "/preparation", json={"version": case["version"]}).status_code == 409
    )
    assert not client.get(prefix + "/office").json()["eligible"]
    assert (
        client.post(
            prefix + "/initial-review/analyze",
            json={"version": case["version"], "revision": automatic["revision"]},
        ).status_code
        == 202
    )
    report = wait_intake(app, client, case)
    body = decision(report)
    for item in body["requests"]:
        item["petition_type"] = "information"
    approved = client.put(prefix + "/initial-review/decision", json=body)
    assert approved.status_code == 200, approved.text
    assert approved.json()["can_prepare"]
    case = client.get(prefix).json()
    assert case["status"] == "confirmed" and case["confirmed_at"]
    assert not app.state.preparation.active
    assert (
        client.post(prefix + "/preparation", json={"version": case["version"]}).status_code == 202
    )
    job = wait(app, client, case["id"])
    assert job["status"] == "ready", job
    assert job["initial_review_revision"] == approved.json()["revision"]
    rows = client.get(prefix + "/review").json()["requests"]
    assert len(rows) == 2 and all(r["paragraphs"] and not r["approval"] for r in rows)
    assert not client.get(prefix + "/office").json()["eligible"]
    work = client.get(prefix + "/office/workspace")
    assert work.status_code == 200 and len(work.json()["requests"]) == 2
    return case, approved.json()


def generate_fiaga(full_flow, pdf):
    app, client, renderer = full_flow
    case, intake = prepare_fiaga(full_flow, pdf)
    for request_id in ("P1", "P2"):
        reviewed = assess(app, client, case, current(client, case, request_id))
        assert reviewed["status"] == "ready", reviewed
        approved = approve(client, case, reviewed)
        assert approved.status_code == 200, approved.text
    run = wait_office(app, client, case, generate(client, case, inputs(client, case)))
    assert run["status"] == "ready", run
    prefix = f"/api/cases/{case['id']}/office/runs/{run['id']}"
    for kind, signature in (("docx", b"PK"), ("pdf", b"%PDF"), ("zip", b"PK")):
        result = client.get(prefix + "/files/" + kind)
        assert result.status_code == 200 and result.content.startswith(signature)
    assert renderer.calls == 1
    return case, intake, run


@pytest.mark.parametrize("change", ["document_route", "classification", "source", "response"])
def test_complete_fiaga_export_and_invalidation(full_flow, information_pdf, change):
    app, client, renderer = full_flow
    case, intake, run = generate_fiaga(full_flow, information_pdf)
    prefix = f"/api/cases/{case['id']}"
    before = client.get(prefix + "/initial-review/history").json()["events"]
    if change == "source":
        assert (
            upload_source(client, content="Nueva versión ficticia sobre las prácticas.").status_code
            == 201
        )
        assert client.get(prefix + "/initial-review").json()["stale"]
    elif change == "response":
        row = current(client, case)
        paragraphs = [{**p, "text": p["text"] + " Ajuste de prueba."} for p in row["paragraphs"]]
        assert save(client, case, row, paragraphs=paragraphs).status_code == 200
    else:
        body = decision(intake)
        for item in body["requests"]:
            item["petition_type"] = "information"
        if change == "document_route":
            body["document"]["route"] = "complement"
        else:
            body["requests"][0]["petition_type"] = "consultation"
        result = client.put(prefix + "/initial-review/decision", json=body)
        assert result.status_code == 200, result.text
        assert result.json()["can_prepare"] == (change == "classification")
    assert not client.get(prefix + "/office").json()["eligible"]
    for kind in ("docx", "pdf", "zip"):
        response = client.get(prefix + f"/office/runs/{run['id']}/files/{kind}")
        assert response.status_code == 409, response.text
    after = client.get(prefix + "/initial-review/history").json()["events"]
    assert after[: len(before)] == before
    assert renderer.calls == 1  # Leer o invalidar nunca genera un nuevo oficio.
