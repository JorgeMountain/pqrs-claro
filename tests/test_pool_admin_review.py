"""Unit tests for PoolAdminReview handoff guards and conflict handling."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from pqrs_claro.pool_admin_review import PoolAdminReview
from pqrs_claro.pool_service import PoolService
from pqrs_claro.storage import CaseStore, Conflict


def _setup(tmp_path):
    store = CaseStore(tmp_path / "data")
    case = store.create("peticion.pdf", b"%PDF-1.4\n%stub\n", receipt={"workflow": "fiaga"})
    case = store.update(
        case["id"],
        status="confirmed",
        identification={
            "subject": "Consulta",
            "warnings": [],
            "requests": [
                {
                    "id": "P1",
                    "label": "1",
                    "title": "Primera",
                    "description": "Indicar fechas.",
                    "source_refs": [],
                }
            ],
        },
    )
    pool = PoolService(store)
    pool.enroll(case["id"])
    preanalysis = SimpleNamespace(
        lock=threading.RLock(),
        store=store,
        settings=SimpleNamespace(data_dir=tmp_path / "data"),
        saved=lambda cid: {"status": "ready"},
        require_approved=lambda cid: {
            "approval": {"actor_id": "admin"},
            "checks": {},
            "pages": [],
        },
    )
    return store, case, pool, preanalysis


def test_pool_admin_review_open_enforces_actor_stage_and_revision(tmp_path):
    store, case, pool, preanalysis = _setup(tmp_path)
    with store.connect() as db:
        db.execute(
            "UPDATE case_pool SET stage='initial_review', revision=2, "
            "body=json_set(body,'$.stage','initial_review','$.revision',2) WHERE case_id=?",
            (case["id"],),
        )
    office = SimpleNamespace()
    admin_review = PoolAdminReview(pool, preanalysis, office)

    with pytest.raises(Conflict):
        admin_review.open(case["id"], "gestor-1", 2)
    with pytest.raises(Conflict):
        admin_review.open(case["id"], "admin", 99)

    opened = admin_review.open(case["id"], "admin", 2)
    assert opened["stage"] == "admin_review"


def test_pool_admin_review_submit_rejects_revoked_scope_or_missing_findings_cleanly(
    tmp_path, monkeypatch
):
    store, case, pool, preanalysis = _setup(tmp_path)
    detail = pool.get(case["id"])
    assert detail["stage"] == "admin_review"

    sources_state = {"scope_revoked": True, "results": []}
    reviews_service = SimpleNamespace(
        lock=threading.RLock(),
        drafts_service=SimpleNamespace(initial_review=None),
        sources_service=SimpleNamespace(get=lambda cid: sources_state),
        get=lambda cid: {
            "reading_confirmation": {"confirmed": True, "content_hash": "hash-1"},
            "requests": [
                {
                    "request_id": "P1",
                    "paragraphs": [{"text": "Respuesta.", "cited_chunk_ids": []}],
                    "facts": [],
                    "available_supports": [],
                    "pending": [],
                }
            ],
        },
    )
    office = SimpleNamespace(
        reviews_service=reviews_service,
        cases=store,
        library=SimpleNamespace(
            lock=threading.RLock(),
            linked_collections=lambda cid: [],
        ),
    )
    monkeypatch.setattr(
        "pqrs_claro.pool_admin_review.get_workspace",
        lambda svc, cid: {
            "revision": 1,
            "blocks": [{"kind": "body", "text": "Respuesta."}],
            "letterhead": None,
            "metadata": {"subject": "Consulta"},
            "attachment_source_ids": [],
        },
    )
    admin_review = PoolAdminReview(pool, preanalysis, office)
    decision = SimpleNamespace(
        actor_id="admin",
        revision=detail["revision"],
        workspace_revision=1,
        content_hash="hash-1",
    )

    with pytest.raises(Conflict, match="fuentes o respuestas cambiaron"):
        admin_review.submit(case["id"], decision)

    # Missing finding for P1 must raise Conflict instead of KeyError.
    sources_state.update(scope_revoked=False, results=[])
    with pytest.raises(Conflict, match="no corresponden"):
        admin_review.submit(case["id"], decision)

    # Matching finding completes handoff into initial_review cleanly.
    sources_state.update(
        scope_revoked=False,
        results=[{"request_id": "P1", "status": "references_found", "supports": []}],
    )
    submitted = admin_review.submit(case["id"], decision)
    assert submitted["stage"] == "initial_review"
    assert submitted["review_imported"] is True
