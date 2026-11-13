"""Prueba opcional de Redacción con Chrome, una biblioteca temporal y motores ficticios."""

import socket
import threading
import time
from contextlib import contextmanager

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright
from test_draft_service_api import FakeDraftEngine, prepared_case
from test_initial_review import FakeIntake
from test_preparation import wait
from test_review_service_api import FakeReviewEngine

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.intake_models import POLICY_VERSION
from pqrs_claro.management import ManagementAction
from pqrs_claro.unified_app import create_unified_app

NEW_QUOTE = "Los requisitos institucionales ahora incluyen el registro COBALTO-72."
OLD_PENDING = "Confirmar el recibo del turno anterior."
NEW_PENDING = "Verificar la firma del registro COBALTO-72."


class LocalReader:
    def assess(self, request, candidates):
        source = next(item for item in candidates if item["title"] == "Norma ficticia")
        pending = NEW_PENDING if source["quote"] == NEW_QUOTE else OLD_PENDING
        return dict(
            request_id=request["id"], status="references_found", summary="Revisión ficticia",
            supports=[{**source, "role": "rule", "reason": "Consta en la norma ficticia."}],
            missing=[{"kind": "fact", "description": pending}], warnings=[],
        )


def seed(app):
    case, source = prepared_case(app, count=2, with_map=False)
    case_id = case["id"]
    app.state.management.change(case_id, ManagementAction(
        revision=0, action="claim", actor_id="gestor-1",
    ))
    pre = app.state.preanalysis
    pre.save(case_id, pre.saved(case_id), status="ready", approval={
        "actor_id": "gestor-1", "management_revision": 1, "at": case["created_at"],
    })
    intake = app.state.initial_review
    intake.save(
        intake.saved(case_id), status="approved",
        report=FakeIntake().assess({"identification": case["identification"]}),
        policy_version=POLICY_VERSION, analysis_scope="classification", reviewed_by="Gestor 1",
        document_decision={"route": "continue", "reviewed": True},
        decisions=[
            {"request_id": row["id"], "route": "continue", "reviewed": True,
             "petition_type": "information"}
            for row in case["identification"]["requests"]
        ],
    )
    return case, source


@contextmanager
def local_server(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started, "El servidor de prueba no arrancó"
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def test_resume_and_correct_open_petition(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    settings = Settings(data_dir=tmp_path, management_enabled=True, initial_review_enabled=True)
    app = create_unified_app(settings, source_assessor=LocalReader(),
                             draft_engine=FakeDraftEngine(), review_engine=FakeReviewEngine())
    case, source = seed(app)
    case_id = case["id"]
    with local_server(app) as url, httpx.Client(base_url=url, trust_env=False) as api:
        api.post(f"/api/cases/{case_id}/preparation", json={"version": case["version"]}
                 ).raise_for_status()
        assert wait(app, api, case_id)["status"] in {"ready", "waiting_review"}
        with sync_playwright() as pw, pw.chromium.launch(channel="chrome") as browser:
            page = browser.new_page()
            # Use the public empty snapshot even if a developer has a local legacy demo.
            page.route("**/data.json", lambda route: route.fulfill(
                path=ROOT / "src/pqrs_claro/static/demo/data.json", content_type="application/json",
            ))
            page.goto(f"{url}/?case={case_id}&step=2")
            page.locator('[data-action="live-sources"][data-index="1"]').first.click()
            context = page.locator("#redaction-context")
            pending = context.locator(".pending-task h4")
            quote = context.locator("blockquote")
            original = context.locator('a[href*="/api/sources/"][href*="/original"]')
            expect(pending).to_have_text(OLD_PENDING)
            old_quote = quote.inner_text()
            assert old_quote and old_quote != NEW_QUOTE
            with page.expect_response(f"**/api/cases/{case_id}/review/requests/P2/preview") as seen:
                page.reload()
            assert seen.value.ok and seen.value.json()["request_id"] == "P2"
            expect(quote).to_have_text(old_quote)
            expect(pending).to_have_text(OLD_PENDING)
            assert source["id"] in original.get_attribute("href")
            document_origin = page.evaluate("performance.timeOrigin")

            fields = {key: source[key] for key in ("document_id", "title", "category", "origin")}
            corrected = api.post("/api/sources", data=fields, files={
                "file": ("norma-v2.txt", NEW_QUOTE.encode(), "text/plain"),
            })
            corrected.raise_for_status()
            notice = page.locator('[data-redaction-correction="waiting"]')
            expect(notice).to_contain_text("Se corrigió un documento", timeout=15000)
            expect(quote).to_have_count(0)
            expect(pending).to_have_count(0)
            expect(original).to_have_count(0)
            expect(page.locator("#view")).not_to_contain_text(old_quote)
            expect(page.locator("#view")).not_to_contain_text(OLD_PENDING)
            page.get_by_role("button", name="Recalcular preparación").click()
            expect(page.locator('[data-redaction-correction="updated"]')).to_be_visible(
                timeout=30000,
            )
            expect(quote).to_have_text(NEW_QUOTE)
            expect(pending).to_have_text(NEW_PENDING)
            href = original.get_attribute("href")
            assert corrected.json()["id"] in href
            original_bytes = api.get(href)
            original_bytes.raise_for_status()
            assert original_bytes.content.decode() == NEW_QUOTE
            assert page.evaluate("performance.timeOrigin") == document_origin
            assert "request=P2" in page.url
