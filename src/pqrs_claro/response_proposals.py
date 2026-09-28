"""Propuestas durables y comparación antes de aplicar una revisión explícita."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import TypedDict
from uuid import uuid4

from fastapi import APIRouter
from langgraph.graph import END, START, StateGraph
from pydantic import Field

from .models import StrictModel
from .response_proposal_engine import OpenAIResponseProposalEngine, validate_proposal
from .review_models import Actor, ReviewEdit
from .review_service import input_hash
from .service import user_error
from .storage import Conflict, now


class ProposalState(TypedDict, total=False):
    proposal: dict
    checks: dict


class ProposalStart(StrictModel):
    revision: int = Field(ge=1)


class ProposalApply(ProposalStart):
    edited_by: Actor


class ResponseProposalService:
    def __init__(self, settings, reviews, engine=None):
        self.settings, self.reviews, self.engine = settings, reviews, engine
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="proposals")
        self.active = {}
        with reviews.store.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS response_proposals (
                id TEXT PRIMARY KEY, case_id TEXT, request_id TEXT, created_at TEXT, body TEXT
            )""")

    def save(self, job, **updates):
        job.update(updates, updated_at=now())
        with self.reviews.store.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO response_proposals VALUES (?,?,?,?,?)",
                (job["id"], job["case_id"], job["request_id"], job["created_at"], json.dumps(job)),
            )
        return deepcopy(job)

    def read(self, case_id, request_id, proposal_id=None):
        with self.reviews.store.connect() as conn:
            row = conn.execute(
                "SELECT body FROM response_proposals WHERE case_id=? AND request_id=?"
                + (" AND id=?" if proposal_id else " ORDER BY created_at DESC LIMIT 1"),
                (case_id, request_id, proposal_id) if proposal_id else (case_id, request_id),
            ).fetchone()
        if not row and proposal_id:
            raise KeyError("La propuesta no pertenece a esta respuesta.")
        return json.loads(row[0]) if row else None

    def get(self, case_id, request_id):
        with self.reviews.lock:
            row = self.reviews._row(case_id, request_id, fresh=False)
            job = self.read(case_id, request_id)
            if not job:
                return {"status": "idle"}
            stale = (
                row["stale"]
                or row["revision"] != job["base_revision"]
                or (input_hash(row) != job["base_hash"])
            )
            return {**job, "stale": stale}

    def start(self, case_id, request_id, revision):
        with self.lock, self.reviews.lock:
            self.reviews.cases.assert_open(case_id)
            row = self.reviews._row(case_id, request_id, revision)
            key = (case_id, request_id)
            if key in self.active:
                return self.get(*key)
            latest = self.get(*key)
            if latest["status"] == "ready" and not latest["stale"]:
                return latest
            if not self.settings.api_key and self.engine is None:
                raise ValueError("Falta configurar OpenAI para proponer un ajuste.")
            job = dict(
                id=uuid4().hex,
                case_id=case_id,
                request_id=request_id,
                model=self.settings.model,
                created_at=now(),
                base_revision=revision,
                base_hash=input_hash(row),
                original=deepcopy(row["paragraphs"]),
                status="running",
                stage="writing",
                proposal=None,
                checks=None,
                error=None,
            )
            self.save(job)
            self.active[key] = job["id"]
            self.pool.submit(self.run, job, deepcopy(row))
            return deepcopy(job)

    def ensure_current(self, job):
        row = self.reviews._row(job["case_id"], job["request_id"], job["base_revision"])
        if input_hash(row) != job["base_hash"]:
            raise Conflict("La respuesta cambió. Solicita una propuesta sobre la versión actual.")
        return row

    def run(self, job, row):
        try:
            engine = self.engine or OpenAIResponseProposalEngine(
                self.settings.api_key, self.settings.model
            )

            def write(state):
                with self.reviews.lock:
                    self.ensure_current(job)
                result, _ = validate_proposal(row, engine.propose(row))
                return {"proposal": result}

            def check(state):
                with self.reviews.lock:
                    self.ensure_current(job)
                self.save(job, stage="checking")
                _, candidate = validate_proposal(row, state["proposal"])
                result = self.reviews._engine().assess(row["request_snapshot"], candidate)
                return {"checks": result}

            graph = StateGraph(ProposalState)
            graph.add_node("proponer", write)
            graph.add_node("comprobar", check)
            graph.add_edge(START, "proponer")
            graph.add_edge("proponer", "comprobar")
            graph.add_edge("comprobar", END)
            result = graph.compile().invoke({})
            with self.reviews.lock:
                self.ensure_current(job)
                self.save(job, status="ready", stage="done", **result)
        except Exception as error:
            self.save(job, status="error", error=user_error(error))
        finally:
            with self.lock:
                self.active.pop((job["case_id"], job["request_id"]), None)

    def apply(self, case_id, request_id, proposal_id, revision, actor):
        with self.lock, self.reviews.lock:
            self.reviews.cases.assert_open(case_id)
            job = self.read(case_id, request_id, proposal_id)
            if job["status"] != "ready" or revision != job["base_revision"]:
                raise Conflict("La propuesta ya no está disponible para aplicar.")
            row = self.ensure_current(job)
            proposal, _ = validate_proposal(row, job["proposal"])
            edited = self.reviews.edit(
                case_id,
                request_id,
                ReviewEdit(
                    revision=revision,
                    edited_by=actor,
                    paragraphs=proposal["paragraphs"],
                    pending_resolutions=[],
                ),
            )
            self.save(job, status="applied", applied_by=actor, applied_revision=edited["revision"])
            return edited

    def dismiss(self, case_id, request_id, proposal_id):
        with self.lock:
            job = self.read(case_id, request_id, proposal_id)
            if job["status"] not in {"ready", "error", "interrupted", "dismissed"}:
                raise Conflict("Espera a que termine la propuesta antes de descartarla.")
            return self.save(job, status="dismissed")

    def recover(self):
        with self.reviews.store.connect() as conn:
            jobs = [
                json.loads(row[0]) for row in conn.execute("SELECT body FROM response_proposals")
            ]
        for job in jobs:
            if job["status"] == "running":
                self.save(
                    job, status="interrupted", error="El servicio se reinició. Puedes reintentar."
                )

    def close(self):
        self.pool.shutdown(wait=True)


def response_proposal_router(service):
    router = APIRouter(prefix="/api/cases/{case_id}/review/requests/{request_id}/proposals")

    @router.get("")
    def get(case_id: str, request_id: str):
        return service.get(case_id, request_id)

    @router.post("", status_code=202)
    def start(case_id: str, request_id: str, body: ProposalStart):
        return service.start(case_id, request_id, body.revision)

    @router.post("/{proposal_id}/apply")
    def apply(case_id: str, request_id: str, proposal_id: str, body: ProposalApply):
        return service.apply(case_id, request_id, proposal_id, body.revision, body.edited_by)

    @router.post("/{proposal_id}/dismiss")
    def dismiss(case_id: str, request_id: str, proposal_id: str):
        return service.dismiss(case_id, request_id, proposal_id)

    return router
