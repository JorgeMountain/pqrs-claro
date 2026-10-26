"""Persistent preanalysis, separate from identification and confirmed by the owner."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pymupdf
from fastapi import APIRouter
from pydantic import Field, StrictBool

from .extraction import OpenAIOCR, PDFExtractor
from .management import ManagementAction
from .models import Page, StrictModel, validate_pages
from .performance_metrics import track_case
from .preanalysis_engine import CheckKey, OpenAIPreanalysisEngine, materialize
from .storage import Conflict, now

KEYS = ("requester", "respect", "integrity")


class CheckDocument(StrictModel):
    actor_id: str = Field(min_length=1, max_length=40)
    retry: bool = False


class StartAnalysis(StrictModel):
    actor_id: str = Field(min_length=1, max_length=40)
    revision: int = Field(ge=1)
    management_revision: int = Field(ge=0)
    confirmed: StrictBool
    acknowledged: list[CheckKey] = Field(default_factory=list, max_length=3)
    notes: dict[CheckKey, str] = Field(default_factory=dict, max_length=3)


class SaveReview(StrictModel):
    actor_id: str = Field(min_length=1, max_length=40)
    revision: int = Field(ge=1)
    acknowledged: list[CheckKey] = Field(default_factory=list, max_length=3)
    notes: dict[CheckKey, str] = Field(default_factory=dict, max_length=3)


class PreanalysisService:
    def __init__(self, settings, store, management, identification, *, engine=None):
        self.settings, self.store = settings, store
        self.management, self.identification = management, identification
        # Admission, ownership changes and the final start share the same lock.
        self.lock = identification.lock
        self.engine = engine
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preanalysis")
        self.active = set()
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS case_preanalysis "
                "(case_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )

    def saved(self, case_id):
        case = self.store.get(case_id)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT body FROM case_preanalysis WHERE case_id=?", (case_id,)
            ).fetchone()
        return (
            json.loads(row[0])
            if row
            else dict(
                status="idle",
                revision=0,
                sha256=case["sha256"],
                checks={},
                pages=[],
                page_count=0,
                error=None,
                approval=None,
                events=[],
            )
        )

    def save(self, case_id, record, **changes):
        record = {**record, **changes, "revision": record["revision"] + 1, "updated_at": now()}
        with self.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO case_preanalysis VALUES (?,?)",
                (case_id, json.dumps(record, ensure_ascii=False)),
            )
        return record

    def view(self, case_id):
        record = self.saved(case_id)
        return {k: v for k, v in record.items() if k != "pages"}

    def owner(self, case_id, actor):
        self.store.assert_open(case_id)
        record = self.management.get(case_id)
        if not record["owner_id"] or record["owner_id"] != actor:
            raise Conflict("Solo el gestor responsable puede revisar e iniciar este expediente.")
        if record["state"] == "closed":
            raise Conflict("Reabre la gestión del expediente antes de continuar.")
        return record

    def original_matches(self, case_id, expected):
        if hashlib.sha256(self.store.original(case_id).read_bytes()).hexdigest() != expected:
            raise Conflict("El documento original cambió. Carga nuevamente el PDF para revisarlo.")

    def check(self, case_id, actor, *, retry=False):
        with self.lock:
            self.owner(case_id, actor)
            case = self.store.get(case_id)
            if case.get("identification") or case["status"] not in {"uploaded", "error"}:
                raise Conflict("Este expediente ya inició su identificación. Abre su seguimiento.")
            record = self.saved(case_id)
            self.original_matches(case_id, case["sha256"])
            if case_id in self.active or (record["status"] == "ready" and not retry):
                return self.view(case_id)
            if case_id in self.identification.active:
                raise Conflict("Espera a que termine el procesamiento del expediente.")
            record = self.save(
                case_id, record, status="running", error=None, approval=None, draft=None
            )
            self.active.add(case_id)
            self.pool.submit(self.run, case_id)
            return {k: v for k, v in record.items() if k != "pages"}

    @track_case("preanalysis", "case_id")
    def run(self, case_id):
        pages = []
        owned_engine = None
        try:
            record = self.saved(case_id)
            self.original_matches(case_id, record["sha256"])
            if record["pages"]:
                pages = [Page.model_validate(p) for p in record["pages"]]
                validate_pages(pages)
            else:
                extractor = self.identification.extractor or PDFExtractor(
                    OpenAIOCR(self.settings.api_key, self.settings.model)
                    if self.settings.api_key
                    else None
                )
                pages = extractor.extract(str(self.store.original(case_id)))
            if self.engine is None and not self.settings.api_key:
                raise ValueError(
                    "La revisión automática no está disponible. "
                    "Revisa los tres puntos en el documento y registra tus observaciones."
                )
            engine = self.engine
            if engine is None:
                owned_engine = engine = OpenAIPreanalysisEngine(self.settings)
            checks = materialize(engine.assess(pages), pages)
            self.original_matches(case_id, record["sha256"])
            with self.lock:
                self.save(
                    case_id,
                    self.saved(case_id),
                    status="ready",
                    checks=checks,
                    pages=[p.model_dump(mode="json") for p in pages],
                    page_count=len(pages),
                    error=None,
                )
        except Exception as exc:
            # An extraction error is not evidence that sender data are missing.
            error = (
                str(exc)[:600]
                if isinstance(exc, (ValueError, Conflict))
                else "No se pudieron completar las verificaciones. Puedes reintentarlo."
            )
            checks = {
                key: {
                    "state": "unverified",
                    "summary": "Pendiente de comprobar en el documento original.",
                    "refs": [],
                }
                for key in KEYS
            }
            with self.lock:
                self.save(
                    case_id,
                    self.saved(case_id),
                    status="ready" if pages else "error",
                    checks=checks,
                    pages=[p.model_dump(mode="json") for p in pages],
                    page_count=len(pages),
                    error=error,
                )
        finally:
            if owned_engine:
                owned_engine.close()
            with self.lock:
                self.active.discard(case_id)

    def require_approved(self, case_id):
        record = self.saved(case_id)
        management = self.management.get(case_id)
        approval = record.get("approval") or {}
        if (
            record["status"] != "ready"
            or not approval
            or approval.get("actor_id") != management["owner_id"]
            or approval.get("management_revision") != management["revision"]
        ):
            raise Conflict("Revisa y confirma el preanálisis antes de iniciar la identificación.")
        self.original_matches(case_id, record["sha256"])
        return record

    def save_review(self, case_id, body):
        with self.lock:
            self.owner(case_id, body.actor_id)
            record = self.saved(case_id)
            if (
                body.revision != record["revision"]
                or record["status"] != "ready"
                or case_id in self.identification.active
                or self.store.get(case_id).get("identification")
            ):
                raise Conflict("El preanálisis cambió. Vuelve a abrir el expediente.")
            if any(len(note) > 1500 for note in body.notes.values()):
                raise ValueError("Cada observación admite hasta 1.500 caracteres.")
            self.save(
                case_id,
                record,
                draft=dict(
                    actor_id=body.actor_id,
                    acknowledged=body.acknowledged,
                    notes={k: v.strip() for k, v in body.notes.items()},
                    at=now(),
                ),
            )
            return self.view(case_id)

    def start(self, case_id, body):
        with self.lock:
            management = self.owner(case_id, body.actor_id)
            case = self.store.get(case_id)
            record = self.saved(case_id)
            if (
                case.get("identification")
                or case_id in self.identification.active
                or case_id in self.active
                or case["status"] not in {"uploaded", "error"}
            ):
                raise Conflict("El expediente ya está procesándose o tiene resultados.")
            if (
                body.revision != record["revision"]
                or body.management_revision != management["revision"]
            ):
                raise Conflict("El expediente cambió. Vuelve a abrir el preanálisis y revísalo.")
            if record["status"] != "ready" or not record["pages"]:
                raise Conflict("Primero completa la lectura y las verificaciones del documento.")
            if not body.confirmed:
                raise ValueError("Confirma que revisaste el documento antes de iniciar.")
            for key in KEYS:
                if record["checks"][key]["state"] != "pass":
                    note = body.notes.get(key, "").strip()
                    if key not in body.acknowledged or not 8 <= len(note) <= 1500:
                        raise ValueError("Revisa cada alerta y registra cómo se puede continuar.")
            if any(len(note) > 1500 for note in body.notes.values()):
                raise ValueError("Cada observación admite hasta 1.500 caracteres.")
            self.original_matches(case_id, record["sha256"])
            if not self.settings.api_key and self.identification.identifier is None:
                raise ValueError(
                    "Falta configurar el motor de identificación. "
                    "El documento permanece en preanálisis."
                )
            if not management["started_at"]:
                management = self.management.change(
                    case_id,
                    ManagementAction(
                        revision=management["revision"], actor_id=body.actor_id, action="start"
                    ),
                )
            approval = dict(
                actor_id=body.actor_id,
                management_revision=management["revision"],
                at=now(),
                acknowledged=body.acknowledged,
                notes={k: v.strip() for k, v in body.notes.items()},
            )
            self.save(
                case_id,
                record,
                approval=approval,
                events=record["events"] + [{"action": "confirm_and_start", **approval}],
            )
            return self.identification.start(case_id)

    def page(self, case_id, number):
        record = self.saved(case_id)
        self.original_matches(case_id, record["sha256"])
        with pymupdf.open(self.store.original(case_id)) as doc:
            if not 1 <= number <= len(doc):
                raise KeyError("Página no encontrada.")
            page = doc[number - 1]
            marks = []
            requester = record["checks"].get("requester", {})
            # Use PDF text geometry; never place highlights by guessed coordinates.
            for text in (requester.get("name"), requester.get("contact")):
                if text:
                    marks.extend(
                        {
                            "key": "requester",
                            "x": r.x0,
                            "y": r.y0,
                            "width": r.width,
                            "height": r.height,
                        }
                        for r in page.search_for(text)
                    )
            for ref in record["checks"].get("respect", {}).get("refs", []):
                if ref["page"] == number:
                    marks.extend(
                        {
                            "key": "respect",
                            "x": r.x0,
                            "y": r.y0,
                            "width": r.width,
                            "height": r.height,
                        }
                        for r in page.search_for(ref["quote"])
                    )
            return dict(
                page=number,
                page_count=len(doc),
                width=page.rect.width,
                height=page.rect.height,
                marks=marks,
            )

    def recover(self):
        with self.store.connect() as db:
            rows = list(db.execute("SELECT case_id,body FROM case_preanalysis"))
            for case_id, raw in rows:
                record = json.loads(raw)
                if record["status"] == "running":
                    record.update(
                        status="error",
                        revision=record["revision"] + 1,
                        error="Se interrumpió el preanálisis. Reintenta las verificaciones.",
                    )
                    db.execute(
                        "UPDATE case_preanalysis SET body=? WHERE case_id=?",
                        (json.dumps(record, ensure_ascii=False), case_id),
                    )

    def close(self):
        self.pool.shutdown(wait=True)


def preanalysis_router(service):
    router = APIRouter()

    @router.get("/api/cases/{case_id}/preanalysis")
    def get(case_id: str):
        return service.view(case_id)

    @router.post("/api/cases/{case_id}/preanalysis/check")
    def check(case_id: str, body: CheckDocument):
        return service.check(case_id, body.actor_id, retry=body.retry)

    @router.post("/api/cases/{case_id}/preanalysis/start")
    def start(case_id: str, body: StartAnalysis):
        return service.start(case_id, body)

    @router.post("/api/cases/{case_id}/preanalysis/draft")
    def save_review(case_id: str, body: SaveReview):
        return service.save_review(case_id, body)

    @router.get("/api/cases/{case_id}/preanalysis/pages/{number}")
    def page(case_id: str, number: int):
        return service.page(case_id, number)

    return router
