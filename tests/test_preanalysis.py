"""The owner, not reception/assignment or a URL, decides when identification starts."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pymupdf
import pytest
from fastapi.testclient import TestClient
from test_app import FakeIdentifier, upload, wait_ready

from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError, Page
from pqrs_claro.preanalysis_engine import materialize
from pqrs_claro.unified_app import create_unified_app


class FakePreanalysis:
    calls = 0

    def assess(self, pages):
        self.calls += 1
        # Only return data actually present in the test PDF.
        lines = pages[0].text.splitlines()
        name = next((i for i, text in enumerate(lines, 1) if "Camila Restrepo" in text), None)
        contact = next(
            (i for i, text in enumerate(lines, 1) if "camila@example.invalid" in text), None
        )
        return dict(
            requester=dict(
                state="pass" if name and contact else "attention",
                summary="Revisa nombre y contacto.",
                name="Camila Restrepo" if name else None,
                contact="camila@example.invalid" if contact else None,
                refs=[dict(page=1, line_start=i, line_end=i) for i in (name, contact) if i],
            ),
            respect=dict(state="pass", summary="Sin expresiones irrespetuosas.", refs=[]),
            integrity=dict(state="pass", summary="El archivo es legible.", refs=[]),
        )


class CountingExtractor(PDFExtractor):
    calls = 0

    def extract(self, path):
        self.calls += 1
        return super().extract(path)


def wait_checks(client, cid):
    for _ in range(200):
        record = client.get(f"/api/cases/{cid}/preanalysis").json()
        if record["status"] != "running":
            return record
        time.sleep(0.02)
    pytest.fail("Preanalysis did not finish")


def check(client, cid):
    response = client.post(f"/api/cases/{cid}/preanalysis/check", json={"actor_id": "gestor-1"})
    assert response.status_code == 200, response.text
    return wait_checks(client, cid)


def approval(record, revision=1):
    return dict(
        actor_id="gestor-1",
        revision=record["revision"],
        management_revision=revision,
        confirmed=True,
        acknowledged=["requester", "respect", "integrity"],
        notes={
            k: "Revisado en el original; se puede continuar."
            for k in ("requester", "respect", "integrity")
        },
    )


@pytest.fixture
def managed(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", api_key="", management_enabled=True)
    identifier, engine, extractor = FakeIdentifier(), FakePreanalysis(), CountingExtractor()
    app = create_unified_app(
        settings,
        identifier=identifier,
        extractor=extractor,
        source_extractor=PDFExtractor(),
        preanalysis_engine=engine,
    )
    with TestClient(app) as client:
        with pymupdf.open() as pdf:
            p = pdf.new_page()
            p.insert_text(
                (50, 80),
                "Documento de prueba\nSolicito copia del acta.\n"
                "Camila Restrepo\ncamila@example.invalid",
            )
            original = pdf.tobytes()
        cid = upload(client, original)["id"]
        yield app, client, cid, original, identifier, engine, extractor


def claim(client, cid):
    response = client.post(
        f"/api/cases/{cid}/management", json=dict(revision=0, actor_id="gestor-1", action="claim")
    )
    assert response.status_code == 200, response.text


def test_complete_flow_waits_for_explicit_confirmation_and_reuses_reading(managed):
    app, client, cid, original, identifier, engine, extractor = managed
    prefix = f"/api/cases/{cid}"
    assert identifier.calls == engine.calls == extractor.calls == 0
    assert (
        client.post(prefix + "/preanalysis/check", json={"actor_id": "gestor-1"}).status_code == 409
    )
    claim(client, cid)
    assert client.post(prefix + "/analyze").status_code == 409
    assert (
        client.post(
            prefix + "/management", json=dict(revision=1, actor_id="gestor-1", action="start")
        ).status_code
        == 409
    )
    record = check(client, cid)
    assert record["status"] == "ready" and record["page_count"] == 1
    assert all(c["state"] == "pass" for c in record["checks"].values())
    assert identifier.calls == 0 and engine.calls == extractor.calls == 1
    current = client.get(prefix).json()
    assert current["status"] == "uploaded" and current["identification"] is None
    assert current["pages"] == [] and current["management"]["started_at"] is None
    assert current["management"]["owner_name"] == "Gestor 1"
    assert check(client, cid)["revision"] == record["revision"]  # reopening never repeats checks
    meta = client.get(prefix + "/preanalysis/pages/1").json()
    assert meta["marks"] and meta["page_count"] == 1
    assert client.get(prefix + "/preanalysis/pages/2").status_code == 404
    assert (
        client.post(
            prefix + "/preanalysis/start", json={**approval(record), "confirmed": False}
        ).status_code
        == 422
    )
    assert identifier.calls == 0
    response = client.post(prefix + "/preanalysis/start", json=approval(record))
    assert response.status_code == 200, response.text
    case = wait_ready(client, cid)
    assert identifier.calls == 1 and extractor.calls == 1
    assert case["identification"] and case["status"] == "needs_review"
    assert client.get(prefix + "/original").content == original
    assert app.state.preanalysis.saved(cid)["approval"]["actor_id"] == "gestor-1"
    assert client.post(prefix + "/preanalysis/start", json=approval(record)).status_code == 409
    assert (
        client.post(prefix + "/preanalysis/check", json={"actor_id": "gestor-1"}).status_code == 409
    )
    assert identifier.calls == 1


def test_another_owner_stale_revision_and_changed_original_cannot_start(managed):
    app, client, cid, _, identifier, _, _ = managed
    claim(client, cid)
    record = check(client, cid)
    prefix = f"/api/cases/{cid}"
    for change in (
        {"actor_id": "gestor-2"},
        {"revision": record["revision"] + 1},
        {"management_revision": 0},
    ):
        assert (
            client.post(
                prefix + "/preanalysis/start", json={**approval(record), **change}
            ).status_code
            == 409
        )
    app.state.store.original(cid).write_bytes(b"%PDF-tampered")
    assert client.post(prefix + "/preanalysis/start", json=approval(record)).status_code == 422
    assert identifier.calls == 0
    assert app.state.management.get(cid)["started_at"] is None


def test_warnings_and_provider_failure_need_specific_human_review(managed):
    app, client, cid, _, identifier, _, _ = managed

    class Unavailable:
        def assess(self, pages):
            raise RuntimeError("Untrusted provider internals")

    app.state.preanalysis.engine = Unavailable()
    claim(client, cid)
    record = check(client, cid)
    assert record["status"] == "ready" and record["error"]
    assert all(c["state"] == "unverified" for c in record["checks"].values())
    assert "Untrusted" not in str(record)
    prefix = f"/api/cases/{cid}"
    for patch in ({"acknowledged": []}, {"notes": {}}, {"notes": {"requester": "x"}}):
        assert (
            client.post(
                prefix + "/preanalysis/start", json={**approval(record), **patch}
            ).status_code
            == 422
        )
    assert identifier.calls == 0
    assert client.post(prefix + "/preanalysis/start", json=approval(record)).status_code == 200
    wait_ready(client, cid)
    assert identifier.calls == 1


def test_ocr_failure_is_not_missing_data_and_cannot_be_bypassed(managed):
    app, client, cid, _, identifier, _, _ = managed

    class BrokenReading:
        def extract(self, path):
            raise DomainError("La página 1 necesita OCR.")

    app.state.service.extractor = BrokenReading()
    claim(client, cid)
    record = check(client, cid)
    assert record["status"] == "error" and record["page_count"] == 0
    assert all(c["state"] == "unverified" for c in record["checks"].values())
    assert (
        client.post(f"/api/cases/{cid}/preanalysis/start", json=approval(record)).status_code == 409
    )
    assert identifier.calls == 0


def test_double_click_starts_exactly_once(managed):
    _, client, cid, _, identifier, _, _ = managed
    claim(client, cid)
    record = check(client, cid)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _: client.post(
                    f"/api/cases/{cid}/preanalysis/start", json=approval(record)
                ).status_code,
                range(2),
            )
        )
    assert sorted(results) == [200, 409]
    wait_ready(client, cid)
    assert identifier.calls == 1


def test_saved_preanalysis_survives_restart_without_identification(managed):
    app, client, cid, _, identifier, engine, _ = managed
    claim(client, cid)
    record = check(client, cid)
    settings = replace(app.state.service.settings)
    reopened = create_unified_app(
        settings,
        identifier=FakeIdentifier(fail_if_called=True),
        extractor=PDFExtractor(),
        preanalysis_engine=engine,
    )
    with TestClient(reopened) as other:
        assert other.get(f"/api/cases/{cid}/preanalysis").json() == record
        assert check(other, cid)["revision"] == record["revision"]
        assert engine.calls == 1 and identifier.calls == 0


def test_positive_fields_and_language_alerts_require_real_evidence():
    pages = [
        Page(
            number=1,
            text="Petición de prueba\nSolicito información.",
            method="native",
            needs_review=False,
        )
    ]
    result = FakePreanalysis().assess(pages)
    result["respect"].update(state="attention", refs=[])
    with pytest.raises(DomainError, match="referencia"):
        materialize(result, pages)
    result["respect"]["state"] = "pass"
    result["requester"].update(
        name="Nombre inventado", refs=[dict(page=1, line_start=1, line_end=1)]
    )
    with pytest.raises(DomainError, match="no coinciden"):
        materialize(result, pages)


def test_save_notes_does_not_authorize_identification(managed):
    app, client, cid, _, identifier, _, _ = managed
    claim(client, cid)
    record = check(client, cid)
    url = f"/api/cases/{cid}/preanalysis/draft"
    body = dict(
        actor_id="gestor-1",
        revision=record["revision"],
        acknowledged=["requester"],
        notes={"requester": "Datos contrastados con el documento original."},
    )
    response = client.post(url, json=body)
    assert response.status_code == 200
    saved = response.json()
    assert saved["draft"]["notes"] == body["notes"] and saved["approval"] is None
    assert client.post(url, json=body).status_code == 409  # stale draft cannot overwrite
    assert client.post(f"/api/cases/{cid}/analyze").status_code == 409
    assert identifier.calls == 0
    assert app.state.management.get(cid)["started_at"] is None


def test_ocr_and_blank_pages_never_silently_pass_integrity():
    pages = [
        Page(
            number=1,
            text="Documento escaneado\nSolicito información.",
            method="ocr",
            needs_review=True,
        )
    ]
    checks = materialize(FakePreanalysis().assess(pages), pages)
    assert checks["integrity"]["state"] == "unverified"
    assert "1" in checks["integrity"]["summary"]
