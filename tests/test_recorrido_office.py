# ruff: noqa: F811
"""El recorrido entrega oficios mediante los contratos existentes y conserva la vigencia."""

import httpx
from fastapi.testclient import TestClient
from test_office_service_api import (  # noqa: F401
    approved_case,
    generate,
    inputs,
    office_app,
    wait_office,
)
from test_review_service_api import current, save

from pqrs_claro.recorrido_app import create_recorrido


def test_recorrido_office_download_and_edit_invalidation(office_app):
    backend, original, renderer, _ = office_app
    case, _ = approved_case(backend, original)
    with TestClient(create_recorrido(transport=httpx.ASGITransport(app=backend))) as client:
        for name in (
            "office.js",
            "office-view.js",
            "office-preview.js",
            "review-fields.js",
            "ui.js",
        ):
            asset = client.get("/shared/" + name)
            assert asset.status_code == 200 and "javascript" in asset.headers["content-type"]
        body = inputs(client, case)
        run = wait_office(backend, client, case, generate(client, case, body))
        assert run["status"] == "ready"
        prefix = f"/api/cases/{case['id']}/office/runs/{run['id']}"
        for kind, signature in [("docx", b"PK"), ("pdf", b"%PDF"), ("zip", b"PK")]:
            result = client.get(prefix + "/files/" + kind)
            assert result.status_code == 200 and result.content.startswith(signature)
            assert "attachment" in result.headers["content-disposition"]
        assert client.get(prefix + "/pages/1").headers["content-type"] == "image/png"
        row = current(client, case)
        assert (
            save(
                client,
                case,
                row,
                paragraphs=[{**row["paragraphs"][0], "text": "Texto cambiado después de generar."}],
            ).status_code
            == 200
        )
        assert client.get(prefix + "/files/pdf").status_code == 409
        assert renderer.calls == 1
