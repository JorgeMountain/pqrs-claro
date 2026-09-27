import json

import httpx
import pytest
from fastapi.testclient import TestClient

from pqrs_claro.laya_lab import create_laya_lab_app


def test_cloud_contract_and_no_secret_or_input_echo():
    def handler(request):
        assert str(request.url) == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
        assert request.headers["authorization"] == "Bearer private-test-key"
        body = json.loads(request.content)
        assert body["model"] == "typesafe-ai/jev"
        assert set(body["questions"]) == {"petition_type", "rude_language"}
        return httpx.Response(
            200,
            json={
                "answers": {
                    "petition_type": {"choice": "information", "extra": body["state"]},
                    "rude_language": {"noul": 0.01},
                },
                "debug": "private-test-key",
                "state": body["state"],
            },
        )

    app = create_laya_lab_app(
        jev_api_key="private-test-key", jev_transport=httpx.MockTransport(handler)
    )
    response = TestClient(app).post(
        "/api/classify", data={"provider": "jev", "text": "Fictional data"}
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "jev"
    assert "private-test-key" not in response.text
    assert "Fictional data" not in response.text


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_cloud_errors_do_not_echo_provider_body(status):
    app = create_laya_lab_app(
        jev_api_key="test-key",
        jev_transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="sensitive data")
        ),
    )
    response = TestClient(app).post("/api/classify", data={"provider": "jev", "text": "Sample"})
    assert response.status_code == 502
    assert "sensitive data" not in response.text


def test_missing_key_blocks_cloud():
    app = create_laya_lab_app(jev_api_key="")
    response = TestClient(app).post("/api/classify", data={"provider": "jev", "text": "Sample"})
    assert response.status_code == 503


def test_customer_verification_error_has_actionable_message():
    app = create_laya_lab_app(
        jev_api_key="test-key",
        jev_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403,
                json={
                    "error": {"type": "customer_verification_required", "message": "private"},
                },
            )
        ),
    )
    response = TestClient(app).post("/api/classify", data={"provider": "jev", "text": "Sample"})
    assert response.status_code == 502
    assert "tarjeta" in response.json()["detail"]
    assert "private" not in response.text


def test_invalid_cloud_answer_is_rejected():
    app = create_laya_lab_app(
        jev_api_key="test-key",
        jev_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "answers": {
                        "petition_type": {"choice": "information"},
                        "rude_language": {"noul": 2},
                    },
                },
            )
        ),
    )
    response = TestClient(app).post("/api/classify", data={"provider": "jev", "text": "Sample"})
    assert response.status_code == 502
