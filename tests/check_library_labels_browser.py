"""Exercise the FIAGA catalog using an isolated local library and a real browser."""

import httpx
from check_fiaga_pool_browser import serve
from playwright.sync_api import expect, sync_playwright
from test_source_service_api import upload_source

from pqrs_claro.config import Settings
from pqrs_claro.unified_app import create_unified_app


def test_edit_and_filter_catalog_by_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    app = create_unified_app(Settings(data_dir=tmp_path / "data", api_key="",
                                     initial_review_enabled=True, management_enabled=True))
    with serve(app) as url, httpx.Client(base_url=url) as api, sync_playwright() as pw:
        upload_source(api, title="Guía de aspirantes 2027-1").raise_for_status()
        other = upload_source(api, title="Acta permanente", content="Texto de otra fuente.")
        other.raise_for_status()
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.get_by_role("heading", name="Recepción de solicitudes")).to_be_visible()
        expect(page.locator("#actor")).to_have_value("admin")
        page.locator(".resources summary").click()
        page.get_by_role("link", name="Biblioteca de fuentes").click()
        cards = page.locator("article.library-source")
        expect(cards).to_have_count(2)
        guide = cards.filter(has_text="Guía de aspirantes")
        guide.get_by_role("button", name="Ver documento").click()
        page.get_by_text("Editar etiquetas", exact=True).click()
        page.get_by_label("Temas (uno por línea)").fill("Examen\nCalendario")
        page.get_by_label("Dependencia emisora", exact=True).fill("Admisiones")
        page.get_by_label("Período al que aplica").fill("2027-1")
        page.get_by_role("button", name="Guardar etiquetas").click()
        expect(page.locator("#library-document dd").first).to_have_text("Calendario, Examen")
        page.locator("#library-back").click()
        page.get_by_label("Tema", exact=True).select_option(label="Examen")
        page.get_by_label("Dependencia emisora", exact=True).select_option(label="Admisiones")
        page.get_by_label("Período", exact=True).select_option(label="2027-1")
        expect(cards).to_have_count(1)
        expect(cards.first).to_contain_text("Guía de aspirantes")
        page.reload()
        page.get_by_label("Período", exact=True).select_option(label="Sin registrar")
        expect(cards).to_have_count(1)
        expect(cards.first).to_contain_text("Acta permanente")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator(".library-panel").evaluate("p => p.scrollWidth <= p.clientWidth + 1")
        assert not errors
        browser.close()
