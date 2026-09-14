"""Confirmación y preparación automática, persistente y sin aprobar respuestas."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictBool

from .service import user_error
from .storage import Conflict, now


class PreparationVersion(BaseModel):
    version: int = Field(ge=1)
    retry_analysis: StrictBool = False


class PreparationService:
    def __init__(self, cases, identification, sources, drafts, reviews):
        self.cases, self.identification = cases, identification
        self.sources, self.drafts, self.reviews = sources, drafts, reviews
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preparation")
        self.active = set()
        self.wake_requested = set()
        with cases.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS preparations (case_id TEXT PRIMARY KEY, body TEXT)"
            )

    def get(self, case_id):
        case = self.cases.get(case_id)
        with self.cases.connect() as conn:
            row = conn.execute(
                "SELECT body FROM preparations WHERE case_id=?", (case_id,)
            ).fetchone()
        result = json.loads(row[0]) if row else dict(case_id=case_id, status="idle", stage=None)
        return {**result, "stale": bool(row and result["version"] != case["version"])}

    def save(self, job, **changes):
        job.update(changes, updated_at=now())
        with self.cases.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO preparations VALUES (?,?)",
                (job["case_id"], json.dumps(job)),
            )
        return dict(job)

    def confirm(self, case_id, version):
        with self.lock:
            previous = self.get(case_id)
            case = self.cases.get(case_id)
            if (
                case["status"] == "confirmed"
                and not previous["stale"]
                and previous.get("confirmed_from") == version
            ):
                return {"case": case, "preparation": previous}
            case = self.identification.confirm(case_id, version)
            job = self.start(case_id, case["version"], confirmed_from=version)
            return {"case": case, "preparation": job}

    def start(self, case_id, version, confirmed_from=None, *, retry_analysis=False):
        with self.lock:
            case = self.cases.get(case_id)
            if case["version"] != version or case["status"] != "confirmed":
                raise Conflict("El expediente cambió. Revisa las solicitudes antes de continuar.")
            previous = self.get(case_id)
            if case_id in self.active:
                return previous
            if previous["status"] == "ready" and not previous["stale"] and not retry_analysis:
                mapping = self.sources.get(case_id)
                if mapping["status"] == "ready" and not mapping["stale"]:
                    return previous
            job = dict(
                case_id=case_id,
                version=version,
                status="running",
                stage="sources",
                confirmed_from=confirmed_from or previous.get("confirmed_from"),
                error=None,
                retry_analysis=retry_analysis,
            )
            self.save(job)
            self.active.add(case_id)
            self.pool.submit(self.run, job)
            return dict(job)

    def check(self, job):
        if self.stop.is_set():
            raise InterruptedError()
        case = self.cases.get(job["case_id"])
        if case["version"] != job["version"] or case["status"] != "confirmed":
            raise Conflict("Las solicitudes cambiaron. Revisa el expediente antes de continuar.")

    def decision_saved(self, case_id):
        with self.lock:
            if case_id in self.active:
                self.wake_requested.add(case_id)
                return
            return self.start(case_id, self.cases.get(case_id)["version"])

    def wait(self, service, job):
        while True:
            self.check(job)
            result = service.get(job["case_id"])
            if result["status"] != "running":
                return result
            self.stop.wait(0.3)

    def run(self, job):
        case_id, version = job["case_id"], job["version"]
        try:
            self.check(job)
            mapping = self.sources.get(case_id)
            if mapping["status"] != "running":
                self.sources.start(case_id, version, retry_analysis=job.get("retry_analysis", False))
            mapping = self.wait(self.sources, job)
            if mapping.get("stale") or mapping["status"] not in {"ready", "error"}:
                raise ValueError(mapping.get("error") or "Actualiza la búsqueda de fuentes.")
            self.check(job)
            self.save(job, stage="points")
            self.reviews.start(case_id, version, before_draft=True)
            attempted = set()
            while True:
                self.check(job)
                rows = self.reviews.get(case_id)["requests"]
                findings = {r["request_id"]: r for r in mapping.get("results", [])}
                eligible = [r for r in rows if r["request_id"] in findings
                            and self.drafts._ready_for_draft(r, findings[r["request_id"]])]
                fresh = [r for r in eligible if (r["request_id"], self.drafts._review_input(r)) not in attempted]
                if not fresh:
                    break
                attempted.update((r["request_id"], self.drafts._review_input(r)) for r in eligible)
                self.save(job, stage="drafts")
                self.drafts.start(case_id, version, ready_only=True)
                draft = self.wait(self.drafts, job)
                if draft.get("stale"):
                    raise ValueError(draft.get("error") or "La preparación cambió durante la redacción.")
                self.save(job, stage="review")
                self.reviews.start(case_id, version, before_draft=True)
            rows = self.reviews.get(case_id)["requests"]
            waiting = [r["request_id"] for r in rows if not r["paragraphs"]]
            errors = [r["request_id"] for r in mapping.get("results", []) if r.get("status") == "error"]
            self.save(job, status="waiting_review" if waiting or errors else "ready",
                      stage="points" if waiting or errors else "review", error=None,
                      waiting_request_ids=waiting, analysis_error_ids=errors)
        except InterruptedError:
            self.save(
                job,
                status="interrupted",
                error="El servicio se reinició. Puedes continuar el proceso guardado.",
            )
        except Exception as exc:
            self.save(job, status="error", error=user_error(exc))
        finally:
            with self.lock:
                self.active.discard(case_id)
                wake = case_id in self.wake_requested
                self.wake_requested.discard(case_id)
                if wake and not self.stop.is_set():
                    self.start(case_id, self.cases.get(case_id)["version"])

    def recover(self):
        with self.cases.connect() as conn:
            rows = conn.execute("SELECT body FROM preparations").fetchall()
        for row in rows:
            job = json.loads(row[0])
            if job["status"] == "running":
                self.save(
                    job,
                    status="interrupted",
                    error="El servicio se reinició. Puedes continuar el proceso guardado.",
                )

    def close(self):
        self.stop.set()
        self.pool.shutdown(wait=True)


def preparation_router(service):
    router = APIRouter()

    @router.post("/api/cases/{case_id}/confirm-and-prepare", status_code=202)
    def confirm(case_id: str, body: PreparationVersion):
        return service.confirm(case_id, body.version)

    @router.get("/api/cases/{case_id}/preparation")
    def get(case_id: str):
        return service.get(case_id)

    @router.post("/api/cases/{case_id}/preparation", status_code=202)
    def resume(case_id: str, body: PreparationVersion):
        return service.start(case_id, body.version, retry_analysis=body.retry_analysis)

    return router
