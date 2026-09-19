"""Un solo ASGI sirve interfaz, servicios y descargas; datos temporales y sin IA real."""

import httpx
import pytest
from fastapi.testclient import TestClient
from test_app import FakeIdentifier, analyze, pdf_bytes, upload  # noqa: F401
from test_office_service_api import (  # noqa: F401
    approved_case,
    generate,
    inputs,
    office_app,
    wait_office,
)
from test_review_service_api import current, save

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.unified_app import create_unified_app


@pytest.fixture
def unified(tmp_path, monkeypatch):
    def no_proxy(*args, **kwargs):
        raise AssertionError("La integración no debe reenviar peticiones HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "request", no_proxy)
    identifier = FakeIdentifier()
    settings = Settings(data_dir=tmp_path / "data", api_key="", port=8772)
    app = create_unified_app(settings, extractor=PDFExtractor(), identifier=identifier,
                             source_extractor=PDFExtractor())
    with TestClient(app) as client:
        yield app, client, identifier, settings


def test_same_app_serves_unchanged_ui_and_direct_api(unified):
    app, client, _, _ = unified
    original = ROOT / "src/pqrs_claro/static/recorrido/index.html"
    assert client.get("/").content == original.read_bytes()
    status = client.get("/recorrido-status").json()
    assert status == {"interface": "recorrido", "library": "connected", "mode": "unified"}
    assert not hasattr(app.state, "backend")
    for path in ("/app.js", "/styles.css", "/logo.png", "/data.json",
                 "/shared/office.js", "/library-evidence.js", "/letterhead-udea.png",
                 "/static/workspace/index.html", "/anterior"):
        assert client.get(path).status_code == 200, path
    for path in ("/api/config", "/api/cases", "/api/sources", "/api/gmail/status"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers['cache-control'] == 'no-store'
        assert 'application/json' in response.headers['content-type']
    assert client.get("/api/cases").json() == []
    assert client.get("/api/not-a-route").status_code == 404


def test_pdf_identification_save_original_and_reopen(unified, pdf_bytes):  # noqa: F811
    app, client, identifier, settings = unified
    case = analyze(client, upload(client, pdf_bytes))
    prefix = f"/api/cases/{case['id']}"
    assert identifier.calls == 1
    result = client.put(prefix + '/identification', json={
        'version': case['version'], 'identification': case['identification']})
    assert result.status_code == 200
    original = client.get(prefix + '/original')
    assert original.content == pdf_bytes
    assert 'inline' in original.headers['content-disposition']
    assert client.get(prefix + '/pages/1.png').headers['content-type'] == 'image/png'
    assert app.state.store.root == settings.data_dir
    # Otro cliente HTTP ve exactamente el mismo expediente, no otra base del proxy.
    other = TestClient(app)
    try:
        assert other.get(prefix).json()['version'] == result.json()['version']
    finally:
        other.close()


def test_same_origin_protection_and_shared_evidence(unified):
    _, client, _, _ = unified
    data = {'title': 'Fuente de prueba', 'origin': 'Prueba aislada',
            'category': 'institutional_norm', 'shared': 'true'}
    for headers in ({'origin': 'https://other.example'}, {'sec-fetch-site': 'cross-site'}):
        response = client.post('/api/evidence', data=data,
                               files={'file': ('source.txt', b'Norma de prueba.')}, headers=headers)
        assert response.status_code == 403
    assert client.get('/api/cases', headers={'host': 'other.example'}).status_code == 400
    response = client.post('/api/evidence', data=data,
                           files={'file': ('source.txt', b'Norma de prueba.')},
                           headers={'origin': 'http://testserver'})
    assert response.status_code == 201, response.text
    sid = response.json()['source_id']
    original = client.get(f'/api/sources/{sid}/original')
    assert original.content == b'Norma de prueba.'
    assert original.headers['x-frame-options'] == 'DENY'


def test_restart_preserves_case_without_repeating_identification(tmp_path, pdf_bytes):  # noqa: F811
    settings = Settings(data_dir=tmp_path / "data", api_key="", port=8772)
    first = create_unified_app(settings, extractor=PDFExtractor(),
                               identifier=FakeIdentifier(), source_extractor=PDFExtractor())
    with TestClient(first) as client:
        case = analyze(client, upload(client, pdf_bytes))
        prefix = f"/api/cases/{case['id']}"
        before = client.get(prefix).json()
    identifier = FakeIdentifier(fail_if_called=True)
    reopened = create_unified_app(settings, extractor=PDFExtractor(),
                                  identifier=identifier, source_extractor=PDFExtractor())
    with TestClient(reopened) as client:
        assert client.get('/recorrido-status').json()['mode'] == 'unified'
        assert client.get(prefix).json() == before
        assert client.get(prefix + '/original').content == pdf_bytes
        assert identifier.calls == 0
        assert not reopened.state.preparation.active


@pytest.mark.parametrize('office_app', ['recorrido'], indirect=True)
def test_unified_office_downloads_and_edit_invalidation(office_app):  # noqa: F811
    app, client, renderer, _ = office_app
    assert client.get('/recorrido-status').json()['mode'] == 'unified'
    case, _ = approved_case(app, client)
    run = wait_office(app, client, case, generate(client, case, inputs(client, case)))
    assert run['status'] == 'ready'
    prefix = f"/api/cases/{case['id']}/office/runs/{run['id']}"
    for kind, signature in [('docx', b'PK'), ('pdf', b'%PDF'), ('zip', b'PK')]:
        response = client.get(prefix + '/files/' + kind)
        assert response.status_code == 200 and response.content.startswith(signature)
        assert 'attachment' in response.headers['content-disposition']
    row = current(client, case)
    assert save(client, case, row, paragraphs=[
        {**row['paragraphs'][0], 'text': 'Edición después de generar.'}]).status_code == 200
    assert client.get(prefix + '/files/pdf').status_code == 409
    assert renderer.calls == 1
