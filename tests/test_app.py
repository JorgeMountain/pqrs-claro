"""Recorridos HTTP reales con identificación doble y persistencia SQLite temporal."""

from __future__ import annotations

import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import Identification, Request, SourceRef, source_quote


class FakeIdentifier:
    """Doble explícito: permite probar la aplicación sin simular conectividad OpenAI."""

    def __init__(self, *, fail_if_called=False):
        self.calls = 0
        self.fail_if_called = fail_if_called

    def identify(self, pages):
        self.calls += 1
        if self.fail_if_called:
            raise AssertionError("Reanudar la revisión no debe volver a llamar la IA")
        return Identification(
            subject="Copia del acta",
            requests=[
                Request(
                    id="P1",
                    label="1",
                    title="Entregar copia del acta",
                    description="Entregar copia del acta institucional mencionada.",
                    source_refs=[
                        SourceRef(
                            page=1,
                            line_start=2,
                            line_end=2,
                            quote=source_quote(pages, 1, 2, 2),
                        )
                    ],
                )
            ],
        )


@pytest.fixture
def pdf_bytes():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (50, 80),
            "Peticion de ejemplo\nSolicito copia del acta institucional indicada en la respuesta.",
        )
        return document.tobytes()


@pytest.fixture
def app_client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", api_key="test-not-real", model="test-model")
    identifier = FakeIdentifier()
    app = create_app(settings, extractor=PDFExtractor(), identifier=identifier)
    with TestClient(app) as client:
        yield app, client, identifier, settings


def upload(client, pdf):
    response = client.post("/api/cases", files={"file": ("peticion.pdf", pdf, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()


def wait_ready(client, case_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        case = client.get(f"/api/cases/{case_id}").json()
        if case["status"] not in {"reading", "identifying", "confirming"}:
            assert case["status"] == "needs_review", case
            return case
        time.sleep(0.02)
    pytest.fail("El grafo local no alcanzó la pausa de revisión en diez segundos")


def analyze(client, case):
    response = client.post(f"/api/cases/{case['id']}/analyze")
    assert response.status_code == 202, response.text
    return wait_ready(client, case["id"])


def test_upload_invalid_pdf_does_not_create_case(app_client):
    _, client, _, _ = app_client
    for data in (b"", b"This is not a PDF", b"%PDF-corrupted"):
        response = client.post(
            "/api/cases", files={"file": ("archivo.pdf", data, "application/pdf")}
        )
        assert response.status_code == 422
    assert client.get("/api/cases").json() == []


def test_upload_analyze_edit_version_conflict_and_confirm(app_client, pdf_bytes):
    app, client, identifier, _ = app_client
    uploaded = upload(client, pdf_bytes)
    assert uploaded["received_at"] is None
    assert uploaded["created_at"]
    reviewed = analyze(client, uploaded)
    assert identifier.calls == 1
    assert reviewed["request_count"] == 1
    assert reviewed["pages"][0]["method"] == "native"
    identification = reviewed["identification"]
    identification["requests"][0]["title"] = "Copia íntegra del acta"
    body = {"version": reviewed["version"], "identification": identification}
    path = f"/api/cases/{uploaded['id']}"
    saved_response = client.put(path + "/identification", json=body)
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()
    assert saved["status"] == "needs_review"
    assert client.put(path + "/identification", json=body).status_code == 409
    assert client.post(path + "/confirm", json={"version": reviewed["version"]}).status_code == 409
    confirmed_response = client.post(path + "/confirm", json={"version": saved["version"]})
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_at"]
    assert confirmed["identification"]["requests"][0]["title"] == "Copia íntegra del acta"
    assert client.post(path + "/analyze").status_code == 409
    assert client.post(path + "/confirm", json={"version": confirmed["version"]}).status_code == 409
    assert identifier.calls == 1
    with app.state.store.connect() as connection:
        count = connection.execute("SELECT count(*) FROM revisions").fetchone()[0]
    assert count >= 2


def test_save_rejects_quote_that_does_not_match_the_original(app_client, pdf_bytes):
    _, client, _, _ = app_client
    case = analyze(client, upload(client, pdf_bytes))
    identification = case["identification"]
    identification["requests"][0]["source_refs"][0]["quote"] = "Cita que el PDF no contiene"
    response = client.put(
        f"/api/cases/{case['id']}/identification",
        json={"version": case["version"], "identification": identification},
    )
    assert response.status_code == 422
    assert "no coincide" in response.json()["detail"]
    current = client.get(f"/api/cases/{case['id']}").json()
    assert current["version"] == case["version"]


def test_restart_recovers_human_edit_without_calling_identifier(tmp_path, pdf_bytes):
    settings = Settings(data_dir=tmp_path / "data", api_key="test-not-real", model="test-model")
    first_identifier = FakeIdentifier()
    first_app = create_app(settings, extractor=PDFExtractor(), identifier=first_identifier)
    with TestClient(first_app) as client:
        case = analyze(client, upload(client, pdf_bytes))
        identification = case["identification"]
        identification["requests"][0]["title"] = "Corrección humana conservada"
        response = client.put(
            f"/api/cases/{case['id']}/identification",
            json={"version": case["version"], "identification": identification},
        )
        assert response.status_code == 200
        # Representa un cierre después de solicitar confirmar y antes de reanudar el grafo.
        first_app.state.store.update(case["id"], status="confirming")
    second_identifier = FakeIdentifier(fail_if_called=True)
    second_app = create_app(settings, extractor=PDFExtractor(), identifier=second_identifier)
    with TestClient(second_app) as client:
        current = client.get(f"/api/cases/{case['id']}").json()
        assert current["status"] == "error"
        recovered = analyze(client, current)
        assert recovered["identification"]["requests"][0]["title"] == "Corrección humana conservada"
        response = client.post(
            f"/api/cases/{case['id']}/confirm", json={"version": recovered["version"]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "confirmed"
    assert first_identifier.calls == 1
    assert second_identifier.calls == 0


@pytest.mark.parametrize(
    "headers", [{"origin": "https://sitio-ajeno.example"}, {"sec-fetch-site": "cross-site"}]
)
def test_cross_site_mutations_are_rejected(app_client, pdf_bytes, headers):
    _, client, _, _ = app_client
    response = client.post(
        "/api/cases", files={"file": ("peticion.pdf", pdf_bytes)}, headers=headers
    )
    assert response.status_code == 403
    assert client.get("/api/cases").json() == []


def test_original_and_page_preview_match_uploaded_pdf(app_client, pdf_bytes):
    _, client, _, _ = app_client
    case = upload(client, pdf_bytes)
    path = f"/api/cases/{case['id']}"
    original = client.get(path + "/original")
    assert original.status_code == 200
    assert original.content == pdf_bytes
    assert original.headers["content-type"] == "application/pdf"
    image = client.get(path + "/pages/1.png")
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG")
    assert image.headers["content-type"] == "image/png"
    assert client.get(path + "/pages/0.png").status_code == 404
    assert client.get(path + "/pages/2.png").status_code == 404
    assert client.get("/api/cases/missing/original").status_code == 404
