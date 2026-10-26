"""Revisión inicial persistente; una recomendación nunca autoriza el trámite."""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
from time import perf_counter

from fastapi import APIRouter

from .classification_questions import QUESTIONS
from .intake_cache import CACHE_VERSION, reuse_plan
from .intake_engine import INSTRUCTIONS, materialize
from .intake_models import (
    POLICY_VERSION,
    TERM_REFERENCE,
    IntakeDecision,
    IntakeStart,
    PilotReviewMode,
)
from .jev_classification import CLASSIFICATION_VERSION as JEV_CLASSIFICATION_VERSION
from .jev_classification import ENDPOINT as JEV_ENDPOINT
from .jev_classification import MODEL as JEV_MODEL
from .jev_classification import SCOPE as JEV_INSTRUCTIONS
from .jev_classification import get_key as get_jev_key
from .jev_intake import CLASSIFICATION_VERSION
from .performance_metrics import track_case
from .petition_classification import (
    CLASSIFICATION_SCOPE,
    PetitionClassificationEngine,
)
from .petition_classification import (
    INSTRUCTIONS as CLASSIFICATION_INSTRUCTIONS,
)
from .service import user_error
from .source_context import CONTEXT_VERSION, build_source_requests
from .source_library import digest
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

    @staticmethod
    def analysis_scope(row):
        # Existing reports retain their original validity rules and decisions.
        return row.get("analysis_scope") or (
            "legacy" if row.get("fingerprint") else CLASSIFICATION_SCOPE)

    def preanalysis(self, case):
        with self.cases.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                "AND name='case_preanalysis'").fetchone():
                return {}
            row = conn.execute("SELECT body FROM case_preanalysis WHERE case_id=?",
                               (case["id"],)).fetchone()
        record = json.loads(row[0]) if row else {}
        if record.get("sha256") != case["sha256"]:
            return {}
        return {k: record.get(k) for k in ("checks", "approval", "revision")}

    def fingerprint(self, case_id, *, identification=None, _catalog=None, scope=None):
        case = self.cases.get(case_id)
        scope = scope or self.analysis_scope(self.saved(case_id))
        if scope == CLASSIFICATION_SCOPE:
            return digest({
                "original": case["sha256"], "pages": case.get("pages"),
                "identification": identification if identification is not None
                else case.get("identification"),
                "preanalysis": self.preanalysis(case), "scope": scope,
                "provider": self.settings.initial_classification_provider,
                "model": JEV_MODEL if self.settings.initial_classification_provider == "jev"
                else self.settings.model,
                "instructions": CLASSIFICATION_INSTRUCTIONS,
                "classification_version": CLASSIFICATION_VERSION,
                "question": QUESTIONS["petition_type"],
                **({"jev_contract": {
                    "version": JEV_CLASSIFICATION_VERSION, "endpoint": JEV_ENDPOINT,
                    "instructions": JEV_INSTRUCTIONS, "context_version": CONTEXT_VERSION,
                }} if self.settings.initial_classification_provider == "jev" else {}),
            })
        return digest(
            {
                "original": case["sha256"],
                "pages": case.get("pages"),
                "identification": (
                    identification if identification is not None else case.get("identification")
                ),
                "catalog": sorted(self.sources.catalog(case_id) if _catalog is None
                                  else _catalog, key=lambda s: s["id"]),
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

    def analysis_plan(self, case_id, row, *, full=False, _catalog=None):
        identification = self.cases.get(case_id)["identification"]
        context = self.fingerprint(case_id, identification={
            k: v for k, v in identification.items() if k != "requests"
        }, _catalog=_catalog, scope=self.analysis_scope(row))
        return context, reuse_plan(row.get("analysis_cache"), context, identification, full=full)

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

    def get(self, case_id, *, _catalog=None, include_plan=True):
        case = self.cases.get(case_id)
        row = self.saved(case_id)
        # Reuse only this call's catalog, retaining the original fingerprint.
        # Downstream eligibility needs the decision, not a new analysis plan.
        has_plan = include_plan and case.get("identification") and row["status"] != "running"
        catalog = _catalog
        if (catalog is None and self.analysis_scope(row) != CLASSIFICATION_SCOPE
                and (row.get("fingerprint") or has_plan)):
            catalog = self.sources.catalog(case_id)
        legacy = bool(row.get("report") and row.get("policy_version") != POLICY_VERSION)
        stale = legacy or bool(
            row.get("fingerprint") and row["fingerprint"] != self.fingerprint(
                case_id, _catalog=catalog)
        )
        bypass = self.pilot_bypassed(case_id)
        allowed = self._decision_allows_preparation(case, row, stale, bypass)
        if self.cases.management and self.cases.management.get(case_id)["state"] == "closed":
            allowed = False
        work = row.get("analysis_work")
        if has_plan:
            _, plan = self.analysis_plan(case_id, row, _catalog=catalog)
            work = {"pending": plan["pending"], "reused": list(plan["reused"]),
                    "reason": plan["reason"]}
        return {
            **{k: v for k, v in row.items() if k != "analysis_cache"},
            "enabled": self.enabled,
            "stale": stale,
            "legacy_report": legacy,
            "can_prepare": allowed,
            "pilot_bypass_active": bypass,
            "classification_provider": self.settings.initial_classification_provider,
            "classification_model": (JEV_MODEL
                if self.settings.initial_classification_provider == "jev" else self.settings.model),
            "next_analysis": work,
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

    def _decision_allows_preparation(self, case, row, stale, bypass):
        return not self.enabled or (
            case["status"] == "confirmed"
            and (row["status"] == "approved" and not stale or bypass)
        )

    def assert_allowed(self, case_id, *, read_only=False):
        if not read_only:
            self.cases.assert_open(case_id)
        if not self.enabled:
            return
        row = self.get(case_id, include_plan=False)
        if not self._decision_allows_preparation(
            self.cases.get(case_id), row, row["stale"], row["pilot_bypass_active"]
        ):
            raise Conflict(
                "Completa la revisión inicial y confirma continuar en todas las solicitudes."
            )

    def pilot_bypassed(self, case_id):
        case = self.cases.get(case_id)
        bypass = self.saved(case_id).get("pilot_bypass") or {}
        return bool(bypass.get("enabled") and bypass.get("basis") == digest({
            "original": case["sha256"], "identification": case.get("identification")
        }))

    def pilot_mode(self, case_id, body):
        with (
            self.identification.lock if self.identification else nullcontext(),
            self.lock,
            self.library.lock,
        ):
            self.cases.assert_open(case_id)
            self.assert_idle(case_id)
            case, row = self.cases.get(case_id), self.saved(case_id)
            if case["version"] != body.version or row["revision"] != body.revision:
                raise Conflict("El expediente cambió. Actualiza antes de continuar.")
            if case_id in self.active or (
                self.identification and case_id in self.identification.active
            ):
                raise Conflict("Espera a que termine el análisis en curso.")
            if body.enabled:
                if case["status"] == "needs_review" and self.identification:
                    self.identification.confirm(case_id, case["version"])
                elif case["status"] != "confirmed":
                    raise Conflict("Primero deben estar identificadas las peticiones.")
            self.save(row, pilot_bypass={
                "enabled": body.enabled,
                "at": now(),
                "basis": digest({"original": case["sha256"],
                                 "identification": case.get("identification")}),
                "reason": "Continuación explícita del piloto; no aprueba la revisión inicial.",
            })
            return self.get(case_id)

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
                    case["id"], IntakeStart(version=case["version"], revision=previous["revision"],
                                            mode="incremental")
                )
            except Exception as exc:
                self.save(
                    self.saved(case["id"]),
                    analysis_scope=CLASSIFICATION_SCOPE,
                    status="error",
                    error=user_error(exc),
                    fingerprint=self.fingerprint(case["id"], scope=CLASSIFICATION_SCOPE),
                    report=None,
                    decisions=None,
                )

    def reuse_selection(self, case, previous_identification):
        """Discard/undo changes selection, not the original or surviving content.

        Keep a persisted full report for undo. Its fingerprint must still match
        sources, model and policy; never bless stale evidence as current.
        """
        if not self.enabled:
            return False
        with self.lock:
            row = self.saved(case["id"])
            current = case["identification"]
            # Upgrade a valid persisted pre-cache report before a content edit.
            if (not row.get("analysis_cache") and row.get("report")
                    and row.get("policy_version") == POLICY_VERSION
                    and row.get("fingerprint") == self.fingerprint(
                        case["id"], identification=previous_identification)):
                context = self.fingerprint(case["id"], identification={
                    k: v for k, v in previous_identification.items() if k != "requests"
                })
                keys = reuse_plan(None, context, previous_identification)["keys"]
                row = self.save(row, analysis_cache={
                    "version": CACHE_VERSION, "context": context,
                    "report": deepcopy(row["report"]),
                    "entries": {r["request_id"]: {"key": keys[r["request_id"]], "report": r}
                                for r in row["report"]["requests"]},
                })
            basis = row.get("selection_basis") or {
                "identification": previous_identification,
                "report": row.get("report"),
                "fingerprint": row.get("fingerprint"),
            }

            def is_selection_of(selected, original):
                if not selected or not original:
                    return False
                if {k: v for k, v in selected.items() if k != "requests"} != {
                    k: v for k, v in original.items() if k != "requests"
                }:
                    return False
                originals = {r["id"]: r for r in original["requests"]}
                ids = {r["id"] for r in selected["requests"]}
                for request in selected["requests"]:
                    expected = deepcopy(originals.get(request["id"]))
                    if expected is None:
                        return False
                    # Discard reconnects children to the nearest remaining ancestor.
                    while expected.get("parent_id") and expected["parent_id"] not in ids:
                        parent = originals.get(expected["parent_id"])
                        if parent is None:
                            return False
                        expected["parent_id"] = parent.get("parent_id")
                    if request != expected:
                        return False
                return bool(ids)

            selection_change = is_selection_of(current, previous_identification)
            cached_selection = is_selection_of(current, basis["identification"])
            if not selection_change and not (row.get("selection_basis") and cached_selection):
                return False
            if (
                not cached_selection
                or not basis.get("report")
                or row.get("policy_version") != POLICY_VERSION
                or row["status"] not in {"needs_review", "approved", "routed"}
                or basis["fingerprint"] != self.fingerprint(
                    case["id"], identification=basis["identification"]
                )
            ):
                # Selection alone never launches a paid call; stale stays stale.
                return True
            indexed = {r["request_id"]: r for r in basis["report"]["requests"]}
            if any(r["id"] not in indexed for r in current["requests"]):
                return True
            report = deepcopy(basis["report"])
            report["requests"] = [deepcopy(indexed[r["id"]]) for r in current["requests"]]
            self.save(
                row, report=report, selection_basis=basis,
                fingerprint=self.fingerprint(case["id"]), status="needs_review",
                decisions=None, document_decision=None, reviewed_by=None,
                decided_at=None, minimum_reference_days=None, error=None,
                analysis_work={"pending": [], "reused": [r["id"] for r in current["requests"]],
                               "reason": "selection", "mode": "incremental"},
                timings={"assessment_calls": 0, "evaluated_requests": 0,
                         "reused_requests": len(current["requests"]), "total_seconds": 0},
            )
            return True

    def start(self, case_id, body):
        with self.identification.lock if self.identification else nullcontext(), self.lock:
            self.cases.assert_open(case_id)
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
            if (self.settings.initial_classification_provider == "openai"
                    and not self.settings.api_key and self.engine is None):
                raise ValueError(
                    "Configura la IA para analizar la revisión inicial; no se simulan resultados."
                )
            if (
                self.engine is None
                and self.settings.initial_classification_provider == "jev"
                and not get_jev_key()
            ):
                raise ValueError(
                    "Configura TYPESAFE_API_KEY en el archivo indicado por "
                    "PQRS_CLARO_JEV_KEY_FILE (o .env.jev.local) para clasificar con JEV 1.14."
                )
            next_row = {**previous, "analysis_scope": CLASSIFICATION_SCOPE}
            _, plan = self.analysis_plan(case_id, next_row, full=body.mode == "full")
            fingerprint = self.fingerprint(case_id, scope=CLASSIFICATION_SCOPE)
            if (not plan["pending"] and previous.get("fingerprint") == fingerprint
                    and previous["status"] in {"needs_review", "approved", "routed"}):
                return self.get(case_id)
            row = self.save(
                previous,
                analysis_scope=CLASSIFICATION_SCOPE,
                analysis_cache=None if body.mode == "full" else previous.get("analysis_cache"),
                analysis_work={"pending": plan["pending"], "reused": list(plan["reused"]),
                               "reason": plan["reason"], "mode": body.mode},
                status="running",
                policy_version=POLICY_VERSION,
                fingerprint=fingerprint,
                error=None,
                report=None,
                decisions=None,
                document_decision=None,
                minimum_reference_days=None,
                selection_basis=None,
                reviewed_by=None,
                decided_at=None,
            )
            self.active.add(case_id)
            self.pool.submit(self.run, row)
            return self.get(case_id)

    @track_case("classification_inputs", "case_id")
    def payload(self, case_id):
        case = self.cases.get(case_id)
        if hashlib.sha256(self.cases.original(case_id).read_bytes()).hexdigest() != case["sha256"]:
            raise ValueError("El original de la petición cambió en disco.")
        return {
            "identification": case["identification"],
            "pages": case["pages"],
            "preanalysis": self.preanalysis(case),
            "candidates": [],
            "scope": {
                "mode": CLASSIFICATION_SCOPE, "library_search": "not_requested",
                "linked_collections": [], "readable_sources": 0,
                "history_available": False, "catalog": [],
                "retrieved_candidates": 0, "selected_candidates": 0,
                "candidates_limited": False,
                "note": "Identificación y tipo de cada petición a partir del original. "
                        "Las fuentes se consultan al continuar a Redacción.",
            },
        }

    @track_case("initial_review", "row")
    def run(self, row):
        case_id = row["case_id"]
        started = perf_counter()
        owned_engine = None
        try:
            context, plan = self.analysis_plan(case_id, row,
                                               full=row["analysis_work"]["mode"] == "full")
            payload = self.payload(case_id)
            full_identification = deepcopy(payload["identification"])
            enriched = build_source_requests({"id": case_id,
                                               "identification": full_identification})
            payload["identification"] = {**full_identification, "requests": [
                r for r in enriched if r["id"] in plan["pending"]
            ]}
            retrieval_seconds = round(perf_counter() - started, 3)
            if self.settings.initial_classification_provider not in {"openai", "jev"}:
                raise ValueError("Proveedor de clasificación no válido.")
            if plan["pending"]:
                engine = self.engine
                if engine is None:
                    owned_engine = engine = PetitionClassificationEngine(self.settings)
                report = materialize(engine.assess(payload), payload)
            else:
                report = deepcopy(row["analysis_cache"]["report"])
            fresh = {r["request_id"]: r for r in report["requests"]}
            for key in plan["pending"]:
                plan["entries"][key] = {"key": plan["keys"][key], "report": fresh[key]}
            report["requests"] = [deepcopy(plan["reused"].get(key, fresh.get(key)))
                                  for key in plan["keys"]]
            if plan["reused"]:
                report["warnings"] = list(dict.fromkeys([
                    *row["analysis_cache"]["report"]["warnings"], *report["warnings"]
                ]))
            cache = {"version": CACHE_VERSION, "context": context,
                     "entries": plan["entries"], "report": deepcopy(report)}
            if payload["scope"]["candidates_limited"]:
                report["warnings"].append(
                    "La revisión inicial consultó 96 fragmentos priorizados entre las peticiones. "
                    "La búsqueda es parcial; no demuestra ausencia de antecedentes o documentos."
                )
            with self.lock:
                if row["fingerprint"] != self.fingerprint(case_id):
                    raise Conflict("Cambiaron las entradas durante el análisis. Vuelve a analizar.")
                self.save(
                    row,
                    status="needs_review",
                    report=report,
                    analysis_cache=cache,
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
                    timings={"assessment_calls": int(bool(plan["pending"])),
                             "evaluated_requests": len(plan["pending"]),
                             "reused_requests": len(plan["reused"]),
                             "retrieval_seconds": retrieval_seconds,
                             "total_seconds": round(perf_counter() - started, 3)},
                )
        except Exception as exc:
            with self.lock:
                self.save(row, status="error", error=user_error(exc), decisions=None)
        finally:
            if owned_engine:
                owned_engine.close()
            with self.lock:
                self.active.discard(case_id)

    def decide(self, case_id, body):
        with (
            self.identification.lock if self.identification else nullcontext(),
            self.lock,
            self.library.lock,
        ):
            self.cases.assert_open(case_id)
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
                    **self.saved(case_id),
                    **{k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "enabled",
                        "stale",
                        "legacy_report",
                        "can_prepare",
                        "classification_provider",
                        "classification_model",
                        "next_analysis",
                    }
                    },
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
                {k: v for k, v in json.loads(r[0]).items() if k != "analysis_cache"}
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
    def get(case_id: str, compact: bool = False):
        result = service.get(case_id)
        if compact:
            result = {k: v for k, v in result.items() if k != "consulted_sources"}
            if result.get("scope"):
                result["scope"] = {k: v for k, v in result["scope"].items() if k != "catalog"}
        return result

    @router.post("/analyze", status_code=202)
    def analyze(case_id: str, body: IntakeStart):
        return service.start(case_id, body)

    @router.put("/decision")
    def decide(case_id: str, body: IntakeDecision):
        return service.decide(case_id, body)

    @router.put("/pilot-mode")
    def pilot_mode(case_id: str, body: PilotReviewMode):
        return service.pilot_mode(case_id, body)

    @router.get("/history")
    def history(case_id: str):
        return {"events": service.history(case_id)}

    return router
