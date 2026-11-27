"""Check the administrator's four-stage review and sequential pool in Chromium."""

import re
import socket
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

import httpx
import pymupdf
import uvicorn
from docx import Document
from playwright.sync_api import expect, sync_playwright
from test_draft_service_api import FakeDraftEngine
from test_gmail import GoogleDouble, MemoryVault, connect, email_bytes
from test_initial_review import FakeIntake
from test_preanalysis import FakePreanalysis
from test_review_service_api import FakeReviewEngine
from test_source_service_api import (
    FakeSourceAssessor,
    TwoRequestsIdentifier,
    pdf_bytes,  # noqa: F401
    upload_source,
)

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.gmail_auth import GmailAuth
from pqrs_claro.unified_app import create_unified_app

GUIDE_REQUIREMENT = "El comité define requisitos de prácticas y registra las decisiones en el acta."


class Integrator:
    def integrate(self, request, inputs):
        item = inputs[-1]
        quote = {"input_id": item["id"], "quote": item["text"]}
        return {"answer": item["text"], "gaps": [],
                "citations": [dict(quote, gap_id=g["id"]) for g in request["open_gaps"]] or [quote]}


class CountingIdentifier(TwoRequestsIdentifier):
    def __init__(self):
        self.calls = 0

    def identify(self, pages):
        self.calls += 1
        return super().identify(pages)


class PracticeSources(FakeSourceAssessor):
    def assess(self, request, candidates):
        result = super().assess(request, candidates)
        if request["id"] == "P2":
            result.update(
                status="needs_evidence", supports=[], summary="El acta no está adjunta.",
                missing=[{"kind": "document", "description": "Adjuntar el acta solicitada."}],
            )
        else:
            result["supports"] = [
                {**candidate, "role": "rule", "reason": "Requisito citado en la guía de prueba."}
                for candidate in candidates if "prácticas" in candidate["quote"]
            ]
        return result


def upload_practice_guide(api):
    with pymupdf.open() as guide:
        guide.new_page().insert_text((52, 80), "Portada de la normativa institucional de prueba.")
        rule_page = guide.new_page()
        rule_page.insert_text((52, 270), GUIDE_REQUIREMENT)
        guide.new_page().insert_text(
            (52, 80), "Para inscribir prácticas se requiere una matrícula vigente."
        )
        api.post("/api/sources", data={
            "title": "Requisitos y acta del comité de prácticas",
            "category": "institutional_norm",
            "origin": "Guía institucional ficticia para la prueba del visor",
        }, files={"file": ("guia.pdf", guide.tobytes(), "application/pdf")}).raise_for_status()


def wait_preanalysis(page):
    expect(page.locator(".preanalysis")).to_be_visible(timeout=15000)
    expect(page.locator("[data-pre-confirm]")).to_be_enabled(timeout=15000)
    return parse_qs(urlparse(page.url).query)["case"][0]


def open_stage(page, stage):
    tabs = page.locator("nav.fiaga-analysis-tabs")
    if not tabs.is_visible():
        page.locator("nav.fiaga-phase-route [data-phase=analysis] a").click()
    target = tabs.locator(f'a[href$="#{stage}"]')
    expect(target).to_be_visible()
    target.click()
    return page.locator(".exp-content")


def check_case_navigation(page, phase, selected_tab=None):
    route = page.locator(".fiaga-route-main nav.fiaga-phase-route")
    side = page.locator("aside.fiaga-side-route nav.fiaga-side-nav")
    labels = [
        "Recepción", "Análisis y borrador", "Revisión de faltantes",
        "Trámites e integración", "Revisión final",
    ]
    expect(route).to_be_visible()
    expect(side).to_have_count(1)
    for nav, name in ((route, ".fiaga-phase-name"), (side, ".fiaga-side-name")):
        expect(nav.locator("[data-phase] " + name)).to_have_text(labels)
        expect(nav.locator(f"[data-phase={phase}].is-current")).to_have_count(1)
    expect(side.locator(".fiaga-side-dot")).to_have_count(5)
    badge = page.locator(".fiaga-case-heading .fiaga-phase-badge")
    expect(badge).to_contain_text(
        route.locator(f"[data-phase={phase}] .fiaga-phase-name").inner_text()
    )
    tabs = page.locator("nav.fiaga-analysis-tabs")
    if selected_tab is None:
        expect(tabs).to_be_hidden()
    else:
        for group in (tabs, side.locator("ol.fiaga-side-analysis")):
            expect(group.locator("[data-route-substep] .fiaga-step-circle")).to_have_count(4)
            expect(group.locator("[aria-current=step]")).to_have_attribute(
                "data-route-substep", str(selected_tab)
            )
        active = tabs.locator("[aria-current=step]")
        expect(active).to_be_visible()
        assert route.bounding_box()["y"] < tabs.bounding_box()["y"]


