"""Provisional drafts and per-request integration, using local documents and provider doubles."""

from copy import deepcopy
from io import BytesIO

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient
from test_draft_service_api import FakeDraftEngine
from test_preanalysis import CountingExtractor, FakePreanalysis
from test_source_service_api import FakeSourceAssessor, TwoRequestsIdentifier, upload_source

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.draft_engine import OpenAIDraftEngine
from pqrs_claro.models import DomainError
from pqrs_claro.pool_document import approved_document
from pqrs_claro.pool_drafts import PoolDrafts
from pqrs_claro.pool_integration import _model_inputs, apply_contributions


class Integration:
    def __init__(self):
        self.calls = []

    def integrate(self, request, inputs):
        self.calls.append((deepcopy(request), deepcopy(inputs)))
        item = next(i for i in inputs if i["kind"] == "attachment")
        return {"answer": "Según el acta, " + item["text"], "gaps": [],
                "citations": [{"input_id": item["id"], "quote": item["text"]}]}


@pytest.fixture()
def engine_and_case(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings, extractor=CountingExtractor(), identifier=TwoRequestsIdentifier(),
                     source_assessor=FakeSourceAssessor(),
                     draft_engine=FakeDraftEngine(pending=True))
    with TestClient(app) as client:
        with pymupdf.open() as doc:
            doc.new_page().insert_text((40, 80), "Informar los requisitos de practicas y remitir "
                                                "copia del acta del comite de practicas.")
            case = app.state.store.create("solicitud.pdf", doc.tobytes(),
                                          receipt={"reference": "PQRS-FICTICIA"})
        engine = PoolDrafts(settings, app.state.store, app.state.service, app.state.sources,
                           app.state.drafts, preanalysis_engine=FakePreanalysis(),
                           integration_engine=Integration())
        yield client, case, engine


def test_pdf_to_unapproved_answers_including_gaps_and_source_references(engine_and_case):
    client, case, engine = engine_and_case
    assert upload_source(client).status_code == 201
    initial = engine.initial(case["id"])
    assert initial["checks"]["requester"]["state"] == "attention"
    assert initial["checks"]["integrity"]["state"] == "pass"
    assert [r["id"] for r in initial["requests"]] == ["P1", "P2"]
    assert all(r["answer"] in initial["text"] and r["gaps"] and r["sources"][0]["quote"]
               and r["source_refs"][0]["page"] == 1 for r in initial["requests"])
    assert engine.cases.get(case["id"])["version"] == case["version"]
    assert not engine.cases.get(case["id"]).get("confirmed_at")
    before = engine.drafts.engine.calls.copy()
    assert engine.initial(case["id"]) == initial
    assert engine.identification.extractor.calls == 1
    assert engine.drafts.engine.calls == before


def test_no_library_still_returns_each_petition_with_a_gap(engine_and_case, monkeypatch):
    _, case, engine = engine_and_case
    draft = OpenAIDraftEngine("test-never-sent", "test")
    monkeypatch.setattr(draft, "_call", lambda *args: pytest.fail("Unexpected AI call"))
    engine.drafts.engine = draft
    try:
        initial = engine.initial(case["id"])
    finally:
        draft.client.close()
    assert all(not r["sources"] and not r["answer"] and r["gap"] for r in initial["requests"])
    assert not engine.sources.assessor.calls


