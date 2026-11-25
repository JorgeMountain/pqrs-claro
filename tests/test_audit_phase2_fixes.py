"""Regression tests for Phase 2 audit fixes (clients, locks, SQLite, uploads, pool, config)."""

from __future__ import annotations

import sqlite3
import threading
from io import BytesIO
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pqrs_claro import config
from pqrs_claro.app import create_app
from pqrs_claro.draft_engine import OpenAIDraftEngine
from pqrs_claro.extraction import OpenAIOCR, PDFExtractor
from pqrs_claro.identification import OpenAIIdentifier
from pqrs_claro.image_ocr import MAX_IMAGE_PIXELS, normalized_image_png, validate_image
from pqrs_claro.intake_engine import OpenAIIntakeEngine
from pqrs_claro.models import DomainError
from pqrs_claro.performance_metrics import _save, metrics_path
from pqrs_claro.pool_integration import OpenAIPoolIntegration, apply_contributions
from pqrs_claro.pool_routing import OpenAIPoolRouting, suggest_responsibles
from pqrs_claro.response_proposal_engine import OpenAIResponseProposalEngine
from pqrs_claro.review_engine import OpenAIReviewEngine
from pqrs_claro.source_assessment import OpenAISourceAssessor
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.source_verifications import SourceVerificationStore
from pqrs_claro.storage import CaseStore


def test_all_openai_engines_implement_close():
    engines = [
        OpenAIOCR("test-not-real", "test-model"),
        OpenAIIdentifier("test-not-real", "test-model"),
        OpenAISourceAssessor("test-not-real", "test-model"),
        OpenAIDraftEngine("test-not-real", "test-model"),
        OpenAIReviewEngine("test-not-real", "test-model"),
        OpenAIResponseProposalEngine("test-not-real", "test-model"),
        OpenAIIntakeEngine(config.Settings(api_key="test-not-real")),
        OpenAIPoolIntegration("test-not-real", "test-model"),
        OpenAIPoolRouting("test-not-real", "test-model"),
    ]
    for engine in engines:
        assert callable(getattr(engine, "close", None))
        engine.close()


def test_source_library_add_releases_lock_during_extraction(tmp_path, monkeypatch):
    import pqrs_claro.source_library as sl

    lock_free_during_extract = []
    real_read = sl.read_source

    def probing_read(path, pdf_extractor):
        acquired = []

        def probe():
            got = library.lock.acquire(blocking=False)
            acquired.append(got)
            if got:
                library.lock.release()

        t = threading.Thread(target=probe)
        t.start()
        t.join(5)
        lock_free_during_extract.extend(acquired)
        return real_read(path, pdf_extractor)

    monkeypatch.setattr(sl, "read_source", probing_read)
    library = SourceLibrary(tmp_path / "data", PDFExtractor())
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50, 80), "Reglamento de prueba.")
        data = pdf.tobytes()
    added = library.add(
        "reglamento.pdf",
        data,
        title="Reglamento",
        category="institutional_norm",
        origin="Archivo de prueba",
    )
    assert added["page_count"] == 1
    assert lock_free_during_extract == [True]


def test_unreadable_source_original_downloads_as_attachment_and_inline_sets_sandbox(tmp_path):
    app = create_app(config.Settings(data_dir=tmp_path / "data", api_key=""))
    with TestClient(app) as client:
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((50, 80), "Contenido legible de petición.")
            valid_pdf = pdf.tobytes()
        case = app.state.store.create("peticion.pdf", valid_pdf)
        ok_case = client.get(f"/api/cases/{case['id']}/original")
        assert ok_case.status_code == 200
        assert ok_case.headers["content-security-policy"] == "default-src 'none'; sandbox"

        broken = app.state.library.add(
            "falso.pdf",
            b"<html><script>alert(1)</script></html>",
            title="Archivo ilegible",
            category="case_evidence",
            origin="Aporte de prueba",
            case_id=case["id"],
            retain_unreadable=True,
        )
        res = client.get(f"/api/sources/{broken['id']}/original", params={"case_id": case["id"]})
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/octet-stream"
        assert res.headers["content-disposition"].startswith("attachment;")


