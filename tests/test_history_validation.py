"""El harness conserva procedencia, aislamiento y criterios sin llamadas externas."""

import importlib.util
import json
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from docx import Document

from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.storage import CaseStore

SPEC = importlib.util.spec_from_file_location(
    "validate_history", Path(__file__).resolve().parents[1] / "scripts" / "validate_history.py"
)
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


# Runtime-shaped sentinel for redaction tests; never a provider credential.
FAKE_PROVIDER_KEY = "sk-" + "SYNTHETIC_TEST_00000000"

@pytest.fixture
def reference_fixture(tmp_path):
    data = tmp_path / "live"
    library = SourceLibrary(data, PDFExtractor())
    library.save_collection({"id": "test-history", "title": "Historia ficticia para prueba"})
    text = "Solicito copia del acta del consejo y explicacion del periodo de la reunion."
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((30, 80), text, fontsize=9)
        original = document.tobytes()
    source = library.add(
        "peticion.pdf", original, title="Petición ficticia", category="institutional_norm",
        origin="Prueba aislada",
    )
    source.update(collection_id="test-history", category="historical_petition")
    with library.connect() as connection:
        connection.execute("UPDATE sources SET body=? WHERE id=?",
                           (json.dumps(source), source["id"]))
    library.add("global.txt", b"Informacion ficticia fuera de la coleccion.",
                title="Global excluida", category="national_norm", origin="Prueba")
    library.link_collections("live-case", ["test-history"])
    library.save_run({"id": "live-run", "case_id": "live-case", "status": "ready"})
    pages = library.get(source["id"])["pages"]
    reference = {
        "schema_version": 1, "collection_ids": ["test-history"], "cases": [{
            "id": "V01", "title": "Copia de acta", "description": text, "holdout": False,
            "request_source": {"source_id": source["id"], "page": 1, "line_start": 1,
                               "line_end": 1, "quote": pages[0]["text"]},
            "expected_source_groups": [{"id": "petition", "source_ids": [source["id"]],
                                        "essential": True}],
        }],
    }
    return library, reference, Settings(data_dir=data)


def test_prepare_snapshots_only_selected_collection_and_keeps_live_unchanged(
    tmp_path, reference_fixture
):
    live, reference, settings = reference_fixture
    reference_path = tmp_path / "reference.json"
    harness.write_json(reference_path, reference)
    output = tmp_path / "qa"
    manifest = harness.prepare(output, reference_path, settings)
    snapshot = harness.SnapshotLibrary(output / "data", live.root)
    assert len(snapshot.list()) == 1
    assert snapshot.linked_collections("live-case") == []
    assert snapshot.latest_run("live-case") is None
    assert len(live.list()) == 2
    assert live.linked_collections("live-case") == ["test-history"]
    assert live.latest_run("live-case")["id"] == "live-run"
    assert manifest["institutional_approval"] is False
    assert manifest["identification_tested"] is False
    assert not manifest["cases"][0]["derived_qa_pdf"]
    qa_case = CaseStore(output / "data").get(manifest["cases"][0]["case_id"])
    assert qa_case["mode"] == "validation"
    assert qa_case["status"] == "confirmed"
    assert CaseStore(output / "data").original(qa_case["id"]).read_bytes() == (
        live.original(reference["cases"][0]["request_source"]["source_id"]).read_bytes()
    )
    assert harness.prepare(output, reference_path, settings) == manifest
    with pytest.raises(ValueError, match="no incorpora"):
        snapshot.add("forbidden.txt", b"No escribir")


def test_prepare_rejects_reference_mutation_after_freezing(tmp_path, reference_fixture):
    _, reference, settings = reference_fixture
    path = tmp_path / "reference.json"
    harness.write_json(path, reference)
    harness.prepare(tmp_path / "qa", path, settings)
    reference["cases"][0]["description"] = "Otra solicitud"
    harness.write_json(path, reference)
    with pytest.raises(ValueError, match="referencia cambió"):
        harness.prepare(tmp_path / "qa", path, settings)


def test_tampered_citation_never_prepares_a_case(tmp_path, reference_fixture):
    _, reference, settings = reference_fixture
    reference["cases"][0]["request_source"]["quote"] = "Una frase inventada."
    path = tmp_path / "reference.json"
    harness.write_json(path, reference)
    with pytest.raises(ValueError, match="no coincide literalmente"):
        harness.prepare(tmp_path / "qa", path, settings)
    assert CaseStore(tmp_path / "qa" / "data").list() == []


def test_docx_reproduction_is_marked_and_keeps_real_origin(tmp_path, reference_fixture):
    live, reference, settings = reference_fixture
    document = Document()
    quote = "Indique cuál período corresponde a la reunión y remita el acta solicitada."
    document.add_paragraph(quote)
    buffer = BytesIO()
    document.save(buffer)
    source = live.add("respuesta.docx", buffer.getvalue(), title="Respuesta ficticia",
                      category="institutional_norm", origin="Prueba")
    source.update(collection_id="test-history", category="historical_response")
    with live.connect() as connection:
        connection.execute("UPDATE sources SET body=? WHERE id=?",
                           (json.dumps(source), source["id"]))
    sample = reference["cases"][0]
    sample["request_source"].update(source_id=source["id"], quote=quote,
                                    location_kind="section")
    path = tmp_path / "reference.json"
    harness.write_json(path, reference)
    manifest = harness.prepare(tmp_path / "qa", path, settings)
    assert manifest["cases"][0]["derived_qa_pdf"]
    cases = CaseStore(tmp_path / "qa" / "data")
    case = cases.get(manifest["cases"][0]["case_id"])
    assert case["validation_origin"]["quote"] == quote
    with pymupdf.open(cases.original(case["id"])) as pdf:
        visible = pdf[0].get_text().replace("\u00a0", " ")
        assert "COPIA DERIVADA QA" in visible
        assert quote in visible


