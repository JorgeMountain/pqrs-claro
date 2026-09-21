"""Recepción controlada: transporte Google doble, SQLite temporal, sin correo real."""

import base64
import copy
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from urllib.parse import parse_qs, urlparse

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.gmail_auth import SCOPE, GmailAuth, GmailError, SecretStore
from pqrs_claro.gmail_content import body_pdf, case_numbers, parse_message
from pqrs_claro.recorrido_app import create_recorrido


class MemoryVault:
    def __init__(self):
        self.data = {}

    def read(self, name):
        return copy.deepcopy(self.data.get(name, {}))

    def write(self, name, value):
        self.data[name] = copy.deepcopy(value)

    def delete(self, name):
        self.data.pop(name, None)


def pdf_bytes(text="Solicitud de prueba. Entregar copia del acta."):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 75), text)
        return doc.tobytes()


def email_bytes(subject="[PRUEBA PQRS] Caso 001", text="Solicito copia del acta.", pdf=True):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, "remitente@example.org", "prueba@example.org"
    msg["Message-ID"] = "<prueba-001@example.org>"
    msg["Date"] = "Wed, 16 Sep 2026 08:00:00 -0500"
    msg.set_content(text)
    if pdf:
        msg.add_attachment(
            pdf_bytes(), maintype="application", subtype="pdf", filename="peticion.pdf"
        )
    return msg.as_bytes()


class GoogleDouble:
    def __init__(self):
        self.messages = {
            "m1": email_bytes(),
            "m2": email_bytes(pdf=False),
            "m3": email_bytes(text="Aviso de seguimiento.", pdf=False),
        }
        self.calls = []
        self.scope = SCOPE

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "fake-access-not-real",
                    "refresh_token": "fake-refresh-not-real",
                    "expires_in": 3600,
                    "scope": self.scope,
                },
            )
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "prueba@example.org"})
        if path.endswith("/labels"):
            return httpx.Response(
                200, json={"labels": [{"id": "Label_Test", "name": "PQRS-Pruebas"}]}
            )
        if path.endswith("/messages"):
            assert request.url.params["labelIds"] == "Label_Test"
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": m} for m in self.messages],
                    "nextPageToken": "another-page",
                },
            )
        mid = path.rsplit("/", 1)[-1]
        if mid not in self.messages:
            return httpx.Response(404, json={"error": "not found"})
        if request.url.params.get("format") == "metadata":
            return httpx.Response(
                200,
                json={
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Caso 001"},
                            {"name": "From", "value": "remitente@example.org"},
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "id": mid,
                "threadId": "thread1",
                "internalDate": "1789563600000",
                "raw": base64.urlsafe_b64encode(self.messages[mid]).decode(),
            },
        )


@pytest.fixture(params=["workspace", "recorrido"])
def mail_app(tmp_path, request):
    google, vault = GoogleDouble(), MemoryVault()
    auth = GmailAuth(tmp_path, vault=vault, transport=httpx.MockTransport(google))
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings, extractor=PDFExtractor(), gmail_auth=auth,
                     interface=request.param)
    with TestClient(app) as client:
        yield app, client, auth, google, vault


def configure(client):
    payload = {
        "installed": {
            "client_id": "test.apps.googleusercontent.com",
            "client_secret": "fake-secret",
            "token_uri": "https://invalid.test",
        }
    }
    result = client.post(
        "/api/gmail/configure", files={"file": ("client.json", json.dumps(payload))}
    )
    assert result.status_code == 200, result.text


