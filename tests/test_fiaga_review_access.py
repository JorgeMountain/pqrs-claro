"""FIAGA keeps its four human review gates even on installations with optional legacy review."""

from fastapi.testclient import TestClient
from test_source_service_api import TwoRequestsIdentifier, pdf_bytes  # noqa: F401

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings


def test_pdf_receipt_captures_collections_without_loading_catalog(tmp_path, pdf_bytes, monkeypatch):  # noqa: F811
    app = create_app(Settings(data_dir=tmp_path, api_key=""))
    library = app.state.library
    for collection in ("archivo", "respuestas"):
        library.save_collection({"id": collection, "name": collection})

    def fail_catalog_read():
        raise AssertionError("Receiving a PDF should only read the collection identifiers.")

    with TestClient(app) as client:
        monkeypatch.setattr(library, "collections", fail_catalog_read)
        received = client.post("/api/cases", data={"workflow": "fiaga"},
                               files={"file": ("caso.pdf", pdf_bytes, "application/pdf")})
        assert received.status_code == 201
        case_id = received.json()["id"]
        library.save_collection({"id": "posterior", "name": "Posterior"})
        assert library.linked_collections(case_id) == ["archivo", "respuestas"]
        assert client.get(f"/api/cases/{case_id}/pool").json()["stage"] == "admin_review"


def test_only_admin_can_review_and_upload_case_evidence(tmp_path, pdf_bytes):  # noqa: F811
    app = create_app(Settings(data_dir=tmp_path, api_key=""), identifier=TwoRequestsIdentifier())
    with TestClient(app) as client:
        case = client.post("/api/cases", data={"workflow": "fiaga"},
                           files={"file": ("caso.pdf", pdf_bytes, "application/pdf")}).json()
        base = "/api/cases/" + case["id"]
        admin = {"X-Fiaga-Actor": "admin"}
        assert client.get(base).json()["management"]["owner_name"] == "Administrador"
        assert "admin" not in [item["id"] for item in client.get("/api/managers").json()]
        assert client.get(base + "/initial-review").json()["enabled"]
        assert client.post(base + "/analyze", headers=admin).status_code == 409
        for headers in ({}, {"X-Fiaga-Actor": "gestor-1"}):
            assert client.post(base + "/preanalysis/check", headers=headers,
                               json={"actor_id": "admin"}).status_code == 409
            assert client.post("/api/evidence", headers=headers,
                               data={"case_id": case["id"], "category": "case_evidence",
                                     "title": "Acta", "origin": "Archivo"},
                               files={"file": ("acta.txt", b"Evidencia")}).status_code == 409
        assert client.get(base + "/preanalysis").json()["approval"] is None
        assert client.get(base + "/pool").json()["stage"] == "admin_review"
