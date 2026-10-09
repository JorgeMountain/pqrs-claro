from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pqrs_claro.intake_service import intake_router
from pqrs_claro.source_api import source_router


def test_compact_progress_preserves_decisions_errors_and_full_audit_response():
    initial = dict(status="needs_review", revision=7, stale=True, can_prepare=False,
                   report={"requests": [{"request_id": "P1", "checks": ["pending"]}]},
                   decisions={"document": {"route": "specialist"}},
                   next_analysis={"pending": ["P1"]},
                   error="Example error", scope={"catalog": ["large catalog"],
                   "readable_sources": 10000, "candidates_limited": True},
                   consulted_sources=["source"])
    sources = dict(status="running", stale=False, source_snapshot=["large snapshot"],
                   results=[{"request_id": "P1", "supports": [{"quote": "Exact quote"}]}],
                   completed_count=1, total_count=2, request_states={"P2": "searching"})
    original_initial, original_sources = deepcopy(initial), deepcopy(sources)
    app = FastAPI()
    app.include_router(intake_router(SimpleNamespace(get=lambda _: initial)))
    app.include_router(source_router(None, SimpleNamespace(get=lambda _: sources), None))
    with TestClient(app) as client:
        compact = client.get("/api/cases/example/initial-review?compact=true").json()
        assert compact == {**{k: v for k, v in initial.items() if k != "consulted_sources"},
                           "scope": {k: v for k, v in initial["scope"].items() if k != "catalog"}}
        assert client.get("/api/cases/example/sources?compact=true").json() == {
            k: v for k, v in sources.items() if k != "source_snapshot"}
        assert client.get("/api/cases/example/initial-review").json() == original_initial
        assert client.get("/api/cases/example/sources").json() == original_sources
    assert initial == original_initial and sources == original_sources