def test_recorrido_rejects_foreign_configuration_and_preserves_oauth_headers(mail_app):
    backend, _, _, _, vault = mail_app
    with TestClient(create_recorrido(transport=httpx.ASGITransport(app=backend))) as client:
        response = client.post(
            "/api/gmail/configure",
            headers={"Origin": "https://foreign.example"},
            files={"file": ("client.json", b"{}")},
        )
        assert response.status_code == 403 and not vault.read("client")
        assert (
            client.post(
                "/api/gmail/disconnect", headers={"sec-fetch-site": "cross-site"}
            ).status_code
            == 403
        )
        assert (
            client.get("/api/gmail/status", headers={"Host": "foreign.example"}).status_code == 400
        )
        configure(client)
        response = client.post("/api/gmail/authorize", headers={"Origin": "http://testserver"})
        assert response.status_code == 200
        params = parse_qs(urlparse(response.json()["url"]).query)
        response = client.get(
            "/api/gmail/oauth/callback", params={"state": params["state"][0], "code": "fake-code"}
        )
        assert response.status_code == 200
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"


def connect(client):
    configure(client)
    result = client.post("/api/gmail/authorize")
    params = parse_qs(urlparse(result.json()["url"]).query)
    assert params["scope"] == [SCOPE]
    assert params["code_challenge_method"] == ["S256"]
    callback = client.get(
        "/api/gmail/oauth/callback", params={"state": params["state"][0], "code": "fake-code"}
    )
    assert callback.status_code == 200, callback.text
    return params


def ingest(client, mid="m1", mode="pdf", **kwargs):
    detail = client.get(f"/api/gmail/messages/{mid}", params={"account": "prueba@example.org"})
    assert detail.status_code == 200, detail.text
    message = detail.json()
    body = {
        "account": "prueba@example.org",
        "mode": mode,
        "case_number": "001",
        "body_confirmed": mode == "body",
    }
    if mode == "pdf":
        body["attachment_id"] = message["attachments"][0]["id"]
    return client.post(f"/api/gmail/messages/{mid}/import", json={**body, **kwargs})


def test_oauth_pkce_state_and_minimum_scope(mail_app):
    _, client, auth, google, _ = mail_app
    params = connect(client)
    assert client.get("/api/gmail/status").json()["account"] == "prueba@example.org"
    exchange = next(r for r in google.calls if r.url.path == "/token")
    verifier = parse_qs(exchange.content.decode())["code_verifier"][0]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert params["code_challenge"] == [challenge]
    assert all(
        r.url.host in {"gmail.googleapis.com", "oauth2.googleapis.com"} for r in google.calls
    )
    replay = client.get(
        "/api/gmail/oauth/callback", params={"state": params["state"][0], "code": "private-code"}
    )
    assert replay.status_code == 400 and "private-code" not in replay.text
    assert not auth.flows


def test_expired_denied_and_missing_scope(mail_app):
    _, client, auth, google, _ = mail_app
    configure(client)
    params = parse_qs(urlparse(client.post("/api/gmail/authorize").json()["url"]).query)
    auth.flows[params["state"][0]]["expires"] = 0
    assert (
        client.get(
            "/api/gmail/oauth/callback", params={"state": params["state"][0], "code": "x"}
        ).status_code
        == 400
    )
    params = parse_qs(urlparse(client.post("/api/gmail/authorize").json()["url"]).query)
    assert (
        client.get(
            "/api/gmail/oauth/callback", params={"state": params["state"][0], "error": "denied"}
        ).status_code
        == 400
    )
    google.scope = "other-scope"
    params = parse_qs(urlparse(client.post("/api/gmail/authorize").json()["url"]).query)
    assert (
        client.get(
            "/api/gmail/oauth/callback", params={"state": params["state"][0], "code": "x"}
        ).status_code
        == 400
    )
    assert not client.get("/api/gmail/status").json()["connected"]


