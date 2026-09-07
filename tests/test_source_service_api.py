"""Fase 4 vía HTTP y SQLite con identificador/evaluador dobles explícitos, sin red."""

from __future__ import annotations

import threading
import time
from collections import Counter

import pymupdf
import pytest
from fastapi.testclient import TestClient

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError, Identification, Request, SourceRef, source_quote


class TwoRequestsIdentifier:
    """Doble: conserva una referencia real para dos solicitudes conocidas del PDF."""

    def identify(self, pages):
        return Identification(
            subject="Prácticas y acta del comité",
            requests=[
                Request(
                    id=f"P{index}",
                    label=str(index),
                    title=title,
                    description=description,
                    source_refs=[
                        SourceRef(
                            page=1,
                            line_start=1,
                            line_end=1,
                            quote=source_quote(pages, 1, 1, 1),
                        )
                    ],
                )
                for index, (title, description) in enumerate(
                    [
                        ("Requisitos de prácticas", "Informar los requisitos de prácticas."),
                        ("Acta del comité", "Solicito copia del acta del comité de prácticas."),
                    ],
                    1,
                )
            ],
        )


class FakeSourceAssessor:
    """Doble controlable para probar coordinación, interrupciones y carreras."""

    def __init__(self, *, fail_once=None, block_once=False):
        self.calls = Counter()
        self.fail_once = fail_once
        self.block_once = block_once
        self.entered = threading.Event()
        self.release = threading.Event()

    def assess(self, request, candidates):
        self.calls[request["id"]] += 1
        if self.block_once:
            self.block_once = False
            self.entered.set()
            if not self.release.wait(5):
                raise AssertionError("La prueba no liberó el evaluador simulado")
        if request["id"] == self.fail_once and self.calls[request["id"]] == 1:
            raise DomainError("Fallo transitorio simulado de evaluación")
        supports = [
            {
                **candidate,
                "reason": "Pertinencia simulada para probar la persistencia del servicio.",
                "role": "rule" if candidate["category"].endswith("norm") else "fact",
            }
            for candidate in candidates[:1]
        ]
        return dict(
            request_id=request["id"],
            status="references_found" if supports else "no_matches",
            summary="Evaluación ficticia del doble de pruebas, sin conexión a OpenAI.",
            supports=supports,
            missing=[],
            warnings=[],
        )


@pytest.fixture
def pdf_bytes():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (50, 80),
            "Solicito requisitos de practicas y copia del acta del comite institucional.",
        )
        return document.tobytes()


@pytest.fixture
def source_app(tmp_path):
    assessor = FakeSourceAssessor()
    settings = Settings(data_dir=tmp_path / "data", api_key="test-not-real", model="test-model")
    app = create_app(
        settings,
        extractor=PDFExtractor(),
        identifier=TwoRequestsIdentifier(),
        source_assessor=assessor,
    )
    with TestClient(app) as client:
        yield app, client, assessor, settings


