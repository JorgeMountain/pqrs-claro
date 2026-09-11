# ruff: noqa: F811
"""La biblioteca del recorrido usa los contratos reales sin modificar la demo."""

import httpx
from fastapi.testclient import TestClient
from test_source_service_api import make_case, pdf_bytes, source_app  # noqa: F401

from pqrs_claro.config import ROOT
from pqrs_claro.recorrido_app import create_recorrido


def upload(client, text=b"Antecedente ficticio para probar la biblioteca.", **extra):
    return client.post(
        "/api/evidence",
        data={
            "title": "Prueba biblioteca",
            "origin": "Prueba aislada",
            "category": "historical_response",
            "shared": "true",
            **extra,
        },
        files={"file": ("fuente.txt", text, "text/plain")},
    )


def test_recorrido_keeps_demo_and_supports_real_shared_versions(source_app):
    backend, _, assessor, _ = source_app
    with TestClient(create_recorrido(transport=httpx.ASGITransport(app=backend))) as client:
        assert "library.js" in client.get("/app.js").text
        assert client.get("/app.js").headers["cache-control"] == "no-cache"
        assert client.get("/").headers["cache-control"] == "no-cache"
        assert "workspace-rail" in client.get("/").text
        assert (
            client.get("/data.json").content
            == (ROOT / "output/ux-peticiones-20260910/data.json").read_bytes()
        )
        first = upload(client)
        assert first.status_code == 201, first.text
        first = first.json()
        assert first["case_id"] is None and first["search_status"] == "not_requested"
        source = client.get("/api/sources/" + first["source_id"]).json()["source"]
        assert source["case_id"] is None
        duplicate = upload(client).json()
        assert duplicate["duplicate"] and duplicate["source_id"] == first["source_id"]
        updated = upload(client, b"Contenido corregido.", document_id=source["document_id"]).json()
        assert updated["source_version"] == 2
        assert client.get("/api/sources").json()["sources"][0]["is_latest"]
        original = client.get("/api/sources/" + first["source_id"] + "/original")
        assert original.status_code == 200
        assert original.content == b"Antecedente ficticio para probar la biblioteca."
        assert "content-disposition" in original.headers
        assert not assessor.calls


def test_recorrido_global_library_excludes_private_evidence(source_app, pdf_bytes):
    backend, case_client, _, _ = source_app
    case = make_case(case_client, pdf_bytes)
    private = backend.state.library.add(
        "private.txt",
        b"Soporte privado.",
        title="Privado",
        origin="Expediente",
        category="case_evidence",
        case_id=case["id"],
    )
    with TestClient(create_recorrido(transport=httpx.ASGITransport(app=backend))) as client:
        assert not client.get("/api/sources").json()["sources"]
        assert client.get("/api/sources/" + private["id"]).status_code == 404


def test_recorrido_reports_backend_failure_without_fake_results():
    def unavailable(request):
        raise httpx.ConnectError("offline")

    with TestClient(create_recorrido(transport=httpx.MockTransport(unavailable))) as client:
        response = client.get("/api/sources")
        assert response.status_code == 503
        assert "biblioteca" in response.json()["detail"]
        assert client.get("/").status_code == 200


def test_uploaded_version_preserves_imported_norm_collection(source_app):
    backend, _, _, _ = source_app
    library = backend.state.library
    library.save_collection({"id": "drive-test", "name": "Normativa de prueba"})
    old = library.add(
        "norma.txt",
        b"Norma inicial.",
        title="Norma",
        origin="Importacion de prueba",
        category="institutional_norm",
        collection_id="drive-test",
    )
    with TestClient(create_recorrido(transport=httpx.ASGITransport(app=backend))) as client:
        response = upload(
            client,
            b"Norma corregida.",
            category="institutional_norm",
            document_id=old["document_id"],
        )
        assert response.status_code == 201, response.text
        updated = client.get("/api/sources/" + response.json()["source_id"]).json()["source"]
        assert updated["collection_id"] == "drive-test" and updated["version"] == 2
        assert client.get("/api/sources/" + old["id"] + "/original").content == b"Norma inicial."