def test_missing_warning_does_not_excuse_missed_existing_essential(reference_fixture):
    library, reference, _ = reference_fixture
    sample = reference["cases"][0]
    mapping = {"case_id": "qa", "status": "ready", "results": [{
        "request_id": "P1", "status": "no_matches", "supports": [],
        "missing": [{"kind": "document", "description": "Falta el acta"}],
    }]}
    result = harness.evaluate_result(sample, mapping, [], library, {"persisted": True})
    assert result["technical_passed"]
    assert not result["essential_retrieval_passed"]
    assert result["semantic_review"] == "pending"
    assert not result["institutional_approval"]


def test_changed_quote_fails_technical_check(reference_fixture):
    library, reference, _ = reference_fixture
    sample = reference["cases"][0]
    citation = {**sample["request_source"], "chunk_id": "source:1:1:1", "quote": "Inventada"}
    mapping = {"case_id": "qa", "status": "ready", "results": [{"supports": [citation]}]}
    result = harness.evaluate_result(sample, mapping, [citation], library, {"persisted": True})
    assert not result["technical_passed"]
    assert result["essential_retrieval_passed"]


def test_empty_essential_group_is_not_a_valid_expected_missing(reference_fixture):
    _, reference, _ = reference_fixture
    reference["cases"][0]["expected_source_groups"][0]["source_ids"] = []
    with pytest.raises(ValueError, match="fuentes concretas"):
        harness.validate_reference(reference)


def test_output_cannot_target_live_database():
    with pytest.raises(ValueError, match="subdirectorio de output"):
        harness.output_path(harness.ROOT / "data")


def test_attempt_archives_are_distinct_and_preserve_previous_files(tmp_path):
    source = {"sample_id": "V01", "marker": "previous result"}
    harness.write_json(tmp_path / "results" / "V01.json", source)
    first, second = tmp_path / "attempts" / "first", tmp_path / "attempts" / "second"
    harness.archive_sample(tmp_path, first, "V01", previous=True)
    changed = {"sample_id": "V01", "marker": "new result"}
    harness.write_json(tmp_path / "results" / "V01.json", changed)
    harness.archive_sample(tmp_path, second, "V01", previous=True)
    assert harness.read_json(first / "previous" / "results" / "V01.json") == source
    assert harness.read_json(second / "previous" / "results" / "V01.json") == changed
    assert harness.read_json(tmp_path / "results" / "V01.json") == changed


def test_execution_metadata_identifies_code_without_saving_key(reference_fixture):
    _, reference, settings = reference_fixture
    settings = replace(settings, api_key=FAKE_PROVIDER_KEY)
    first = harness.execution_info(settings, reference, "development", ["V01"])
    second = harness.execution_info(settings, reference, "development", ["V01"])
    assert first["attempt_id"] != second["attempt_id"]
    assert first["model"] == settings.model
    assert first["reference_sha256"] == harness.digest(reference)
    assert first["code_sha256"][str(Path("scripts") / "validate_history.py")]
    assert first["dependencies"]["langgraph"]
    assert FAKE_PROVIDER_KEY not in json.dumps(first)


def test_script_error_is_sanitized_and_next_sample_and_summary_are_saved(
    tmp_path, reference_fixture, monkeypatch
):
    _, reference, settings = reference_fixture
    second = deepcopy(reference["cases"][0])
    second["id"] = "V02"
    reference["cases"].append(second)
    reference_path = tmp_path / "reference.json"
    harness.write_json(reference_path, reference)
    output = tmp_path / "qa"
    harness.prepare(output, reference_path, settings)
    previous = {"marker": "pre-existing proof"}
    harness.write_json(output / "calls" / "V01.json", previous)
    harness.write_json(output / "results" / "V01.json", previous)
    started, closed = [], []

    class ServiceDouble:
        def __init__(self, *args, **kwargs):
            pass

        def start(self, case_id, version):
            started.append(case_id)
            if len(started) == 1:
                raise ValueError(f"Provider accidentally included {FAKE_PROVIDER_KEY}")
            return {"id": "run-two", "fingerprint": "test", "case_id": case_id,
                    "status": "ready", "results": []}

        def close(self):
            closed.append(True)

    monkeypatch.setattr(harness, "SourceService", ServiceDouble)
    monkeypatch.setattr(harness, "OpenAISourceAssessor",
                        lambda key, model: SimpleNamespace(model=model))
    monkeypatch.setattr(harness, "persistence_checks", lambda *args: {"checked": True})
    summary = harness.run(output, "development", replace(settings, api_key="test-only-key"))
    assert len(started) == 2
    assert closed == [True]
    assert summary["completed"] == 2
    failed = harness.read_json(output / "results" / "V01.json")
    assert failed["script_error_type"] == "ValueError"
    assert not failed["technical_passed"]
    assert not failed["essential_retrieval_passed"]
    assert harness.read_json(output / "results" / "V02.json")["technical_passed"]
    attempt = next((output / "attempts").iterdir())
    assert harness.read_json(attempt / "previous" / "calls" / "V01.json") == previous
    assert harness.read_json(attempt / "previous" / "results" / "V01.json") == previous
    assert harness.read_json(attempt / "execution.json")["status"] == "completed"
    assert harness.read_json(attempt / "execution.json")["technical_error_count"] == 1
    assert (output / "technical-summary.json").is_file()
    assert all(FAKE_PROVIDER_KEY not in path.read_text("utf-8")
               for path in output.rglob("*.json"))