def wait_case(client, case_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        case = client.get(f"/api/cases/{case_id}").json()
        if case["status"] == "needs_review":
            return case
        assert case["status"] != "error", case
        time.sleep(0.01)
    pytest.fail("El identificador doble no llegó a revisión")


def make_case(client, pdf, *, confirm=True):
    uploaded = client.post("/api/cases", files={"file": ("peticion.pdf", pdf, "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    case = uploaded.json()
    response = client.post(f"/api/cases/{case['id']}/analyze")
    assert response.status_code == 202, response.text
    case = wait_case(client, case["id"])
    if confirm:
        response = client.post(
            f"/api/cases/{case['id']}/confirm", json={"version": case["version"]}
        )
        assert response.status_code == 200, response.text
        case = response.json()
    return case


def upload_source(client, *, case_id=None, category="institutional_norm", **changes):
    data = {
        "title": "Requisitos y acta del comité de prácticas",
        "category": category,
        "origin": "Institución ficticia. Documento de pruebas locales.",
    }
    if case_id:
        data["case_id"] = case_id
    content = changes.pop(
        "content", "El comité define requisitos de prácticas y registra las decisiones en el acta."
    )
    data.update(changes)
    return client.post(
        "/api/sources",
        data=data,
        files={"file": ("fuente.txt", content.encode("utf-8"), "text/plain")},
    )


def wait_search(app, client, case_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get(f"/api/cases/{case_id}/sources").json()
        if result["status"] != "running" and case_id not in app.state.sources.active:
            return result
        time.sleep(0.01)
    pytest.fail("La búsqueda local con doble no terminó")


def start_search(client, case):
    response = client.post(
        f"/api/cases/{case['id']}/sources/search", json={"version": case["version"]}
    )
    assert response.status_code == 202, response.text
    return response.json()


def review_source(client, source_id, *, case_id=None, note="Contrastado con el original ficticio"):
    response = client.put(
        f"/api/sources/{source_id}/review",
        json={
            "case_id": case_id,
            "reviewed_by": "Persona ficticia de la prueba",
            "review_note": note,
            "validity": "current",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_search_requires_confirmation_current_version_and_available_sources(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case = make_case(client, pdf_bytes, confirm=False)
    path = f"/api/cases/{case['id']}/sources/search"
    response = client.post(path, json={"version": case["version"]})
    assert response.status_code == 409
    assert "Confirma" in response.json()["detail"]
    old_version = case["version"]
    case = client.post(f"/api/cases/{case['id']}/confirm", json={"version": old_version}).json()
    assert client.post(path, json={"version": old_version}).status_code == 409
    assert client.post(path, json={"version": case["version"]}).status_code == 422
    assert upload_source(client).status_code == 201
    start_search(client, case)
    first = wait_search(app, client, case["id"])
    assert first["status"] == "ready"
    assert first["completed_count"] == first["total_count"] == 2
    repeated = start_search(client, case)
    assert repeated["id"] == first["id"]
    assert assessor.calls == {"P1": 1, "P2": 1}
    assert client.get(f"/api/cases/{case['id']}").json()["version"] == case["version"]


def test_source_uploads_and_all_read_routes_respect_case_scope(source_app, pdf_bytes):
    _, client, _, _ = source_app
    first = make_case(client, pdf_bytes)
    second = make_case(client, pdf_bytes)
    assert upload_source(client, category="case_evidence").status_code == 422
    assert (
        upload_source(client, case_id="missing-case", category="case_evidence").status_code == 404
    )
    global_source = upload_source(client).json()
    local_response = upload_source(client, case_id=first["id"], category="case_evidence")
    assert local_response.status_code == 201, local_response.text
    local_source = local_response.json()
    global_ids = {source["id"] for source in client.get("/api/sources").json()["sources"]}
    second_ids = {
        source["id"]
        for source in client.get("/api/sources", params={"case_id": second["id"]}).json()["sources"]
    }
    assert global_ids == second_ids == {global_source["id"]}
    for suffix in ("", "/original", "/versions", "/pages/1.png"):
        path = f"/api/sources/{local_source['id']}{suffix}"
        assert client.get(path).status_code == 404
        assert client.get(path, params={"case_id": second["id"]}).status_code == 404
    visible = client.get(f"/api/sources/{local_source['id']}", params={"case_id": first["id"]})
    assert visible.status_code == 200
    original = client.get(
        f"/api/sources/{local_source['id']}/original", params={"case_id": first["id"]}
    )
    assert original.status_code == 200 and b"requisitos" in original.content
    invalid_version = upload_source(
        client,
        case_id=second["id"],
        category="case_evidence",
        document_id=local_source["document_id"],
        content="Otro contenido de un expediente distinto.",
    )
    assert invalid_version.status_code == 404
    assert (
        client.put(
            f"/api/sources/{local_source['id']}/review",
            json={
                "case_id": second["id"],
                "reviewed_by": "Prueba",
                "review_note": "Prueba de aislamiento",
                "validity": "not_applicable",
            },
        ).status_code
        == 404
    )


def test_review_makes_previous_analysis_stale_without_erasing_results(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case = make_case(client, pdf_bytes)
    source = upload_source(client).json()
    start_search(client, case)
    previous = wait_search(app, client, case["id"])
    assert previous["status"] == "ready"
    review_source(client, source["id"])
    stale = client.get(f"/api/cases/{case['id']}/sources").json()
    assert stale["status"] == "stale" and stale["stale"] is True
    assert stale["results"] == previous["results"]
    start_search(client, case)
    current = wait_search(app, client, case["id"])
    assert current["status"] == "ready" and current["stale"] is False
    assert current["id"] != previous["id"]
    assert assessor.calls == {"P1": 2, "P2": 2}
    assert all(
        support["review_status"] == "reviewed"
        for result in current["results"]
        for support in result["supports"]
    )


def test_new_source_version_preserves_original_and_replaces_search_inputs(source_app, pdf_bytes):
    app, client, _, _ = source_app
    case = make_case(client, pdf_bytes)
    first = upload_source(client).json()
    original = client.get(f"/api/sources/{first['id']}/original").content
    start_search(client, case)
    previous = wait_search(app, client, case["id"])
    response = upload_source(
        client,
        document_id=first["document_id"],
        content="Versión dos: requisitos de prácticas aprobados por el comité y su acta.",
    )
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["id"] != first["id"] and second["version"] == 2
    assert second["document_id"] == first["document_id"]
    versions = client.get(f"/api/sources/{second['id']}/versions").json()["versions"]
    assert len(versions) == 2
    assert {source["id"] for source in versions if source["is_latest"]} == {second["id"]}
    assert client.get(f"/api/sources/{first['id']}/original").content == original
    stale = client.get(f"/api/cases/{case['id']}/sources").json()
    assert stale["status"] == "stale" and stale["results"] == previous["results"]
    start_search(client, case)
    current = wait_search(app, client, case["id"])
    assert current["status"] == "ready"
    assert {
        support["source_id"] for result in current["results"] for support in result["supports"]
    } == {second["id"]}


def test_retry_preserves_successful_requests_and_recovers_only_failed_checkpoint(
    source_app, pdf_bytes
):
    app, client, assessor, _ = source_app
    assessor.fail_once = "P2"
    case = make_case(client, pdf_bytes)
    assert upload_source(client).status_code == 201
    start_search(client, case)
    failed = wait_search(app, client, case["id"])
    assert failed["status"] == "error"
    assert [result["status"] for result in failed["results"]] == ["references_found", "error"]
    assert failed["completed_count"] == 2
    start_search(client, case)
    recovered = wait_search(app, client, case["id"])
    assert recovered["status"] == "ready"
    assert recovered["results"][0] == failed["results"][0]
    assert assessor.calls == {"P1": 1, "P2": 2}


def test_library_change_while_running_marks_final_result_stale(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    assessor.block_once = True
    case = make_case(client, pdf_bytes)
    source = upload_source(client).json()
    try:
        start_search(client, case)
        assert assessor.entered.wait(5), "El doble no alcanzó la evaluación"
        conflict = client.post(
            f"/api/cases/{case['id']}/sources/search", json={"version": case["version"]}
        )
        assert conflict.status_code == 409
        review_source(client, source["id"], note="Revisión efectuada durante la búsqueda")
        running = client.get(f"/api/cases/{case['id']}/sources").json()
        assert running["status"] == "running" and running["stale"] is True
    finally:
        assessor.release.set()
    final = wait_search(app, client, case["id"])
    assert final["status"] == "stale" and final["stale"] is True
    assert len(final["results"]) == 2
    assert all(
        support["review_status"] == "pending"
        for result in final["results"]
        for support in result["supports"]
    )


def test_example_sources_are_idempotent_and_do_not_enter_other_cases(source_app, pdf_bytes):
    _, client, _, _ = source_app
    ordinary = make_case(client, pdf_bytes)
    forbidden = client.post(f"/api/cases/{ordinary['id']}/sources/example")
    assert forbidden.status_code == 422
    demo_response = client.post("/api/cases/demo")
    assert demo_response.status_code == 201, demo_response.text
    demo = wait_case(client, demo_response.json()["id"])
    path = f"/api/cases/{demo['id']}/sources/example"
    first = client.post(path)
    assert first.status_code == 201, first.text
    second = client.post(path)
    assert second.status_code == 201, second.text
    first_ids = {source["id"] for source in first.json()["sources"]}
    assert len(first_ids) == 2
    assert first_ids == {source["id"] for source in second.json()["sources"]}
    assert all(source["case_id"] == demo["id"] for source in first.json()["sources"])
    assert client.get("/api/sources").json()["sources"] == []
    assert client.get("/api/sources", params={"case_id": ordinary["id"]}).json()["sources"] == []
    for source_id in first_ids:
        assert (
            client.get(f"/api/sources/{source_id}", params={"case_id": ordinary["id"]}).status_code
            == 404
        )