def test_image_ocr_rejects_oversized_resolution_and_downscales_cleanly(monkeypatch):
    monkeypatch.setattr("pqrs_claro.image_ocr.MAX_IMAGE_PIXELS", 500)
    with BytesIO() as buf, Image.new("RGB", (40, 40), "white") as img:
        img.save(buf, format="PNG")
        data = buf.getvalue()
    with pytest.raises(DomainError, match="resolución máxima"):
        validate_image(data, ".png")
    monkeypatch.setattr("pqrs_claro.image_ocr.MAX_IMAGE_PIXELS", MAX_IMAGE_PIXELS)
    png, meta = normalized_image_png(data, ".png", max_dimension=20)
    assert png.startswith(b"\x89PNG")
    assert meta["raster_size"] == [20, 20]


def test_pool_integration_rejects_trivial_single_char_quote_erasing_gaps():
    row = {
        "id": "P1",
        "answer": "Respuesta provisional.",
        "gaps": ["Falta fecha oficial del acta."],
        "gap": "Falta fecha oficial del acta.",
    }
    inputs = [
        {
            "kind": "note",
            "title": "Nota de secretaría",
            "text": "Se adjunta comentario preliminar sin confirmar la fecha del acta.",
        }
    ]
    engine = SimpleNamespace(
        integrate=lambda r, i: {
            "answer": "Texto reescrito por inyección.",
            "gaps": [],
            "citations": [{"input_id": "A1", "quote": "a"}],
        }
    )
    with pytest.raises(DomainError, match="fragmento verificable"):
        apply_contributions(engine, row, inputs)


def test_pool_routing_backfills_missing_task_indexes():
    detail = {
        "subject": "Consulta",
        "requests": [
            {"id": "P1", "title": "Primera", "text": "Texto 1", "gap": "Falta 1"},
            {"id": "P2", "title": "Segunda", "text": "Texto 2", "gap": "Falta 2"},
        ],
    }
    tasks = [{"request_id": "P1", "instruction": "A"}, {"request_id": "P2", "instruction": "B"}]
    engine = SimpleNamespace(
        suggest=lambda ctx, items: {
            "suggestions": [
                {
                    "index": 0,
                    "kind": "dependencia",
                    "responsible": "Admisiones",
                    "reason": "Corresponde al calendario.",
                }
            ]
        }
    )
    result = suggest_responsibles(engine, detail, tasks)
    assert len(result) == 2
    assert result[0]["responsible"] == "Admisiones"
    assert result[1]["index"] == 1
    assert result[1]["kind"] == "por_definir"
    assert result[1]["responsible"] == ""


def test_config_env_overrides_local_api_key_and_validates_port(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / ".env.local").write_text("OPENAI_API_KEY=local-key\n", encoding="utf-8")
    monkeypatch.setenv("PQRS_CLARO_KEY_FILE", str(tmp_path / "unused"))
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.delenv("PQRS_CLARO_PORT", raising=False)
    assert config.Settings.load().api_key == "env-key"

    monkeypatch.setenv("PQRS_CLARO_PORT", "not-a-port")
    with pytest.raises(ValueError, match="PQRS_CLARO_PORT"):
        config.Settings.load()

    monkeypatch.setenv("PQRS_CLARO_PORT", "70000")
    with pytest.raises(ValueError, match="1 y 65535"):
        config.Settings.load()


def test_sqlite_indexes_and_performance_wal_mode(tmp_path):
    store = CaseStore(tmp_path / "data")
    library = SourceLibrary(tmp_path / "data", PDFExtractor())
    verifications = SourceVerificationStore(tmp_path / "data", library, store)
    with library.connect() as conn:
        lib_indexes = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
    assert {"sources_case_scope", "source_reviews_id"} <= lib_indexes
    with verifications.connect() as conn:
        ver_indexes = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
    assert {"verification_case", "verification_events_target"} <= ver_indexes

    case = store.create("p.pdf", b"%PDF-1.4\n%stub\n")
    _save({"root": tmp_path / "data", "case_id": case["id"], "run_id": "r1", "stage": "t"},
          {"kind": "op", "name": "test"})
    db = sqlite3.connect(metrics_path(tmp_path / "data", case["id"]))
    try:
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        db.close()
    assert mode.lower() == "wal"