def test_bad_configuration_and_origin(mail_app):
    _, client, _, _, _ = mail_app
    for payload in [b"not json", b"{}", b'{"web":{}}', b"x" * 65537]:
        assert (
            client.post(
                "/api/gmail/configure", files={"file": ("client.json", payload)}
            ).status_code
            == 422
        )
    assert (
        client.post("/api/gmail/authorize", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/api/gmail/oauth/callback?state=unknown&code=hidden").status_code == 400


def test_filter_pagination_refresh_and_disconnect(mail_app):
    _, client, _, google, vault = mail_app
    connect(client)
    vault.data["token"]["expires"] = 0
    data = client.get("/api/gmail/messages").json()
    assert len(data["messages"]) == 3 and data["next_page"] == "another-page"
    assert vault.data["token"]["expires"] > time.time()
    client.get("/api/gmail/messages?page_token=another-page")
    assert any(r.url.params.get("pageToken") == "another-page" for r in google.calls)
    before = len([r for r in google.calls if r.url.path.endswith("/messages")])
    missing = client.get("/api/gmail/messages?label=missing").json()
    assert missing["notice"] and not missing["messages"]
    assert len([r for r in google.calls if r.url.path.endswith("/messages")]) == before
    assert "access_token" not in client.get("/api/gmail/status").text
    client.post("/api/gmail/disconnect")
    assert client.get("/api/gmail/messages").status_code == 422
    assert all(r.method == "GET" or r.url.path == "/token" for r in google.calls)


def test_pdf_import_duplicate_and_manual_upload_preserved(mail_app):
    app, client, _, google, _ = mail_app
    connect(client)
    result = ingest(client)
    assert result.status_code == 200, result.text
    cid = result.json()["case_id"]
    case = client.get("/api/cases/" + cid).json()
    assert case["status"] == "uploaded" and case["received_at"] is None
    assert case["origin"]["reported_case_number"] == "001"
    assert case["origin"]["email_received_at"]
    assert ingest(client).json()["duplicate"]
    assert len(client.get("/api/cases").json()) == 1
    mail = client.get("/api/gmail/cases/" + cid).json()["messages"][0]
    assert client.get("/api/gmail/originals/" + mail["key"]).content == google.messages["m1"]
    manual = client.post("/api/cases", files={"file": ("manual.pdf", pdf_bytes())})
    assert manual.status_code == 201 and "origin" not in manual.json()
    assert len(app.state.store.list()) == 2


def test_reimport_cannot_resurrect_a_case_in_trash(mail_app):
    app, client, _, _, _ = mail_app
    connect(client)
    cid = ingest(client).json()['case_id']
    path = '/api/cases/' + cid
    before = client.get(path).json()
    original = client.get(path + '/original').content
    action = dict(version=before['version'], lifecycle_revision=0, confirmed=True)
    assert client.request('DELETE', path, json=action).status_code == 200
    response = ingest(client)
    assert response.status_code == 409 and 'papelera' in response.json()['detail']
    assert not app.state.store.list()
    assert len(app.state.store.list(deleted=True)) == 1
    restored = client.post(path + '/restore', json={**action, 'lifecycle_revision': 1})
    assert restored.status_code == 200
    assert ingest(client).json()['duplicate']
    assert client.get(path).json() == before
    assert client.get(path + '/original').content == original


def test_import_is_idempotent_for_concurrent_clicks(mail_app):
    app, client, _, _, _ = mail_app
    connect(client)
    from pqrs_claro.gmail_api import ImportMail

    detail = app.state.gmail.detail("m1", "prueba@example.org")
    body = ImportMail(
        account="prueba@example.org", mode="pdf", attachment_id=detail["attachments"][0]["id"]
    )
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        return app.state.gmail.import_message("m1", body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert len({r["case_id"] for r in results}) == 1
    assert sum(r["duplicate"] for r in results) == 1
    assert len(app.state.store.list()) == 1


def test_recover_import_after_case_created_before_receipt(mail_app, monkeypatch):
    app, client, _, _, _ = mail_app
    connect(client)
    client.get("/api/gmail/messages/m1?account=prueba@example.org")
    save = app.state.gmail.save
    monkeypatch.setattr(
        app.state.gmail, "save", lambda row: (_ for _ in ()).throw(RuntimeError("crash"))
    )
    with pytest.raises(RuntimeError):
        ingest(client)
    monkeypatch.setattr(app.state.gmail, "save", save)
    result = ingest(client)
    assert result.status_code == 200 and len(app.state.store.list()) == 1


def test_email_body_confirmation_and_unicode_pdf(mail_app):
    _, client, _, _, _ = mail_app
    connect(client)
    assert ingest(client, "m2", "body", body_confirmed=False).status_code == 422
    result = ingest(client, "m2", "body")
    assert result.status_code == 200, result.text
    pdf = client.get("/api/cases/" + result.json()["case_id"] + "/original").content
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        text = "".join(p.get_text() for p in doc)
    assert "Solicito copia del acta" in text and "Copia de consulta del correo" in text


def test_followup_link_keeps_case_version_and_original(mail_app):
    _, client, _, _, _ = mail_app
    connect(client)
    cid = ingest(client).json()["case_id"]
    before = client.get("/api/cases/" + cid).json()
    detail = client.get("/api/gmail/messages/m3?account=prueba@example.org").json()
    assert detail["related_cases"][0]["case_id"] == cid
    linked = ingest(client, "m3", "link", target_case_id=cid)
    assert linked.status_code == 200 and linked.json()["linked"]
    assert client.get("/api/cases/" + cid).json() == before
    assert len(client.get("/api/gmail/cases/" + cid).json()["messages"]) == 2
    client.post("/api/gmail/disconnect")
    assert len(client.get("/api/gmail/cases/" + cid).json()["messages"]) == 2


def test_account_change_invalid_pdf_and_original_integrity(mail_app):
    app, client, _, google, vault = mail_app
    connect(client)
    assert client.get("/api/gmail/messages/m1?account=other@example.org").status_code == 422
    detail = client.get("/api/gmail/messages/m1?account=prueba@example.org").json()
    (app.state.gmail.root / "messages" / detail["key"] / "original.eml").write_bytes(b"modified")
    assert ingest(client).status_code == 422
    vault.data["token"]["account"] = "other@example.org"
    assert (
        client.post(
            "/api/gmail/messages/m2/import",
            json={"account": "prueba@example.org", "mode": "body", "body_confirmed": True},
        ).status_code
        == 422
    )


def test_html_email_is_plain_text_and_no_fake_case_number():
    msg = EmailMessage()
    msg["Subject"] = "Actualización Caso#001 y radicado 002"
    msg.set_content(
        "<p>Petición: café, asignación y año.</p><script>alert(1)</script>"
        '<img src="https://tracker.example/pixel"><a href="https://portal.example">Ver caso</a>',
        subtype="html",
    )
    public, _ = parse_message(msg.as_bytes(), {"id": "m1"})
    assert "alert" not in public["text"] and "tracker" not in public["text"]
    assert "café" in public["text"] and public["case_number"] == ""
    assert public["case_numbers"] == ["001", "002"]
    assert case_numbers("Sin radicado ni número") == []
    assert len(body_pdf(public)) > 100


def test_blank_or_truncated_text_not_imported():
    with pytest.raises(ValueError):
        body_pdf({"text": "", "text_too_long": False})
    with pytest.raises(ValueError):
        body_pdf({"text": "partial", "text_too_long": True})


def test_google_errors_do_not_expose_response(tmp_path):
    auth = GmailAuth(
        tmp_path,
        vault=MemoryVault(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, text="secret-provider-response")
        ),
    )
    with pytest.raises(GmailError, match="autorización") as error:
        auth._request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")
    assert "secret-provider" not in str(error.value)
    auth.close()


def test_windows_secret_store_uses_protection(tmp_path):
    pytest.importorskip("win32crypt")
    store = SecretStore(tmp_path)
    store.write("test", {"refresh_token": "fake-token-to-protect"})
    assert b"fake-token-to-protect" not in (tmp_path / "test.protected").read_bytes()
    assert store.read("test")["refresh_token"] == "fake-token-to-protect"
    store.delete("test")
    assert store.read("test") == {}
