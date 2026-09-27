"""Pruebas del banco aislado: entrada temporal y contrato con Laya local."""

import json

import httpx
import pymupdf
from fastapi.testclient import TestClient

from pqrs_claro.laya_lab import MAX_TEXT_CHARS, QUESTIONS, create_laya_lab_app


def make_laya_reply(model="multilingual"):
    return {
        "answers": {
            "petition_type": {
                "type": "choice",
                "choice": "information",
                "probabilities": {"information": 0.8, "complaint": 0.2},
                "confidence": 0.4,
            },
            "rude_language": {
                "type": "noul",
                "noul": 0.1,
                "confidence": 0.3,
            },
        },
        "routing": {"model": model},
        "usage": {"input_tokens": 123},
        "latency_ms": 42.0,
    }


def client_for(handler):
    transport = httpx.MockTransport(handler)
    app = create_laya_lab_app(laya_transport=transport)
    return TestClient(app)


def selectable_pdf(text):
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_pasted_text_uses_separate_local_models_and_is_not_echoed():
    received = []

    def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(
                200,
                json={"models": {"multilingual": "ready"}, "version": "test", "device": "cpu"},
            )
        payload = json.loads(request.content)
        received.append(payload)
        return httpx.Response(200, json=make_laya_reply(payload["model"]))

    client = client_for(handler)
    text = "Solicitud ficticia de información para probar el banco."
    response = client.post("/api/classify", data={"text": text})

    assert response.status_code == 200
    assert len(received) == 2
    assert received[0]["state"] == received[1]["state"] == text
    assert received[0]["model"] == "english"
    assert received[1]["model"] == "multilingual"
    assert received[0]["lang"] == received[1]["lang"] == "es"
    assert received[0]["questions"] == {"petition_type": QUESTIONS["petition_type"]}
    assert received[1]["questions"] == {"rude_language": QUESTIONS["rude_language"]}
    assert response.json()["result"]["routing"]["models"] == {
        "petition_type": "english",
        "rude_language": "multilingual",
    }
    assert response.json()["result"]["usage"] == {
        "input_tokens": 246,
        "max_input_tokens": 123,
    }
    assert response.json()["character_count"] == len(text)
    assert text not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_pdf_text_is_extracted_in_memory_and_not_returned():
    received = []

    def handler(request):
        payload = json.loads(request.content)
        received.append(payload)
        return httpx.Response(200, json=make_laya_reply(payload["model"]))

    client = client_for(handler)
    text = "Texto ficticio que solo debe viajar a Laya en el equipo."
    response = client.post(
        "/api/classify",
        files={"file": ("anonimizado.pdf", selectable_pdf(text), "application/pdf")},
    )

    assert response.status_code == 200
    assert len(received) == 2
    assert all(item["state"] == text for item in received)
    assert response.json()["source"] == "PDF"
    assert response.json()["page_count"] == 1
    assert text not in response.text


def test_empty_and_overlong_text_are_rejected_before_calling_laya():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=make_laya_reply())

    client = client_for(handler)
    empty = client.post("/api/classify", data={"text": "   "})
    long = client.post("/api/classify", data={"text": "x" * (MAX_TEXT_CHARS + 1)})

    assert empty.status_code == 422
    assert long.status_code == 413
    assert calls == []


def test_unrecognized_models_are_rejected_without_calling_laya():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=make_laya_reply())

    client = client_for(handler)
    response = client.post(
        "/api/classify",
        data={"text": "Ejemplo ficticio.", "type_model": "remote-model"},
    )

    assert response.status_code == 422
    assert calls == []


def test_pdf_without_selectable_text_is_rejected_without_ocr_or_laya_call():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=make_laya_reply())

    client = client_for(handler)
    response = client.post(
        "/api/classify",
        files={"file": ("escaneado.pdf", selectable_pdf(""), "application/pdf")},
    )

    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]
    assert calls == []


def test_unavailable_laya_is_reported_without_fallback():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    client = client_for(handler)
    status = client.get("/api/status")
    response = client.post("/api/classify", data={"text": "Ejemplo ficticio."})

    assert status.status_code == 200
    assert status.json()["connected"] is False
    assert response.status_code == 503
    assert "Laya local" in response.json()["detail"]