def check_redaction_sources(page, api, tmp_path):
    page.locator('[data-action="live-sources"][data-index="0"]').click()
    context = page.locator("#redaction-context")
    expect(
        context.locator(
            'input[type=file], [data-action="live-collections"], [data-action="live-pending"]'
        )
    ).to_have_count(0)
    documents = context.locator("[data-redaction-document]")
    guide = documents.get_by_role("option", name=re.compile("Requisitos y acta"))
    documents.select_option(guide.get_attribute("value"))
    passages = context.locator("[data-redaction-passage]")
    page_two = passages.get_by_role("option", name=re.compile(r"Página 2\b", re.I))
    passages.select_option(page_two.get_attribute("value"))
    expect(context.locator("blockquote")).to_contain_text("El comité define requisitos")
    image = context.locator(".source-passage-paper img")
    expect(image).to_have_attribute("src", re.compile(r"/pages/2\.png\?"))
    assert image.evaluate("img => img.decode().then(() => img.naturalWidth > 0)")
    mark = context.locator(".source-passage-mark").first
    expect(mark).to_be_visible()
    assert mark.evaluate("""e => {
        const mark = e.getBoundingClientRect();
        const image = e.closest('.source-passage-paper')
            .querySelector('img').getBoundingClientRect();
        const relativeTop = (mark.top - image.top) / image.height;
        return relativeTop > .28 && relativeTop < .34 && mark.width > 0 && mark.height > 0 &&
            mark.bottom <= image.bottom && mark.left >= image.left && mark.right <= image.right;
    }""")
    context.screenshot(path=str(tmp_path / "fuente-citada.png"))
    desktop = page.viewport_size
    page.set_viewport_size({"width": 390, "height": 844})
    expect(mark).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.set_viewport_size(desktop)
    source = context.locator('a[href*="/api/sources/"][href*="/original"]').first
    assert api.get(source.get_attribute("href")).is_success
    page_three = passages.get_by_role("option", name=re.compile(r"Página 3\b", re.I))
    passages.select_option(page_three.get_attribute("value"))
    expect(context.locator("blockquote")).to_contain_text("matrícula vigente")
    expect(image).to_have_attribute("src", re.compile(r"/pages/3\.png\?"))
    expect(mark).to_be_visible()
    unavailable = "**/source-versions/**/pages/2/view"
    page.route(unavailable, lambda route: route.fulfill(status=503, body=""))
    passages.select_option(page_two.get_attribute("value"))
    expect(context.locator("blockquote")).to_be_visible()
    expect(context.locator("blockquote")).to_contain_text("El comité define requisitos")
    expect(mark).to_have_count(0)
    page.unroute(unavailable)
    register = documents.get_by_role("option", name=re.compile("Registro de prácticas"))
    documents.select_option(register.get_attribute("value"))
    expect(context.locator(".source-passage-text mark")).to_contain_text("aprobación del comité")
    expect(context.locator(".source-passage-paper img")).to_have_count(0)
    revoked = "**/source-versions/**/pages/*/view"
    page.route(revoked, lambda route: route.fulfill(status=403, json={"detail": "Acceso retirado"}))
    documents.select_option(guide.get_attribute("value"))
    expect(context.locator("[data-passage-body]")).to_contain_text("ya no está disponible")
    expect(context.locator("blockquote")).to_be_hidden()
    expect(source).to_be_hidden()
    page.unroute(revoked)

    page.locator('[data-action="live-sources"][data-index="1"]').click()
    expect(context.locator(".fiaga-pool-pending")).to_contain_text("Adjuntar el acta solicitada")
    expect(context.locator("source-passage-viewer, input[type=file]")).to_have_count(0)
    context.locator('[data-action="live-response-return"]').click()
    expect(page.locator('[data-response-id="P2"] > summary')).to_be_focused()


