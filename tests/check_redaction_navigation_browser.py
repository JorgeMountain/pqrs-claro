"""Navegación respuesta/fuentes en Chrome sin nuevas lecturas ni escrituras."""

from collections import Counter

import httpx
from check_redaction_browser import OLD_PENDING, LocalReader, local_server, seed
from playwright.sync_api import expect, sync_playwright
from test_draft_service_api import FakeDraftEngine
from test_preparation import wait
from test_review_service_api import FakeReviewEngine

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.unified_app import create_unified_app


class CountingReader(LocalReader):
    def __init__(self):
        self.calls = Counter()

    def assess(self, request, candidates):
        self.calls[request["id"]] += 1
        return super().assess(request, candidates)


def mount_page(browser, url, case_id, *, width=390):
    page = browser.new_page(viewport={"width": width, "height": 960})
    page.add_init_script("localStorage.setItem('pqrs-pilot-manager','gestor-1')")
    page.route("**/data.json", lambda route: route.fulfill(
        path=ROOT / "src/pqrs_claro/static/demo/data.json", content_type="application/json",
    ))
    page.goto(f"{url}/?case={case_id}&step=2", wait_until="networkidle")
    return page


def test_source_return_keeps_selected_petition_and_does_not_write_or_run_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    reader, drafts = CountingReader(), FakeDraftEngine()
    app = create_unified_app(
        Settings(data_dir=tmp_path, api_key="", management_enabled=True,
                 initial_review_enabled=True),
        source_assessor=reader, draft_engine=drafts, review_engine=FakeReviewEngine(),
    )
    case, _ = seed(app, count=3)
    case_id = case["id"]
    prefix = f"/api/cases/{case_id}"
    with local_server(app) as url, httpx.Client(base_url=url, trust_env=False) as api:
        api.post(prefix + "/preparation", json={"version": case["version"]}).raise_for_status()
        assert wait(app, api, case_id)["status"] in {"ready", "waiting_review"}
        before = api.get(prefix + "/review").json()["requests"]
        reader_calls, draft_calls = reader.calls.copy(), drafts.calls.copy()
        with sync_playwright() as pw, pw.chromium.launch(channel="chrome") as browser:
            for width in (320, 390, 768, 1024, 1440):
                page = mount_page(browser, url, case_id, width=width)
                writes = []
                page.on("request", lambda request: writes.append(request.url)
                        if request.method in {"PUT", "POST", "DELETE"}
                        and not any(part in request.url for part in (
                            "/activity", "/work-time", "/work-session",
                        ))
                        else None)
                for index in (1, 0, 2, 1):
                    request_id = f"P{index + 1}"
                    page.locator(f'[data-action="live-sources"][data-index="{index}"]').click()
                    context = page.locator("#redaction-context")
                    expect(context.locator(".redaction-context-request")).to_contain_text(
                        f"Petición {index + 1}",
                    )
                    expect(context.locator(".pending-task h4")).to_have_text(OLD_PENDING)
                    if width <= 390:
                        assert context.locator("h2").evaluate("""e =>
                            e.getBoundingClientRect().top >= document.querySelector(
                                '.workspace-rail').getBoundingClientRect().bottom
                        """), "La barra móvil no debe cubrir el título de las fuentes"
                    target = page.locator(f'[data-response-id="{request_id}"] > summary')
                    target.click()
                    expect(target.locator("..")).not_to_have_attribute("open", "")
                    action = "live-response-return-end" if index == 2 else "live-response-return"
                    back = context.locator(f'[data-action="{action}"]')
                    expect(back).to_be_visible()
                    back.focus()
                    page.keyboard.press("Enter")
                    expect(target).to_be_focused()
                    expect(target.locator("..")).to_have_attribute("open", "")
                    if width <= 390:
                        assert target.evaluate("""e =>
                            e.getBoundingClientRect().top >= document.querySelector(
                                '.workspace-rail').getBoundingClientRect().bottom
                        """), "La barra móvil no debe cubrir la petición enfocada"
                    assert f"request={request_id}" in page.url
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.reload(wait_until="networkidle")
                selected = page.locator("#redaction-context .redaction-context-request")
                expect(selected).to_contain_text("Petición 2")
                page.locator('[data-action="live-response-return"]').click()
                expect(page.locator('[data-response-id="P2"] > summary')).to_be_focused()
                page.locator('.workflow-shortcuts [data-action="live-stage-actions"]').click()
                expect(page.locator(".response-reading")).to_be_focused()
                if width == 390:
                    page.wait_for_timeout(5500)
                    expect(page.locator(".response-reading")).to_be_focused()
                assert not api.get(prefix + "/review").json()["reading_confirmation"]["confirmed"]
                assert writes == [], writes
                page.close()
        assert reader.calls == reader_calls
        assert drafts.calls == draft_calls
        assert api.get(prefix + "/review").json()["requests"] == before


