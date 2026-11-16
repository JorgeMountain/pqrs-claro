"""Guardado al salir de Redacción, con Chrome y expedientes temporales."""

import re
from copy import deepcopy

import httpx
import pytest
from check_redaction_browser import LocalReader, local_server, seed
from playwright.sync_api import expect, sync_playwright
from test_draft_service_api import FakeDraftEngine
from test_preparation import wait
from test_review_service_api import FakeReviewEngine

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.unified_app import create_unified_app


class ReaderWithoutPending(LocalReader):
    def assess(self, request, candidates):
        result = super().assess(request, candidates)
        result["missing"] = []
        return result


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    settings = Settings(data_dir=tmp_path, api_key="", management_enabled=True,
                        initial_review_enabled=True)
    app = create_unified_app(settings, source_assessor=ReaderWithoutPending(),
                             draft_engine=FakeDraftEngine(), review_engine=FakeReviewEngine())
    case, source = seed(app)
    with local_server(app) as url, httpx.Client(base_url=url, trust_env=False) as api:
        prefix = f"/api/cases/{case['id']}"
        api.post(prefix + "/preparation", json={"version": case["version"]}).raise_for_status()
        assert wait(app, api, case["id"])["status"] in {"ready", "waiting_review"}
        with sync_playwright() as pw, pw.chromium.launch(channel="chrome") as browser:
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.add_init_script("""
                localStorage.setItem('pqrs-pilot-manager', 'gestor-1');
                sessionStorage.setItem('gestion-peticiones-responsable-v1', 'Gestor ficticio');
            """)
            page.route("**/data.json", lambda route: route.fulfill(
                path=ROOT / "src/pqrs_claro/static/demo/data.json", content_type="application/json",
            ))
            redaction_url = f"{url}/?case={case['id']}&step=2"
            page.goto(redaction_url, wait_until="networkidle")
            expect(page.locator('[data-action="live-edit"]')).to_have_count(2)
            yield page, api, prefix, redaction_url, source


def edit_and_close(page, index, text):
    if page.locator("#drawer").evaluate("node => node.open"):
        page.locator("#close").click()
    page.locator(f'[data-action="live-edit"][data-index="{index}"]').click()
    paragraph = page.locator("#response-paragraphs textarea").first
    expect(paragraph).to_be_visible()
    paragraph.fill(text)
    page.locator("#close").click()


def save_and_return(page):
    page.locator(".redaction-footer").get_by_role(
        "button", name="Guardar y volver a la bandeja", exact=True,
    ).click()


def rows(api, prefix):
    response = api.get(prefix + "/review")
    response.raise_for_status()
    return response.json()["requests"]


def test_saves_two_closed_editors_before_leaving_and_survives_reload(workspace):
    page, api, prefix, redaction_url, source = workspace
    original = rows(api, prefix)
    texts = ["Respuesta corregida por el gestor para P1.", "Aclaración guardada para P2."]
    for index, text in enumerate(texts):
        edit_and_close(page, index, text)
    save_and_return(page)
    expect(page.locator("#cases-title")).to_be_visible()
    saved = rows(api, prefix)
    for old, new, text in zip(original, saved, texts):
        assert new["paragraphs"][0]["text"] == text
        assert new["paragraphs"][0]["cited_chunk_ids"] == old["paragraphs"][0]["cited_chunk_ids"]
        assert new["edited_by"] == "Gestor ficticio"
    page.locator(f'[data-management-action="continue"][data-id="{prefix.split("/")[-1]}"]'
                 ).click()
    expect(page.locator(".redaction-workspace")).to_be_visible()
    for text in texts:
        expect(page.locator("#view")).to_contain_text(text)
    page.reload(wait_until="networkidle")
    for text in texts:
        expect(page.locator("#view")).to_contain_text(text)
    page.locator('[data-action="live-sources"][data-index="1"]').click()
    link = page.locator('#redaction-context a[href*="/api/sources/"][href*="/original"]')
    expect(link).to_have_attribute("href", re.compile(source["id"]))
    assert api.get(link.get_attribute("href")).status_code == 200
    assert "step=2" in page.url and redaction_url.split("?")[0] in page.url


@pytest.mark.parametrize("width", [1440, 390])
def test_partial_failure_keeps_the_page_and_allows_retry(workspace, width, tmp_path):
    page, api, prefix, _, _ = workspace
    page.set_viewport_size({"width": width, "height": 960 if width == 1440 else 844})
    texts = ["Primera respuesta para el guardado parcial.", "Segunda respuesta tras reintentar."]
    for index, text in enumerate(texts):
        edit_and_close(page, index, text)
    endpoint = prefix + "/review/requests/P2"
    failed = []

    def fail_once(route):
        if route.request.method == "PUT" and not failed:
            failed.append(True)
            route.fulfill(status=503, content_type="application/json",
                          body='{"detail":"Fallo transitorio de prueba al guardar."}')
        else:
            route.continue_()

    page.route("**" + endpoint, fail_once)
    with page.expect_response(lambda r: r.url.endswith(endpoint) and r.status == 503):
        save_and_return(page)
    expect(page.locator(".redaction-workspace")).to_be_visible()
    expect(page.locator("#cases-title")).to_have_count(0)
    error = page.locator("[data-redaction-save-error]")
    expect(error).to_contain_text("Fallo transitorio de prueba")
    error.scroll_into_view_if_needed()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for control in (error, page.locator('[data-action="live-continue-draft"]')):
        bounds = control.bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    page.screenshot(path=str(tmp_path / f"aviso-guardado-{width}.png"), animations="disabled")
    saved_first = rows(api, prefix)[0]
    assert saved_first["paragraphs"][0]["text"] == texts[0]
    page.locator('[data-action="live-edit"][data-index="1"]').click()
    expect(page.locator("#response-paragraphs textarea").first).to_have_value(texts[1])
    page.locator("#close").click()
    save_and_return(page)
    expect(page.locator("#cases-title")).to_be_visible()
    saved = rows(api, prefix)
    assert [row["paragraphs"][0]["text"] for row in saved] == texts
    assert saved[0]["revision"] == saved_first["revision"]


def test_conflict_preserves_local_text_and_does_not_overwrite_other_editor(workspace):
    page, api, prefix, _, _ = workspace
    local_text = "Aporte todavía local de esta pestaña."
    edit_and_close(page, 0, local_text)
    previous = rows(api, prefix)[0]
    paragraphs = deepcopy(previous["paragraphs"])
    paragraphs[0]["text"] = "Aporte confirmado por otra sesión."
    response = api.put(prefix + "/review/requests/P1", json={
        "revision": previous["revision"], "edited_by": "Otro gestor ficticio",
        "paragraphs": paragraphs, "pending_resolutions": [],
    })
    response.raise_for_status()
    save_and_return(page)
    expect(page.locator("[data-redaction-save-error], #notice, #response-edit-error").filter(
        has_text=re.compile("cambi|versión|sesión", re.I),
    ).first).to_be_visible()
    expect(page.locator(".redaction-workspace")).to_be_visible()
    saved = rows(api, prefix)[0]
    assert saved["paragraphs"] == response.json()["paragraphs"]
    assert saved["revision"] == response.json()["revision"]
    if not page.locator("#drawer").evaluate("node => node.open"):
        page.locator('[data-action="live-edit"][data-index="0"]').click()
    expect(page.locator("#response-paragraphs textarea").first).to_have_value(local_text)