def check_draft_page_fit(page):
    zoom = page.get_by_label("Zoom del documento")
    expect(zoom).to_have_value("page")
    sheets = page.locator(".oficio-sheet")
    expect(sheets.first).to_be_in_viewport(ratio=.99)
    assert sheets.first.evaluate("""sheet =>
        sheet.getBoundingClientRect().bottom <=
        sheet.closest('.draft-workspace').querySelector('.document-toolbar').getBoundingClientRect().top
    """)
    fits = """sheet => {
        const canvas = sheet.closest('.document-canvas');
        const view = canvas.getBoundingClientRect(), paper = sheet.getBoundingClientRect();
        const number = sheet.querySelector('.oficio-page-number').getBoundingClientRect();
        return paper.height > 0 && paper.top >= view.top && number.bottom <= view.bottom &&
            paper.bottom <= view.bottom && paper.left >= view.left && paper.right <= view.right;
    }"""
    assert sheets.first.evaluate(fits)
    if sheets.count() == 1:
        assert page.locator(".document-canvas").evaluate(
            "c => c.scrollHeight <= c.clientHeight + 1"
        )
        expect(page.get_by_role("button", name="Página siguiente del borrador")).to_have_count(0)

    # Exercise pagination without saving any content changes to this test case.
    subject = page.locator(".oficio-editable.kind-subject").first
    subject.fill("Revisión del oficio. " * 450)
    assert sheets.count() > 1
    previous = page.get_by_role("button", name="Página anterior del borrador")
    following = page.get_by_role("button", name="Página siguiente del borrador")
    for _ in range(sheets.count() - 1):
        if previous.is_disabled():
            break
        previous.click()
    expect(previous).to_be_disabled()
    following.click()
    expect(page.locator("[data-page-count]")).to_have_text(f"Página 2 de {sheets.count()}")
    assert sheets.nth(1).evaluate(fits)
    zoom.select_option("100")
    zoom.select_option("page")
    assert sheets.nth(1).evaluate(fits)
    page.get_by_role("button", name="Deshacer", exact=True).click()
    assert sheets.first.evaluate(fits)


