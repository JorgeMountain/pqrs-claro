"""Sondeo acotado: el catálogo se conserva y la vigencia se valida al terminar."""

import json
import threading
from types import SimpleNamespace

import pytest

from pqrs_claro.preparation import PreparationService
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.source_service import SourceService
from pqrs_claro.storage import Conflict


def make_run(**changes):
    return {
        "id": "run-1", "case_id": "case-1", "status": "running",
        "results": [], "source_snapshot": [{"id": "source-1", "title": "Original"}],
        "source_count": 1, "completed_count": 0, "total_count": 2,
        "fingerprint": "fingerprint", "stale": False, **changes,
    }


def test_compact_progress_does_not_serialize_snapshot_and_preserves_full_run(tmp_path):
    library = SourceLibrary(tmp_path, None)
    run = make_run()
    original = run["source_snapshot"]
    library.save_run(run)
    with library.connect() as conn:
        saved = conn.execute("SELECT body FROM source_runs").fetchone()[0]
    # Deliberately non-serializable: no progress write may traverse this object.
    run.update(source_snapshot=object(), completed_count=1,
               results=[{"request_id": "P1", "status": "references_found"}])
    library.save_run_progress(run)
    compact = library.latest_run("case-1", compact=True)
    assert compact["completed_count"] == 1 and "source_snapshot" not in compact
    full = library.latest_run("case-1")
    assert full["source_snapshot"] == original
    assert full["results"] == compact["results"]
    with library.connect() as conn:
        assert conn.execute("SELECT body FROM source_runs").fetchone()[0] == saved
    run.update(source_snapshot=original, status="ready", completed_count=2)
    library.save_run(run)
    assert library.latest_run("case-1")["status"] == "ready"
    assert library.latest_run("case-1")["source_snapshot"] == original


def test_legacy_runs_recovery_and_purge_keep_compact_progress_consistent(tmp_path):
    library = SourceLibrary(tmp_path, None)
    run = make_run()
    with library.connect() as conn:
        conn.execute("INSERT INTO source_runs VALUES (?,?,?)",
                     (run["id"], run["case_id"], json.dumps(run)))
    assert library.latest_run("case-1", compact=True) == {
        key: value for key, value in run.items() if key != "source_snapshot"}
    run.update(completed_count=1, results=[{"request_id": "P1"}])
    library.save_run_progress(run)
    library.recover()
    recovered = library.latest_run("case-1")
    assert recovered["status"] == "error"
    assert recovered["results"] == run["results"]
    assert recovered["source_snapshot"] == run["source_snapshot"]
    assert library.latest_run("case-1", compact=True)["status"] == "error"
    with library.connect() as conn:
        conn.execute("DELETE FROM source_runs WHERE case_id=?", ("case-1",))
        assert conn.execute("SELECT COUNT(*) FROM source_run_progress").fetchone()[0] == 0
    library.save_run_progress(run)
    assert library.latest_run("case-1") is None


def test_progress_skips_catalog_while_running_but_checks_terminal_freshness(tmp_path, monkeypatch):
    library = SourceLibrary(tmp_path, None)
    case = {"id": "case-1", "identification": {"requests": []}, "request_count": 0}
    cases = SimpleNamespace(get=lambda _: dict(case))
    service = SourceService(SimpleNamespace(data_dir=tmp_path, model="test"), cases, library)
    try:
        _, sources, _, fingerprint = service.inputs("case-1")
        run = make_run(source_snapshot=sources, fingerprint=fingerprint, total_count=0)
        library.save_run(run)
        with monkeypatch.context() as patch:
            def forbidden(*_):
                raise AssertionError("El sondeo volvió a recorrer el catálogo")
            patch.setattr(library, "eligible", forbidden)
            result = service.progress("case-1")
        assert result["status"] == "running"
        assert result["freshness_checked"] is False and result["stale"] is None
        run.update(status="ready")
        library.save_run(run)
        original_latest = library.latest_run
        compact_reads = []

        def read_latest(case_id, *, compact=False):
            compact_reads.append(compact)
            return original_latest(case_id, compact=compact)

        with monkeypatch.context() as patch:
            patch.setattr(library, "latest_run", read_latest)
            assert service.progress("case-1")["status"] == "ready"
        assert compact_reads and all(compact_reads)
        case["identification"] = {"requests": [], "subject": "Corrección posterior"}
        result = service.progress("case-1")
        assert result["status"] == "stale" and result["stale"] is True
        assert "source_snapshot" not in result
    finally:
        service.close()


@pytest.mark.parametrize("changed", [False, True])
def test_preparation_wait_checks_version_before_returning_not_on_each_poll(changed):
    preparation = PreparationService.__new__(PreparationService)
    preparation.stop = threading.Event()
    preparation.initial_review = None
    checks, reads = [], []
    case = {"version": 2, "status": "confirmed"}
    preparation.cases = SimpleNamespace(get=lambda _: checks.append(True) or dict(case))

    def progress(_):
        reads.append(True)
        if len(reads) < 3:
            return {"status": "running"}
        if changed:
            case["version"] = 3
        return {"status": "ready"}

    service = SimpleNamespace(progress=progress, get=lambda _: pytest.fail("Usó lectura completa"))
    job = {"case_id": "case-1", "version": 2}
    if changed:
        with pytest.raises(Conflict):
            preparation.wait(service, job)
    else:
        assert preparation.wait(service, job)["status"] == "ready"
    assert len(checks) == 1 and len(reads) == 3
    preparation.stop.set()
    with pytest.raises(InterruptedError):
        preparation.wait(service, job)
    assert len(reads) == 3
