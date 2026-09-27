"""Revisión inicial persistente; una recomendación nunca autoriza el trámite."""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

from fastapi import APIRouter

from .classification_questions import QUESTIONS
from .intake_engine import INSTRUCTIONS, OpenAIIntakeEngine, materialize
from .intake_models import POLICY_VERSION, TERM_REFERENCE, IntakeDecision, IntakeStart
from .jev_client import MODEL as JEV_MODEL
from .jev_client import get_key as get_jev_key
from .jev_intake import CLASSIFICATION_VERSION, JevIntakeEngine
from .service import user_error
from .source_library import digest
from .source_retrieval import retrieve
from .storage import Conflict, now


class IntakeService:
    def __init__(self, settings, cases, library, sources, *, engine=None):
        self.settings, self.cases, self.library, self.sources = settings, cases, library, sources
        self.engine = engine
        self.enabled = settings.initial_review_enabled
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intake")
        self.active = set()
        self.downstream = ()
        self.identification = None
        with cases.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS intake_reviews (case_id TEXT PRIMARY KEY, body TEXT)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS intake_history (case_id TEXT, body TEXT)")

    def fingerprint(self, case_id):
        case = self.cases.get(case_id)
        return digest(
            {
                "original": case["sha256"],
                "pages": case.get("pages"),
                "identification": case.get("identification"),
                "catalog": sorted(self.sources.catalog(case_id), key=lambda s: s["id"]),
                "collections": self.library.linked_collections(case_id),
                "model": self.settings.model,
                "policy": POLICY_VERSION,
                "review_instructions": INSTRUCTIONS,
                "classification": {
                    "provider": self.settings.initial_classification_provider,
                    "model": JEV_MODEL,
                    "version": CLASSIFICATION_VERSION,
                    "question": QUESTIONS["petition_type"],
                }
                if self.settings.initial_classification_provider == "jev"
                else {"provider": "openai"},
            }
        )

    def saved(self, case_id):
        with self.cases.connect() as conn:
            row = conn.execute(
                "SELECT body FROM intake_reviews WHERE case_id=?", (case_id,)
            ).fetchone()
        return (
            json.loads(row[0])
            if row
            else {
                "case_id": case_id,
                "revision": 0,
                "status": "idle",
                "report": None,
                "decisions": None,
                "error": None,
            }
        )

    def get(self, case_id):
        case = self.cases.get(case_id)
        row = self.saved(case_id)
        legacy = bool(row.get("report") and row.get("policy_version") != POLICY_VERSION)
        stale = legacy or bool(
            row.get("fingerprint") and row["fingerprint"] != self.fingerprint(case_id)
        )
        allowed = not self.enabled or (
            row["status"] == "approved" and not stale and case["status"] == "confirmed"
        )
        return {
            **row,
            "enabled": self.enabled,
            "stale": stale,
            "legacy_report": legacy,
            "can_prepare": allowed,
            "classification_provider": self.settings.initial_classification_provider,
        }

    def save(self, row, **changes):
        previous = self.saved(row["case_id"])
        result = {**row, **changes, "revision": previous["revision"] + 1, "updated_at": now()}
        with self.cases.connect() as conn:
            conn.execute(
                "INSERT INTO intake_history VALUES (?,?)",
                (row["case_id"], json.dumps(result, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO intake_reviews VALUES (?,?)",
                (row["case_id"], json.dumps(result, ensure_ascii=False)),
            )
        return result

    def assert_allowed(self, case_id):
        if self.enabled and not self.get(case_id)["can_prepare"]:
            raise Conflict(
                "Completa la revisión inicial y confirma continuar en todas las solicitudes."
            )

    def assert_idle(self, case_id):
        if any(
            case_id in getattr(s, "active", ())
            or any(isinstance(k, tuple) and k[0] == case_id for k in getattr(s, "active", ()))
            for s in self.downstream
        ):
            raise Conflict(
                "Espera a que termine la preparación antes de cambiar la revisión inicial."
            )

    def analyze_identified(self, case):
        """Start automatically; provider failures must not erase extracted petitions."""
        if not self.enabled:
            return
        with self.identification.lock if self.identification else nullcontext(), self.lock:
            previous = self.get(case["id"])
            if previous["status"] != "idle" and not previous["stale"]:
                return
            try:
                self.start(
                    case["id"], IntakeStart(version=case["version"], revision=previous["revision"])
                )
            except Exception as exc:
                self.save(
                    self.saved(case["id"]),
                    status="error",
                    error=user_error(exc),
                    fingerprint=self.fingerprint(case["id"]),
                    report=None,
                    decisions=None,
                )

    def start(self, case_id, body):
        with self.identification.lock if self.identification else nullcontext(), self.lock:
            if not self.enabled:
                raise Conflict("La revisión inicial no está habilitada en este entorno.")
            self.assert_idle(case_id)
            case, previous = self.cases.get(case_id), self.saved(case_id)
            if (
                case["status"] not in {"needs_review", "confirmed"}
                or case["version"] != body.version
            ):
                raise Conflict("Espera a identificar las peticiones y actualiza antes de analizar.")
            if case_id in self.active:
                return self.get(case_id)
            if previous["revision"] != body.revision:
                raise Conflict("La revisión inicial cambió. Actualiza antes de reanalizar.")
            if not self.settings.api_key and self.engine is None:
                raise ValueError(
                    "Configura la IA para analizar la revisión inicial; no se simulan resultados."
                )
            if (
                self.engine is None
                and self.settings.initial_classification_provider == "jev"
                and not get_jev_key()
            ):
                raise ValueError(
                    "Configura AI_GATEWAY_API_KEY en .env.jev.local para clasificar con JEV."
                )
            row = self.save(
                previous,
                status="running",
                policy_version=POLICY_VERSION,
                fingerprint=self.fingerprint(case_id),
                error=None,
                report=None,
                decisions=None,
                document_decision=None,
                minimum_reference_days=None,
                reviewed_by=None,
                decided_at=None,
            )
            self.active.add(case_id)
            self.pool.submit(self.run, row)
            return self.get(case_id)

    def payload(self, case_id):
        case = self.cases.get(case_id)
        if hashlib.sha256(self.cases.original(case_id).read_bytes()).hexdigest() != case["sha256"]:
            raise ValueError("El original de la petición cambió en disco.")
        sources, chunks = self.library.snapshot(case_id)
        linked = self.library.linked_collections(case_id)
        candidates = {}
        base = {"case_id": case_id, "allowed_collection_ids": linked}
        queries = [
            *case["identification"]["requests"],
            {
                "id": "INITIAL",
                "title": "Revisión de requisitos y trámite de PQRS",
                "description": "petición incompleta datos contacto lenguaje respetuoso "
                "reiteración antecedentes clasificación requisitos atención ciudadano",
            },
        ]
        for query in queries:
            for candidate in retrieve({**query, **base}, chunks, limit=16):
                candidates[candidate["chunk_id"]] = candidate
        # Bound the request explicitly rather than silently dropping the original or requests.
        if len(candidates) > 96:
            raise ValueError(
                "La revisión recuperó demasiados fragmentos. Delimita las fuentes de consulta."
            )
        catalog = self.sources.catalog(case_id)
        return {
            "identification": case["identification"],
            "pages": case["pages"],
            "candidates": list(candidates.values()),
            "scope": {
                "linked_collections": linked,
                "readable_sources": len(sources),
                "history_available": any(
                    c.get("category") == "historical_response" for c in candidates.values()
                ),
                "catalog": [
                    {
                        k: s.get(k)
                        for k in ("id", "title", "category", "validity", "extraction_status")
                    }
                    for s in catalog
                ],
                "note": "Consulta local parcial; no es una búsqueda institucional exhaustiva.",
            },
        }

    def run(self, row):
        case_id = row["case_id"]
        try:
            payload = self.payload(case_id)
            if self.settings.initial_classification_provider not in {"openai", "jev"}:
                raise ValueError("Proveedor de clasificación no válido.")
            engine = self.engine or (
                JevIntakeEngine(self.settings)
                if self.settings.initial_classification_provider == "jev"
                else OpenAIIntakeEngine(self.settings)
            )
            report = materialize(engine.assess(payload), payload)
            with self.lock:
                if row["fingerprint"] != self.fingerprint(case_id):
                    raise Conflict("Cambiaron las entradas durante el análisis. Vuelve a analizar.")
                self.save(
                    row,
                    status="needs_review",
                    report=report,
                    scope=payload["scope"],
                    consulted_sources=list(
                        {
                            c["source_id"]: {
                                k: c.get(k) for k in ("source_id", "title", "category", "version")
                            }
                            for c in payload["candidates"]
                        }.values()
                    ),
                    error=None,
                )
        except Exception as exc:
            with self.lock:
                self.save(row, status="error", error=user_error(exc), decisions=None)
        finally:
            with self.lock:
                self.active.discard(case_id)

    def decide(self, case_id, body):
        with (
            self.identification.lock if self.identification else nullcontext(),
            self.lock,
            self.library.lock,
        ):
            self.assert_idle(case_id)
            row = self.get(case_id)
            if row["status"] not in {"needs_review", "approved", "routed"} or row["stale"]:
                raise Conflict("Analiza la revisión inicial vigente antes de guardar la decisión.")
            if row["revision"] != body.revision:
                raise Conflict("Otra decisión cambió esta revisión. Actualiza antes de guardar.")
            expected = {r["request_id"] for r in row["report"]["requests"]}
            ids = [r.request_id for r in body.requests]
            if len(ids) != len(set(ids)) or set(ids) != expected:
                raise ValueError("Registra una decisión por cada solicitud, sin duplicados.")
            if (
                not body.reviewed_by.strip()
                or not body.document.note.strip()
                or not body.document.reviewed
                or any(not r.note.strip() or not r.reviewed for r in body.requests)
            ):
                raise ValueError(
                    "Revisa los datos y lenguaje del documento una vez, y las peticiones. "
                    "Registra responsable y justificaciones."
                )
            if any(
                r.route == "continue" and r.petition_type == "undetermined" for r in body.requests
            ):
                raise ValueError(
                    "Define el tipo de cada solicitud antes de continuar a las respuestas."
                )
            decisions = [r.model_dump(mode="json") for r in body.requests]
            reports = {r["request_id"]: r for r in row["report"]["requests"]}
            for item in decisions:
                repetition = next(
                    c for c in reports[item["request_id"]]["checks"] if c["key"] == "repetition"
                )
                if item["route"] == "reiterate" and (
                    repetition["state"] in {"unavailable", "unverified"}
                    or not any(
                        s.get("category") == "historical_response" for s in repetition["sources"]
                    )
                ):
                    raise ValueError("La ruta por reiteración necesita un antecedente comprobable.")
                item["reference_days"] = TERM_REFERENCE.get(item["petition_type"])
            can_continue = body.document.route == "continue" and all(
                r.route == "continue" for r in body.requests
            )
            case = self.cases.get(case_id)
            if case["status"] == "needs_review" and self.identification is not None:
                self.identification.confirm(case_id, case["version"])
            elif case["status"] != "confirmed":
                raise Conflict("La identificación aún no está disponible para confirmar.")
            self.save(
                {
                    k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "enabled",
                        "stale",
                        "legacy_report",
                        "can_prepare",
                        "classification_provider",
                    }
                },
                status="approved" if can_continue else "routed",
                decisions=decisions,
                document_decision=body.document.model_dump(mode="json"),
                reviewed_by=body.reviewed_by.strip(),
                decided_at=now(),
                minimum_reference_days=min(
                    (r["reference_days"] for r in decisions if r["reference_days"] is not None),
                    default=None,
                ),
            )
            return self.get(case_id)

    def history(self, case_id):
        self.cases.get(case_id)
        with self.cases.connect() as conn:
            return [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM intake_history WHERE case_id=? ORDER BY rowid", (case_id,)
                )
            ]

    def recover(self):
        with self.cases.connect() as conn:
            rows = conn.execute("SELECT body FROM intake_reviews").fetchall()
        for raw in rows:
            row = json.loads(raw[0])
            if row["status"] == "running":
                self.save(
                    row,
                    status="interrupted",
                    error="El análisis se interrumpió. Vuelve a analizar.",
                )

    def close(self):
        self.pool.shutdown(wait=True)


def intake_router(service):
    router = APIRouter(prefix="/api/cases/{case_id}/initial-review")

    @router.get("")
    def get(case_id: str):
        return service.get(case_id)

    @router.post("/analyze", status_code=202)
    def analyze(case_id: str, body: IntakeStart):
        return service.start(case_id, body)

    @router.put("/decision")
    def decide(case_id: str, body: IntakeDecision):
        return service.decide(case_id, body)

    @router.get("/history")
    def history(case_id: str):
        return {"events": service.history(case_id)}

    return router