@contextmanager
def serve(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(10)


def test_fiaga_through_the_user_interface(tmp_path, pdf_bytes, monkeypatch):  # noqa: F811
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        pdf[0].insert_text((50, 120), "Camila Restrepo\ncamila@example.invalid")
        pdf_bytes = pdf.tobytes()
    google = GoogleDouble()
    google.messages["m1"] = email_bytes(attachment=pdf_bytes)
    google.messages["m2"] = email_bytes(
        pdf=False, text="Solicito requisitos de prácticas y copia del acta del comité.",
    )
    gmail = GmailAuth(tmp_path, vault=MemoryVault(), transport=httpx.MockTransport(google))
    assessor, identifier = PracticeSources(), CountingIdentifier()
    writer = FakeDraftEngine(pending=True)
    app = create_unified_app(
        Settings(data_dir=tmp_path / "data", api_key="",
                 initial_review_enabled=True, management_enabled=True),
        extractor=PDFExtractor(), identifier=identifier,
        preanalysis_engine=FakePreanalysis(), source_assessor=assessor,
        intake_engine=FakeIntake(), draft_engine=writer, review_engine=FakeReviewEngine(),
        pool_integration_engine=Integrator(), gmail_auth=gmail,
    )
    with serve(app) as url, httpx.Client(base_url=url) as api, sync_playwright() as pw:
        upload_practice_guide(api)
        upload_source(
            api,
            title="Registro de prácticas",
            content="El registro de prácticas incluye la aprobación del comité.",
        ).raise_for_status()
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        page.route("**/data.json", lambda route: route.fulfill(
            path=ROOT / "src/pqrs_claro/static/demo/data.json", content_type="application/json",
        ))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.get_by_role("heading", name="Recepción de solicitudes")).to_be_visible()
        brandbar = page.locator(".fiaga-brandbar")
        expect(brandbar.locator("strong")).to_have_text("FIAGA")
        expect(brandbar.locator("time")).to_be_visible()
        expect(brandbar).to_have_css("background-color", "rgb(32, 63, 48)")
        intake = page.locator(".receipt-intake")
        recent = page.locator(".recent-cases")
        expect(intake.get_by_role("heading", name="Nueva solicitud")).to_be_visible()
        expect(intake.get_by_role("link", name="Recibir desde Gmail")).to_be_visible()
        expect(recent.get_by_role("heading", name="Solicitudes recientes")).to_be_visible()
        expect(recent.get_by_role("link", name="Ver expedientes")).to_be_visible()
        expect(recent).to_contain_text("Aquí aparecerán las solicitudes que recibas.")
        assert (
            intake.bounding_box()["x"] + intake.bounding_box()["width"]
            <= recent.bounding_box()["x"]
        )
        page.screenshot(path=str(tmp_path / "recepcion.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert (
            intake.bounding_box()["y"] + intake.bounding_box()["height"]
            <= recent.bounding_box()["y"]
        )
        page.screenshot(path=str(tmp_path / "recepcion-movil.png"), full_page=True)
        page.set_viewport_size({"width": 1366, "height": 900})
        page.route(
            "**/api/pool", lambda route: route.fulfill(status=503, json={"detail": "Prueba"})
        )
        page.reload()
        expect(recent).to_contain_text("La lista de solicitudes recientes no está disponible.")
        expect(intake.locator("input[type=file]")).to_be_enabled()
        expect(intake.get_by_role("link", name="Recibir desde Gmail")).to_be_visible()
        page.unroute("**/api/pool")
        page.reload()
        expect(recent).to_contain_text("Aquí aparecerán las solicitudes que recibas.")
        page.locator(".resources summary").click()
        page.get_by_role("link", name="Biblioteca de fuentes").click()
        expect(page.locator("#drawer")).to_be_visible()
        expect(page.locator("#library-list")).to_contain_text("Requisitos y acta")
        page.locator("#close").click()
        page.get_by_role("link", name="Volver al inicio de FIAGA", exact=True).click()
        page.get_by_role("link", name="Recibir desde Gmail").click()
        expect(page.locator("#gmail-content")).to_contain_text("Google")
        reception = page.locator(".tabs [data-page=recepcion]")
        expect(reception).to_have_attribute("aria-current", "page")
        connect(api)
        page.reload()
        page.get_by_role("button", name="Consultar correos").click()
        page.locator('[data-message="m1"]').click()
        expect(page.locator("#gmail-content")).to_contain_text("peticion.pdf")
        page.get_by_role("button", name=re.compile("^Recibir")).click()
        mail_id = wait_preanalysis(page)
        expect(brandbar).to_have_css("position", "sticky")
        mail = api.get("/api/cases/" + mail_id).json()
        assert mail["receipt"]["workflow"] == "fiaga" and mail["origin"]["kind"] == "gmail"
        checks = page.locator("[data-pre-checks]")
        expect(checks).to_contain_text("Camila Restrepo")
        expect(checks).to_contain_text("camila@example.invalid")
        headings = ("Datos del solicitante", "Contenido respetuoso", "Legibilidad e integridad")
        for heading in headings:
            expect(checks.get_by_role("heading", name=heading)).to_be_visible()
        expect(page.locator("[data-pre-start]")).to_be_disabled()
        page.reload()
        assert wait_preanalysis(page) == mail_id and identifier.calls == 0
        expect(page.locator("[data-pre-paper] img")).to_be_visible()
        page.get_by_role("button", name="Ampliar documento").click()
        expect(page.locator("[data-pre-zoom-value]")).to_have_text("125%")
        expect(page.locator("[data-pre-owner]")).to_contain_text("Administrador")
        page.locator("[data-pre-back]").first.click()
        page.goto(url)
        recent_case = recent.get_by_role("link").filter(has=page.locator(".case-main")).first
        expect(recent_case).to_have_attribute("href", f"/?case={mail_id}&view=revision-fiaga")
        pool_url = f"{url}/api/cases/{mail_id}/pool"
        held = []
        page.route(pool_url, lambda route: held.append(route))
        with page.expect_request(pool_url):
            recent_case.click(no_wait_after=True)
        expect(page.locator("#view .fiaga-review-opening")).to_be_visible()
        for selector in (".workspace-rail", ".prototype", "nav.steps"):
            expect(page.locator(selector)).to_be_hidden()
        held[0].fulfill(status=503, json={"detail": "Prueba de reconexión"})
        expect(page.locator("#view [role=alert]")).to_be_visible()
        expect(page.locator(".prototype")).to_be_hidden()
        page.unroute(pool_url)
        page.get_by_role("button", name="Reintentar", exact=True).click()
        assert wait_preanalysis(page) == mail_id
        page.goto(url)
        page.locator("[name=file]").set_input_files({
            "name": "texto.txt", "mimeType": "text/plain", "buffer": b"no es PDF",
        })
        expect(page.locator("[data-file-summary]")).to_contain_text("Elige un archivo PDF")
        expect(page.locator("[data-file-preview]")).to_be_hidden()
        expect(page.locator("#upload [type=submit]")).to_be_hidden()
        page.locator("[name=file]").set_input_files({
            "name": "practicas.pdf", "mimeType": "application/pdf", "buffer": pdf_bytes,
        })
        expect(page.locator("[data-file-preview]")).to_be_visible()
        assert page.locator("[data-file-preview]").get_attribute("href").startswith("blob:")
        page.locator("#upload details summary").click()
        page.locator("[name=subject]").fill("Prácticas y constancia")
        page.locator("[name=due_date]").fill("2000-01-01")
        submit = page.get_by_role("button", name="Recibir e iniciar preanálisis")
        submit.click()
        expect(page.locator("#feedback")).to_contain_text("La fecha límite no puede ser anterior")
        expect(submit).to_be_enabled()
        assert (
            page.locator("[name=file]").evaluate("input => input.files[0].name")
            == "practicas.pdf"
        )
        page.locator("[name=due_date]").fill("")
        pool_reads = []
        page.on(
            "request",
            lambda req: pool_reads.append(req.url) if req.url.endswith("/pool") else None,
        )
        # Keep the local test engine busy until the real navigation reports progress.
        release = threading.Event()
        assess = app.state.preanalysis.engine.assess

        def await_release(pages):
            assert release.wait(25)
            return assess(pages)

        with monkeypatch.context() as patch:
            patch.setattr(app.state.preanalysis.engine, "assess", await_release)
            try:
                submit.click()
                pre_step = page.locator('nav.fiaga-analysis-tabs [data-route-substep="0"]')
                side_pre = page.locator('ol.fiaga-side-analysis [data-route-substep="0"]')
                expect(pre_step).to_have_attribute("data-state", "working", timeout=15000)
                check_case_navigation(page, "analysis", 0)
                expand_stages = page.locator("summary.fiaga-side-stages-toggle")
                expand_stages.click()
                has_animation = "e => e.getAnimations({subtree:true}).length > 0"
                for step in (pre_step, side_pre):
                    expect(step).to_have_attribute("data-state", "working")
                    circle = step.locator(".fiaga-step-circle")
                    expect(circle).to_be_visible()
                    assert circle.evaluate(has_animation)
                page.emulate_media(reduced_motion="reduce")
                assert not pre_step.locator(".fiaga-step-circle").evaluate(has_animation)
                expect(pre_step).to_have_accessible_name(re.compile("Preanálisis.*Verificando"))
                page.emulate_media(reduced_motion="no-preference")
                page.screenshot(path=str(tmp_path / "preanalisis-en-curso.png"))
                expand_stages.click()
            finally:
                release.set()
        cid = wait_preanalysis(page)
        expect(pre_step).not_to_have_attribute("data-state", "working")
        expect(pre_step.locator(".fiaga-step-circle")).to_be_visible()
        assert not pre_step.locator(".fiaga-step-circle").evaluate(has_animation)
        assert pool_reads.count(f"{url}/api/cases/{cid}/pool") <= 1
        path = "/api/cases/" + cid
        pool = api.get(path + "/pool").json()
        assert pool["stage"] == "admin_review" and not pool["draft"]
        assert identifier.calls == 0 and not assessor.calls and not writer.calls
        rejected = api.post(path + "/pool/import-review", json={
            "actor_id": "admin", "revision": pool["revision"],
        })
        assert rejected.status_code == 409
        current = api.get(path).json()
        previous = api.get(path + "/preanalysis").json()
        premature = dict(actor_id="gestor-1", revision=previous["revision"],
                         management_revision=current["management"]["revision"], confirmed=True,
                         acknowledged=[], notes={})
        assert api.post(path + "/preanalysis/start", json=premature,
                        headers={"X-Fiaga-Actor": "gestor-1"}).status_code in (403, 409)
        assert identifier.calls == 0
        page.locator("[data-pre-confirm]").check()
        page.locator("[data-pre-start]").click()
        confirm_identification = page.locator('[data-action="live-initial-confirm"]')
        expect(page.locator("#identified-1")).to_be_visible(timeout=20000)
        expect(page.locator("#initial-decision-form")).to_be_visible(timeout=20000)
        check_case_navigation(page, "analysis", 1)
        assert identifier.calls == 1 and not assessor.calls and not writer.calls
        page.locator('#identified-0 [data-action="original"]').click()
        page.locator(".original-quote summary").click()
        expect(page.locator(".original-quote")).to_contain_text("Solicito requisitos de practicas")
        page.reload()
        expect(page.locator("#identified-1")).to_contain_text("Acta del comité", timeout=15000)
        first_petition = page.locator("#identified-0")
        first_petition.locator(".expediente-corrections > summary").click()
        first_petition.locator('[data-action="live-correct"]').click()
        page.locator("#live-title").fill("Requisitos de prácticas revisados")
        page.locator('#live-correction [type="submit"]').click()
        expect(first_petition).to_contain_text("Requisitos de prácticas revisados")
        page.locator('[name="type-1"]').select_option("documents")
        expect(confirm_identification).to_be_disabled()
        page.locator('[name="reviewed-all"]').check()
        expect(confirm_identification).to_be_enabled()
        assert not assessor.calls and not writer.calls
        confirm_identification.click()
        reading = page.locator('[data-action="live-confirm-responses"]')
        expect(page.locator(".redaction-workspace")).to_be_visible(timeout=20000)
        expect(reading).to_be_enabled(timeout=30000)
        check_case_navigation(page, "analysis", 2)
        side_nav = page.locator("nav.fiaga-side-nav")
        toggle = page.locator("summary.fiaga-side-toggle")
        expect(side_nav).to_be_visible()
        assert (
            side_nav.bounding_box()["x"]
            < page.locator("nav.fiaga-phase-route").bounding_box()["x"]
        )
        toggle.focus()
        toggle.press("Enter")
        expect(side_nav).to_be_hidden()
        check_case_navigation(page, "analysis", 2)
        page.reload()
        expect(reading).to_be_enabled(timeout=20000)
        expect(side_nav).to_be_hidden()
        toggle.press("Enter")
        expect(side_nav).to_be_visible()
        if not side_nav.locator("ol.fiaga-side-analysis").is_visible():
            side_nav.locator("summary.fiaga-side-stages-toggle").click()
        side_nav.locator('[data-route-substep="1"]').click()
        check_case_navigation(page, "analysis", 1)
        page.locator('nav.fiaga-analysis-tabs [data-route-substep="2"]').click()
        check_case_navigation(page, "analysis", 2)
        page.evaluate("scrollTo({top:0, behavior:'instant'})")
        page.screenshot(path=str(tmp_path / "ruta-redaccion.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        expect(side_nav).to_be_hidden()
        toggle.click()
        expect(side_nav).to_be_visible()
        check_case_navigation(page, "analysis", 2)
        toggle.click()
        expect(side_nav).to_be_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "ruta-redaccion-movil.png"))
        page.set_viewport_size({"width": 1366, "height": 900})
        continue_draft = page.locator('[data-action="live-continue-draft"]')
        expect(continue_draft).to_be_disabled()
        expect(page.locator('[data-response-id="P1"]')).to_contain_text(
            "Borrador ficticio atribuido al soporte.",
        )
        calls = (assessor.calls.copy(), writer.calls.copy())
        check_redaction_sources(page, api, tmp_path)
        assert (assessor.calls, writer.calls) == calls
        assert not api.get(path + "/review").json()["reading_confirmation"]["confirmed"]
        reading.click()
        expect(continue_draft).to_be_enabled(timeout=20000)
        reviewed = api.get(path + "/review").json()
        assert reviewed["reading_confirmation"]["confirmed"]
        missing = next(item for item in reviewed["requests"] if item["request_id"] == "P2")
        assert not missing["paragraphs"] and missing["pending"]
        continue_draft.click()
        transfer = page.locator('[data-action="fiaga-handoff"]')
        expect(transfer).to_be_visible(timeout=20000)
        expect(transfer).to_be_disabled()
        check_draft_page_fit(page)
        page.locator("[data-confirm-office]").check()
        expect(transfer).to_be_enabled()
        assert api.get(path + "/pool").json()["stage"] == "admin_review"
        transfer.click()
        plan = page.locator("#plan")
        expect(plan).to_be_visible(timeout=20000)
        check_case_navigation(page, "gaps")
        page.screenshot(path=str(tmp_path / "revision-inicial.png"), full_page=True)
        assert api.get(path + "/pool").json()["stage"] == "initial_review"
        panel = open_stage(page, "redaccion")
        expect(panel).to_contain_text("Confirmar el hecho del caso.")
        correction = panel.locator('form[data-review="P1"]')
        correction.locator("..").locator("summary").click()
        gap = "Verificar fecha de inscripción con Coordinación."
        correction.locator("[name=gaps]").fill(gap)
        correction.locator("[name=reason]").fill("Aclaración del dato pendiente.")
        with page.expect_response(lambda res: res.url.endswith("/requests/P1/review")) as review:
            correction.get_by_role("button", name="Guardar corrección").click()
        assert review.value.ok
        page.reload()
        expect(panel).to_contain_text(gap)
        open_stage(page, "borrador")
        expect(panel).to_contain_text(gap)
        assert api.get(path + "/pool/document.docx").status_code == 409
        assert api.post(path + "/management", json={
            "actor_id": "gestor-1", "revision": 0, "action": "claim",
        }).status_code == 409
        assert api.get("/api/cases").json() == []
        page.locator("nav.fiaga-phase-route [data-phase=gaps] a").click()
        rows = plan.locator("fieldset")
        expect(rows).to_have_count(2)
        for i, name in enumerate(("Coordinación", "Secretaría")):
            rows.nth(i).locator("[name=department]").fill(name)
            rows.nth(i).locator("[name=manager_id]").select_option(f"gestor-{i + 1}")
        plan.locator("[data-plan-submit]").click()
        expect(page.locator(".turn-available")).to_have_count(1)
        expect(page.locator(".turn-waiting")).to_have_count(1)
        page.locator("#actor").select_option("gestor-2")
        expect(page.get_by_text("Turno reservado", exact=False)).to_be_visible()
        expect(page.locator("[data-command=claim]")).to_have_count(0)
        page.locator("#actor").select_option("gestor-1")
        page.get_by_role("link", name="Pool de trámites").click()
        page.get_by_role("link", name="Prácticas y constancia", exact=False).click()
        page.locator("[data-command=claim]").click()
        expect(page.locator("#contribute")).to_be_visible()
        page.locator('.tabs [data-page="trabajo"]').click()
        expect(page.get_by_role("heading", name="Mi trabajo")).to_be_visible()
        expect(page.locator(".task-list")).to_contain_text("Prácticas y constancia")
        page.locator('.tabs [data-page="pool"]').click()
        expect(page.locator(".task-list")).to_have_count(0)
        page.locator('.tabs [data-page="trabajo"]').click()
        page.locator(".task-list a").click()
        page.locator("#contribute [name=note]").fill("La inscripción vence el 18 de junio.")
        page.locator("#contribute button").click()
        expect(page.locator(".turn-completed")).to_have_count(1)
        page.locator("#actor").select_option("gestor-2")
        page.locator("[data-command=claim]").click()
        page.locator("#contribute [name=files]").set_input_files({
            "name": "acta.txt", "mimeType": "text/plain", "buffer": b"Acta de practica 003.",
        })
        page.locator("#contribute button").click()
        expect(page.locator(".stage-final_review")).to_be_visible(timeout=20000)
        page.locator("#actor").select_option("admin")
        page.get_by_role("link", name="Revisar peticiones y fuentes").click()
        petition = page.locator('.petition-record[data-request="P1"]')
        history = petition.locator("details").filter(has=page.get_by_text(
            "Historial de cierres con respaldo", exact=True))
        history.locator("summary").click()
        expect(history.get_by_text(gap, exact=True)).to_be_visible()
        expect(history.locator("blockquote")).to_have_text("La inscripción vence el 18 de junio.")
        page.locator("nav.fiaga-phase-route [data-phase=final] a").click()
        page.locator(".return-panel > summary").click()
        row = plan.locator("fieldset").first
        row.locator("[name=request_id]").select_option("P2")
        row.locator("[name=instruction]").fill("Verificar la versión del acta.")
        row.locator("[name=department]").fill("Secretaría")
        plan.locator("[data-plan-submit]").click()
        expect(page.locator(".turn-available")).to_have_count(1)
        expect(page.locator(".turn-completed")).to_have_count(2)
        page.locator("#actor").select_option("gestor-2")
        page.locator("[data-command=claim]").click()
        page.locator("#contribute [name=note]").fill("Se verificó la versión 2 del acta 003.")
        page.locator("#contribute button").click()
        expect(page.locator(".stage-final_review")).to_be_visible(timeout=20000)
        page.locator("#actor").select_option("admin")
        page.get_by_role("button", name="Aprobar respuesta final").click()
        expect(page.get_by_role("link", name="Descargar Word")).to_be_visible()
        expect(brandbar).to_be_visible()
        page.reload()
        with page.expect_download() as capture:
            page.get_by_role("link", name="Descargar Word").click()
        saved = api.get(path + "/pool").json()["draft"]
        output = Document(capture.value.path())
        assert "\n".join(p.text for p in output.paragraphs) == saved
        assert "18 de junio" in saved and "versión 2 del acta" in saved
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        check_case_navigation(page, "final")
        for index, stage in enumerate(("preanalisis", "peticiones", "redaccion", "borrador")):
            open_stage(page, stage)
            expect(panel).to_be_visible()
            check_case_navigation(page, "final", index)
            for nav in ("nav.fiaga-phase-route", "nav.fiaga-side-nav"):
                expect(page.locator(nav + " [data-phase=analysis].is-viewed")).to_have_count(1)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), stage
        page.locator('.tabs [data-page="recepcion"]').click()
        page.get_by_role("link", name="Recibir desde Gmail").click()
        page.get_by_role("button", name="Consultar correos").click()
        page.locator('[data-message="m2"]').click()
        expect(page.locator('[name="mode"]')).to_have_value("body")
        page.locator('[name="body_confirmed"]').check()
        page.get_by_role("button", name=re.compile("^Recibir")).click()
        body_id = wait_preanalysis(page)
        assert body_id not in (cid, mail_id)
        assert api.get("/api/cases/" + body_id).json()["origin"]["primary"] == "body"
        page.locator("[data-pre-confirm]").check()
        alert = page.locator('[data-pre-ack="requester"]')
        expect(alert).to_be_visible()
        expect(page.locator("[data-pre-start]")).to_be_disabled()
        alert.check()
        expect(page.locator("[data-pre-start]")).to_be_disabled()
        page.locator('[data-pre-note="requester"]').fill("Contacto pendiente de contrastar.")
        expect(page.locator("[data-pre-start]")).to_be_enabled()
        assert identifier.calls == 1

        page.locator(".resources summary").click()
        page.get_by_role("button", name="Añadir tramitador").click()
        page.get_by_label("Nombre del tramitador").fill("Tramitadora de cabecera")
        page.get_by_role("button", name="Guardar tramitador").click()
        expect(page.locator("#manager-dialog")).not_to_be_visible()
        profile = page.locator("#actor")
        manager = (
            profile.locator("option")
            .filter(has_text="Tramitadora de cabecera")
            .get_attribute("value")
        )
        with page.expect_event("dialog") as rejected:
            page.once("dialog", lambda dialog: dialog.dismiss())
            profile.select_option(manager)
        assert rejected.value.type == "beforeunload"
        expect(profile).to_have_value("admin")
        expect(page.locator('[data-pre-note="requester"]')).to_have_value(
            "Contacto pendiente de contrastar."
        )
        assert page.evaluate("sessionStorage.getItem('fiaga-profile')") in ("admin", None)
        page.once("dialog", lambda dialog: dialog.accept())
        profile.select_option(manager)
        expect(page.locator(".tabs [data-page=trabajo]")).to_be_visible()
        expect(profile).to_have_value(manager)
        assert parse_qs(urlparse(page.url).query) == {"expediente": [body_id]}
        assert api.get(f"/api/cases/{body_id}/pool").json()["stage"] == "admin_review"
        assert not errors
        browser.close()