RESTRICTED_QUOTE = "Los requisitos institucionales incluyen el registro AURORA-61 firmado."
RESTRICTED_PENDING = "Comprobar la firma del registro privado AURORA-61."


class RestrictedReader(CountingReader):
    def assess(self, request, candidates):
        self.calls[request["id"]] += 1
        source = next(item for item in candidates if item["title"] == "Norma reservada ficticia")
        return dict(
            request_id=request["id"], status="references_found", summary="Revisión ficticia",
            supports=[{**source, "role": "rule", "reason": "Consta en la fuente de prueba."}],
            missing=[{"kind": "fact", "description": RESTRICTED_PENDING}], warnings=[],
        )


def test_return_after_revocation_does_not_restore_withdrawn_quote_or_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    reader, drafts = RestrictedReader(), FakeDraftEngine()
    app = create_unified_app(
        Settings(data_dir=tmp_path, api_key="", management_enabled=True,
                 initial_review_enabled=True),
        source_assessor=reader, draft_engine=drafts, review_engine=FakeReviewEngine(),
    )
    case, _ = seed(app, count=3)
    collection = "coleccion-navegacion-retirable"
    app.state.library.save_collection({"id": collection, "title": "Colección de QA"})
    source = app.state.library.add(
        "norma-reservada.txt", RESTRICTED_QUOTE.encode(), title="Norma reservada ficticia",
        category="institutional_norm", origin="Prueba aislada", collection_id=collection,
    )
    case_id, prefix = case["id"], f"/api/cases/{case['id']}"
    with local_server(app) as url, httpx.Client(base_url=url, trust_env=False) as api:
        api.put(prefix + "/source-collections", json={"collection_ids": [collection]}
                ).raise_for_status()
        api.post(prefix + "/preparation", json={"version": case["version"]}).raise_for_status()
        assert wait(app, api, case_id)["status"] in {"ready", "waiting_review"}
        reader_calls, draft_calls = reader.calls.copy(), drafts.calls.copy()
        with sync_playwright() as pw, pw.chromium.launch(channel="chrome") as browser:
            page = mount_page(browser, url, case_id)
            page.locator('[data-action="live-sources"][data-index="1"]').click()
            expect(page.locator("#redaction-context blockquote")).to_have_text(RESTRICTED_QUOTE)
            expect(page.locator("#redaction-context .pending-task h4")).to_have_text(
                RESTRICTED_PENDING,
            )
            origin = page.evaluate("performance.timeOrigin")
            api.put(prefix + "/source-collections", json={"collection_ids": []}
                    ).raise_for_status()
            expect(page.locator("#view")).not_to_contain_text(RESTRICTED_QUOTE, timeout=15000)
            expect(page.locator("#view")).not_to_contain_text(RESTRICTED_PENDING)
            expect(page.locator('#redaction-context a[href*="/api/sources/"]')).to_have_count(0)
            page.locator('[data-action="live-response-return"]').click()
            expect(page.locator('[data-response-id="P2"] > summary')).to_be_focused()
            assert page.evaluate("performance.timeOrigin") == origin
            assert "request=P2" in page.url
            assert api.get(f"/api/sources/{source['id']}/original", params={
                "case_id": case_id,
            }).status_code == 404
        assert reader.calls == reader_calls
        assert drafts.calls == draft_calls
