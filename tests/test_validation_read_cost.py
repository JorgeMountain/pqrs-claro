"""Reuse validation only while committed inputs remain identical, never across changes."""

import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pqrs_claro.config import Settings
from pqrs_claro.draft_service import DraftService, _InputsChanged
from pqrs_claro.intake_service import IntakeService
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.source_service import SourceService
from pqrs_claro.storage import CaseStore


@pytest.fixture
def validation(tmp_path):
    settings = Settings(data_dir=tmp_path, model="offline-test", initial_review_enabled=True)
    cases = CaseStore(tmp_path)
    cases.management = None
    case = cases.create("ficticio.pdf", b"%PDF-1.4 ficticio", case_id="fictitious")
    case = cases.update(case["id"], status="confirmed", identification={
        "subject": "Consulta ficticia", "requests": [{
            "id": "P1", "label": "1", "title": "Consulta", "description": "Información",
            "source_refs": [],
        }],
    })
    library = SourceLibrary(tmp_path, None)
    library.save_collection({"id": "archive", "name": "Archivo ficticio"})
    source = library.add("fuente.txt", b"Contenido de la fuente ficticia.",
                         title="Fuente ficticia", category="institutional_norm",
                         origin="Prueba local")
    verification = {"value": "initial-verifications"}
    sources = SourceService(settings, cases, library, verifications=SimpleNamespace(
        fingerprint=lambda *_: verification["value"]))
    intake = IntakeService(settings, cases, library, sources)
    intake.save({"case_id": case["id"], "status": "approved", "revision": 0,
                 "report": None, "fingerprint": intake.fingerprint(case["id"], scope="legacy"),
                 "decisions": {"reviewed_by": "Gestor ficticio"}})
    _, snapshot, _, fingerprint = sources.inputs(case["id"])
    sources.library.save_run({
        "id": "test-run", "case_id": case["id"], "status": "ready", "stale": False,
        "fingerprint": fingerprint, "source_snapshot": snapshot,
        "results": [{"request_id": "P1", "status": "references_found"}],
    })
    drafts = DraftService(settings, cases, library, sources)
    drafts.initial_review = intake
    yield SimpleNamespace(settings=settings, cases=cases, case=case, library=library,
                          source=source, sources=sources, intake=intake, drafts=drafts,
                          verification=verification)
    intake.close()
    drafts.close()
    sources.close()


def count_catalog(monkeypatch, env):
    reads = []
    original = env.library.scoped

    def scoped(*args, **kwargs):
        reads.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(env.library, "scoped", scoped)
    return reads


def test_shared_read_retains_exact_fingerprint_without_reanalysis_plan(validation, monkeypatch):
    env = validation
    case_id = env.case["id"]
    previous_run = env.sources.get(case_id, compact=True)
    expected_fingerprint = env.drafts._fingerprint(env.case, previous_run)
    expected_allowed = env.intake.get(case_id)["can_prepare"]
    assert expected_allowed
    reads = count_catalog(monkeypatch, env)
    monkeypatch.setattr(env.intake, "analysis_plan", lambda *_a, **_k: pytest.fail(
        "Downstream validation must not calculate a reanalysis plan"))
    first = env.drafts._current(case_id)
    second = env.drafts._current(case_id)
    assert first == second == (env.case, previous_run, expected_fingerprint, expected_allowed)
    assert len(reads) == 1  # Both calls check durable revisions; unchanged inputs reuse validation.


def test_intake_view_uses_one_catalog_and_keeps_full_next_analysis(validation, monkeypatch):
    env = validation
    case_id = env.case["id"]
    expected_plan = env.intake.analysis_plan(case_id, env.intake.saved(case_id))[1]
    expected_fingerprint = env.intake.fingerprint(case_id)
    reads = count_catalog(monkeypatch, env)
    row = env.intake.get(case_id)
    assert row["can_prepare"] and not row["stale"]
    assert row["fingerprint"] == expected_fingerprint
    assert row["next_analysis"] == {
        "pending": expected_plan["pending"], "reused": list(expected_plan["reused"]),
        "reason": expected_plan["reason"],
    }
    assert len(reads) == 1


@pytest.mark.parametrize("change", ["source_metadata", "scope", "identification",
                                  "verification", "intake_decision"])
def test_next_read_still_invalidates_every_changed_validation_input(validation, change):
    env = validation
    case_id = env.case["id"]
    assert env.drafts._current(case_id)[3]
    if change == "source_metadata":
        env.library.review(env.source["id"], reviewed_by="Gestor ficticio",
                           review_note="Vigencia comprobada en prueba", validity="current")
    elif change == "scope":
        env.library.link_collections(case_id, ["archive"])
    elif change == "identification":
        identification = deepcopy(env.case["identification"])
        identification["requests"][0]["description"] = "Otra información"
        env.cases.update(case_id, identification=identification)
    elif change == "verification":
        env.verification["value"] = "verification-revoked"
    else:
        env.intake.save(env.intake.saved(case_id), status="needs_review")
    assert env.drafts._current(case_id)[3] is False


def test_another_case_source_does_not_change_this_cases_scope(validation):
    env = validation
    before = env.drafts._current(env.case["id"])
    env.library.add("privado.txt", b"Fuente ficticia de otro expediente.",
                    title="Privada", category="case_evidence", origin="Prueba local",
                    case_id="another-fictitious-case")
    assert env.drafts._current(env.case["id"]) == before


def test_external_catalog_edit_invalidates_cached_validation(validation, monkeypatch):
    env = validation
    reads = count_catalog(monkeypatch, env)
    assert env.drafts._current(env.case["id"])[3]
    revision = env.library.catalog_revision()
    # Simulate an import/OCR process using its own SQLite connection.
    with sqlite3.connect(env.library.db) as conn:
        body = json.loads(conn.execute("SELECT body FROM sources WHERE id=?",
                                       (env.source["id"],)).fetchone()[0])
        body["extraction_revision"] = 2
        conn.execute("UPDATE sources SET body=? WHERE id=?",
                     (json.dumps(body), env.source["id"]))
    assert env.library.catalog_revision() > revision
    assert env.drafts._current(env.case["id"])[3] is False
    assert len(reads) == 2


def test_source_run_update_invalidates_cached_validation(validation):
    env = validation
    assert env.drafts._current(env.case["id"])[3]
    run = env.library.latest_run(env.case["id"], compact=True)
    env.library.save_run_progress({**run, "status": "running"})
    assert env.drafts._current(env.case["id"])[3] is False


def test_cached_metadata_never_skips_original_integrity(validation):
    env = validation
    fingerprint = env.drafts._current(env.case["id"])[2]
    finding = {"supports": [{"source_id": env.source["id"]}]}
    env.drafts._ensure_current(env.case["id"], fingerprint, finding)
    env.library.original(env.source["id"]).write_bytes(b"Changed outside the application")
    with pytest.raises(_InputsChanged):
        env.drafts._ensure_current(env.case["id"], fingerprint, finding)


def test_guard_does_not_compute_a_reanalysis_plan(validation, monkeypatch):
    env = validation
    monkeypatch.setattr(env.intake, "analysis_plan", lambda *_a, **_k: pytest.fail(
        "An eligibility guard must not plan another analysis"))
    env.intake.assert_allowed(env.case["id"])


def test_cached_validation_is_not_mutable_by_its_caller(validation):
    env = validation
    expected = env.drafts._current(env.case["id"])
    cached = env.drafts._current(env.case["id"])
    cached[1]["results"].clear()
    cached[0]["identification"]["requests"].clear()
    assert env.drafts._current(env.case["id"]) == expected