def test_integration_preserves_other_answers_and_verifies_literal_file_contents(engine_and_case):
    _, case, engine = engine_and_case
    initial = engine.initial(case["id"])
    task = {"id": "task-2", "request_id": "P2", "department": "Archivo",
            "instruction": "Adjuntar el acta.", "contributions": [
                {"actor_id": "archivo-1", "note": "Se adjunta copia.", "files": [
                    {"id": "attachment-1", "filename": "acta.txt", "url": "/files/test",
                     "text": "el comité sesionó el 5 de marzo."}]}]}
    integrated = engine.integrate(case["id"], initial, [task])
    assert integrated["requests"][0] == initial["requests"][0]
    assert initial["requests"][1]["gaps"]
    row = integrated["requests"][1]
    assert not row["gaps"] and row["answer"] in integrated["text"]
    assert row["contribution_sources"][0]["id"] == "attachment-1"
    assert row["contribution_sources"][0]["quote"] == task["contributions"][0]["files"][0]["text"]
    assert [r["id"] for r, _ in engine.integration_engine.calls] == ["P2"]
    task["contributions"][0]["files"][0].update(id="attachment-2", text="el acta fue corregida.")
    correction = engine.integrate(case["id"], integrated, [task])
    assert "el acta fue corregida" in correction["text"]
    assert [s["id"] for s in correction["requests"][1]["contribution_sources"]] == [
        "attachment-1", "attachment-2"]
    assert "Prácticas y acta del comité" in correction["text"]
    assert "PQRS-FICTICIA" in correction["text"]
    docx = approved_document({"stage": "approved", "case_id": case["id"],
                              "draft": correction["text"]})
    downloaded = Document(BytesIO(docx.body))
    assert "\n".join(p.text for p in downloaded.paragraphs) == correction["text"]


def test_phantom_citation_does_not_modify_the_draft():
    class Bad:
        def integrate(self, request, inputs):
            return {"answer": "Documento firmado", "gaps": [],
                    "citations": [{"input_id": "A1", "quote": "firmado por el secretario"}]}

    row = {"answer": "", "gaps": ["Aportar la firma"]}
    previous = deepcopy(row)
    with pytest.raises(DomainError, match="cita"):
        apply_contributions(Bad(), row,
            [{"id": "file-id", "kind": "attachment", "text": "Borrador sin firma"}])
    assert row == previous


def test_unreadable_attachment_remains_pending():
    row = {"answer": "", "gaps": ["Aportar la firma"]}
    apply_contributions(None, row, [{"id": "id", "kind": "attachment",
                                    "title": "escaneo.pdf", "text": ""}])
    assert row["gaps"][0] == "Aportar la firma" and "escaneo.pdf" in row["gap"]


def test_long_attachment_selects_matching_passage_and_marks_partial_reading():
    phrase = "La fecha del acta es el 5 de marzo."
    long_text = ("Contenido ajeno al acta. " * 10000) + phrase
    row = {"text": "¿Cuál es la fecha?", "gaps": ["Verificar marzo"]}
    sources = {"A1": {"text": long_text, "instruction": "Aportar fecha", "kind": "attachment"}}
    result = _model_inputs(sources, row)[0]
    assert phrase in result["text"] and result["partial_reading"]
    assert len(result["text"]) <= 144_000


def test_multiline_crlf_note_and_wrapped_pdf_quotes_match_verbatim():
    from pqrs_claro.pool_integration import contribution_inputs

    task = {
        "id": "task-1",
        "department": "Decanatura",
        "instruction": "Confirmar respuesta.",
        "contributions": [
            {
                "actor_id": "gestor-1",
                "note": "Primera línea.\r\nSegunda línea.",
                "files": [
                    {
                        "id": "file-1",
                        "filename": "soporte.pdf",
                        "url": "/api/cases/c/pool/files/file-1",
                        "text": "El profesor respondió\ndirectamente   el 5 de marzo.",
                    }
                ],
                "created_at": "2026-11-20T00:00:00+00:00",
            }
        ],
    }
    inputs = contribution_inputs(task)
    assert inputs[0]["text"] == "Primera línea.\nSegunda línea."

    class NormalizedQuoter:
        def integrate(self, request, items):
            return {
                "answer": "El profesor respondió directamente el 5 de marzo.",
                "gaps": [],
                "citations": [
                    {"input_id": "A1", "quote": "Primera línea.\nSegunda línea."},
                    {
                        "input_id": "A2",
                        "quote": "El profesor respondió directamente el 5 de marzo.",
                    },
                ],
            }

    row = {"answer": "", "gaps": ["Confirmar respuesta."]}
    apply_contributions(NormalizedQuoter(), row, inputs)
    assert not row["gaps"]
    assert row["contribution_sources"][0]["quote"] == "Primera línea.\nSegunda línea."
    assert (
        row["contribution_sources"][1]["quote"]
        == "El profesor respondió\ndirectamente   el 5 de marzo."
    )
