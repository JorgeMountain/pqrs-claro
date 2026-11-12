"""Prueba opcional en Chromium y un servidor local con datos temporales."""

import csv
import socket
import threading
import time

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright
from test_app import pdf_bytes  # noqa: F401
from test_preanalysis import FakePreanalysis

from pqrs_claro.config import Settings
from pqrs_claro.unified_app import create_unified_app


def test_work_and_report_from_inbox(tmp_path, pdf_bytes):  # noqa: F811
    settings = Settings(data_dir=tmp_path, initial_review_enabled=True, management_enabled=True)
    app = create_unified_app(settings, preanalysis_engine=FakePreanalysis())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            with httpx.Client(base_url=url) as api, sync_playwright() as pw:
                for ref in ("RAD-PRUEBA-A", "RAD-PRUEBA-B"):
                    response = api.post("/api/cases", files={"file": ("prueba.pdf", pdf_bytes)},
                                        data={"subject": "Solicitud ficticia", "reference": ref})
                    response.raise_for_status()
                    if ref.endswith("A"):
                        cid = response.json()["id"]
                        api.post(f"/api/cases/{cid}/management", json={
                            "revision": 0, "action": "claim", "actor_id": "gestor-1",
                        }).raise_for_status()

                browser = pw.chromium.launch(channel="chrome")
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                page.locator("[data-manager-toggle]").click()
                page.locator('[data-manager-id="gestor-1"]').click()
                page.locator(f'[data-management-action="preanalysis"][data-id="{cid}"]').click()
                expect(page.locator(".work-activity")).to_contain_text("Registro activo")
                page.get_by_role("button", name="Registrar trabajo externo").click()
                page.get_by_label("Duración en minutos").fill("3")
                page.get_by_label("Actividad realizada").fill("Llamada de la prueba")
                page.get_by_role("button", name="Guardar actividad").click()
                expect(page.locator(".work-activity-dialog")).not_to_be_visible()
                # Leave a measurable interval between server timestamps.
                time.sleep(1.2)
                with page.expect_response(lambda r: r.url.endswith("/work-session") and
                                          r.request.post_data_json["event"] == "stop"):
                    page.get_by_role("button", name="Tiempos de gestión").click()
                expect(page.locator(".work-activity")).not_to_be_visible()
                page.get_by_text("RAD-PRUEBA-A", exact=False).first.click()
                expect(page.locator(".times-results")).to_contain_text("Llamada de la prueba")
                row = api.get("/api/management-times", params={"manager_id": "gestor-1"}).json()
                active = row["cases"][0]["active_seconds"]
                assert active >= 1 and row["cases"][0]["external_seconds"] == 180
                page.get_by_label("Gestor", exact=True).select_option("gestor-1")
                expect(page.locator(".times-status")).to_contain_text("1 expediente")
                expect(page.locator(".times-results")).not_to_contain_text("RAD-PRUEBA-B")
                page.get_by_role("button", name="Por gestor").click()
                expect(page.get_by_role("table")).to_contain_text("Gestor 1")
                with page.expect_download() as capture:
                    page.get_by_role("link", name="Descargar CSV").click()
                download = capture.value
                assert download.suggested_filename == "tiempos-gestores.csv"
                with download.path().open(encoding="utf-8-sig", newline="") as handle:
                    exported = list(csv.DictReader(handle, delimiter=";"))
                assert len(exported) == 1
                assert int(exported[0]["Activo estimado (s)"]) == active
                assert int(exported[0]["Externo declarado (s)"]) == 180
                page.reload()
                expect(page.get_by_role("heading", name="Tiempos de gestión")).to_be_visible()
                for width in (320, 768, 1024, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    expect(page.get_by_role("table")).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
