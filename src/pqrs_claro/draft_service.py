"""Borradores por solicitud con fuentes vigentes, avance durable y revisión humana."""

import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from time import perf_counter
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from .draft_repair import repair_targets
from .draft_store import DraftStore
from .intake_drafting import drafting_context
from .models import DomainError
from .performance_metrics import operation, submit_context, track_case
from .service import user_error
from .source_context import build_source_requests
from .source_library import digest
from .storage import Conflict, now

DRAFT_VERSION = 12


class _InputsChanged(Exception):
    """Las entradas dejaron de corresponder al borrador que se está preparando."""


class _GuardedEngine:
    def __init__(self, engine, check):
        self.engine, self.check_inputs = engine, check
        self.timings = {}

    def _call(self, method, args):
        self.check_inputs()
        started = perf_counter()
        try:
            return getattr(self.engine, method)(*args)
        finally:
            timing = self.timings.setdefault(method, {"calls": 0, "seconds": 0.0})
            timing["calls"] += 1
            timing["seconds"] = round(timing["seconds"] + perf_counter() - started, 3)

    def plan(self, *args):
        return self._call("plan", args)

    def write(self, *args):
        return self._call("write", args)

    def check(self, *args):
        return self._call("check", args)

    @property
    def can_repair(self):
        return callable(getattr(self.engine, "repair", None))

    def repair(self, *args):
        return self._call("repair", args)


class DraftService:
    def __init__(self, settings, cases, library, sources_service, engine=None):
        self.settings, self.cases, self.library = settings, cases, library
        self.sources_service, self.engine = sources_service, engine
        self.store = DraftStore(settings.data_dir)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="drafts")
        self.lock = threading.RLock()
        self.active = set()
        self.reviews = None

    def _fingerprint(self, case, source_run):
        intake = getattr(self, "initial_review", None)
        initial_inputs = {}
        if intake and intake.enabled:
            initial = intake.saved(case["id"])
            initial_inputs = {
                "initial_review_revision": initial["revision"],
                "initial_review_status": initial["status"],
            }
        return digest(
            {
                **initial_inputs,
                "identification": case["identification"],
                "case_version": case["version"],
                "case_status": case["status"],
                "source_run_id": source_run.get("id"),
                "source_results": source_run.get("results", []),
                "source_fingerprint": source_run.get("fingerprint"),
                "model": self.settings.model,
                "draft_version": DRAFT_VERSION,
            }
        )

    def _current(self, case_id):
        with self.library.lock:
            case = self.cases.get(case_id)
            source_run = self.sources_service.get(case_id)
            current = (
                case["status"] == "confirmed"
                and source_run["status"] in {"ready", "error"}
                and not source_run.get("stale")
            )
            if getattr(self, "initial_review", None) and self.initial_review.enabled:
                current = current and self.initial_review.get(case_id)["can_prepare"]
            return case, source_run, self._fingerprint(case, source_run), current

    def get(self, case_id):
        case, _, fingerprint, current = self._current(case_id)
        run = self.store.latest(case_id)
        if not run:
            return dict(
                id=None,
                case_id=case_id,
                status="idle",
                stale=False,
                results=[],
                completed_count=0,
                total_count=case["request_count"],
                current_request_id=None,
                current_step=None,
                error=None,
                requires_human_review=True,
            )
        stale = run.get("stale", False) or not current or run["fingerprint"] != fingerprint
        if not stale:
            try:
                self.cases.original(case_id)
                for source_id in {
                    support["source_id"]
                    for result in run["results"]
                    for support in result.get("supports", [])
                }:
                    self.library.original(source_id, case_id)
            except (ValueError, KeyError):
                stale = True
        return {**run, "status": "stale" if stale else run["status"], "stale": stale}

    def _inputs(self, case_id, version):
        with self.library.lock:
            case, source_run, fingerprint, current = self._current(case_id)
            if case["status"] != "confirmed":
                raise Conflict("Confirma primero las solicitudes identificadas.")
            if case["version"] != version:
                raise Conflict("El expediente cambió. Recarga antes de preparar borradores.")
            if not current:
                raise Conflict(
                    "Actualiza y completa el mapa de fuentes antes de preparar borradores."
                )
            self.cases.original(case_id)
            _, _, chunks, source_fingerprint = self.sources_service.inputs(case_id)
            if source_fingerprint != source_run["fingerprint"]:
                raise Conflict("Las fuentes cambiaron. Actualiza su mapa antes de continuar.")
            by_chunk = {chunk["chunk_id"]: chunk for chunk in chunks}
            findings = source_run.get("results", [])
            request_ids = [request["id"] for request in case["identification"]["requests"]]
            if len(findings) != len(request_ids) or {
                finding.get("request_id") for finding in findings
            } != set(request_ids):
                raise Conflict("El mapa no contiene una evaluación completa de cada solicitud.")
            reconciled = {}
            for finding in findings:
                if finding.get("status") == "error":
                    continue
                supports, seen = [], set()
                for support in finding.get("supports", []):
                    chunk_id = support.get("chunk_id")
                    chunk = by_chunk.get(chunk_id)
                    fields = (
                        "source_id",
                        "quote",
                        "page",
                        "line_start",
                        "line_end",
                        "version",
                        "sha256",
                    )
                    if (
                        not chunk
                        or chunk_id in seen
                        or any(support.get(field) != chunk.get(field) for field in fields)
                    ):
                        raise Conflict(
                            "Una cita del mapa dejó de corresponder a las fuentes permitidas."
                        )
                    seen.add(chunk_id)
                    supports.append(
                        {**chunk, "reason": support.get("reason", ""), "role": support.get("role")}
                    )
                documents, document_ids = [], set()
                selected_ids = {support["source_id"] for support in supports}
                for document in finding.get("candidate_documents", []):
                    source_id = document.get("source_id")
                    if source_id in document_ids or not document.get("chunks"):
                        raise Conflict("El inventario de candidatos requiere actualizar su mapa.")
                    document_ids.add(source_id)
                    verified_chunks, chunk_ids = [], set()
                    original = None
                    for fragment in document["chunks"]:
                        chunk_id = fragment.get("chunk_id")
                        original = by_chunk.get(chunk_id)
                        if (
                            not original
                            or chunk_id in chunk_ids
                            or any(
                                document.get(key) != original.get(key)
                                for key in ("source_id", "document_id", "version")
                            )
                            or any(
                                fragment.get(key) != original.get(key)
                                for key in (
                                    "quote",
                                    "page",
                                    "line_start",
                                    "line_end",
                                    "location_kind",
                                )
                            )
                        ):
                            raise Conflict(
                                "Un candidato no corresponde a las fuentes permitidas del mapa."
                            )
                        chunk_ids.add(chunk_id)
                        verified_chunks.append(
                            {
                                key: original.get(key)
                                for key in (
                                    "chunk_id",
                                    "page",
                                    "line_start",
                                    "line_end",
                                    "quote",
                                    "location_kind",
                                )
                            }
                        )
                    documents.append(
                        {
                            **{
                                key: original.get(key)
                                for key in (
                                    "source_id",
                                    "document_id",
                                    "version",
                                    "title",
                                    "filename",
                                    "category",
                                )
                            },
                            "location_status": "candidate_located",
                            "selected_as_support": source_id in selected_ids,
                            "chunks": verified_chunks,
                        }
                    )
                reconciled[finding["request_id"]] = {
                    **finding,
                    "supports": supports,
                    "candidate_documents": documents,
                }
            case["allowed_collection_ids"] = self.library.linked_collections(case_id)
            return case, source_run, reconciled, fingerprint

    def start(self, case_id, version, *, ready_only=False):
        with self.lock:
            self.cases.assert_open(case_id)
            if getattr(self, "initial_review", None):
                self.initial_review.assert_allowed(case_id)
            if case_id in self.active:
                raise Conflict("Los borradores de este expediente ya se están preparando.")
            case, source_run, findings, fingerprint = self._inputs(case_id, version)
            if not findings and not ready_only:
                raise Conflict(
                    "No hay solicitudes con un análisis de fuentes válido para redactar."
                )
            review_snapshots = {}
            if ready_only:
                rows = {r["request_id"]: r for r in self.reviews.get(case_id)["requests"]}
                findings = {
                    rid: self._reviewed_finding(finding, rows[rid])
                    for rid, finding in findings.items()
                    if rid in rows and self._ready_for_draft(rows[rid], finding)
                }
                review_snapshots = {rid: self._review_input(rows[rid]) for rid in findings}
                if not findings:
                    return self.get(case_id)
            if not self.settings.api_key and self.engine is None:
                raise ValueError("Falta configurar OpenAI para preparar los borradores.")
            previous = self.store.latest(case_id)
            if (
                not ready_only
                and previous
                and previous["fingerprint"] == fingerprint
                and previous["status"] in {"ready", "partial"}
                and not previous.get("stale")
                and not any(result["status"] == "error" for result in previous["results"])
            ):
                return self.get(case_id)
            run = dict(
                id=uuid4().hex,
                case_id=case_id,
                status="running",
                stale=False,
                fingerprint=fingerprint,
                source_run_id=source_run["id"],
                source_fingerprint=source_run["fingerprint"],
                case_version=case["version"],
                model=self.settings.model,
                draft_version=DRAFT_VERSION,
                results=[
                    r
                    for r in (previous or {}).get("results", [])
                    if ready_only
                    and previous["fingerprint"] == fingerprint
                    and r["request_id"] not in findings
                ],
                completed_count=0,
                total_count=case["request_count"],
                selected_request_ids=list(findings),
                review_snapshots=review_snapshots,
                current_request_id=None,
                current_step=None,
                error=None,
                started_at=now(),
                finished_at=None,
                requires_human_review=True,
            )
            run["completed_count"] = len(run["results"])
            self.store.save(run)
            self.active.add(case_id)
            self.pool.submit(self.run, case, findings, run)
            return self.get(case_id)

    @staticmethod
    def _review_input(row):
        return digest(
            {key: row.get(key) for key in ("pending", "facts", "paragraphs", "base_fingerprint")}
        )

    @staticmethod
    def _ready_for_draft(row, finding):
        return (
            not row.get("stale")
            and not row.get("paragraphs")
            and finding.get("status") != "error"
            and "analysis_error" not in finding.get("evidence_states", [])
            and not any(
                p.get("blocks_approval", True)
                and (not p.get("resolution") or p["resolution"].get("action") == "open")
                for p in row.get("pending", [])
            )
        )

    @staticmethod
    def _reviewed_finding(finding, row):
        value = deepcopy(finding)
        opened, decisions = [], []
        for pending in row.get("pending", []):
            resolution = pending.get("resolution")
            if resolution and resolution.get("action") != "open":
                decisions.append(deepcopy(pending))
            else:
                opened.append(deepcopy(pending))
        # Keep decisions and their attribution as inputs, never as final approval.
        closed_checks = [
            {
                **p,
                "resolution": {
                    "status": "resolved",
                    "kind": "human_decision",
                    "decision": deepcopy(p["resolution"]),
                },
            }
            for p in decisions
        ]
        value.update(missing=opened, actions=[], checks=closed_checks, human_decisions=decisions)
        selected = {s["chunk_id"]: s for s in value["supports"]}
        cited = {cid for p in decisions for cid in p["resolution"].get("cited_chunk_ids", [])}
        for source in row["available_supports"]:
            if source["chunk_id"] in cited:
                selected[source["chunk_id"]] = deepcopy(source)
        value["supports"] = list(selected.values())
        return value

    def _ensure_current(self, case_id, fingerprint, finding=None, *, full=False):
        if getattr(self, "initial_review", None):
            self.initial_review.assert_allowed(case_id)
        _, source_run, current_fingerprint, current = self._current(case_id)
        if not current or current_fingerprint != fingerprint:
            raise _InputsChanged()
        try:
            self.cases.original(case_id)
            if full:
                _, _, _, source_fingerprint = self.sources_service.inputs(case_id)
                if source_fingerprint != source_run["fingerprint"]:
                    raise _InputsChanged()
            else:
                source_ids = {s["source_id"] for s in (finding or {}).get("supports", [])}
                source_ids.update(
                    document["source_id"]
                    for document in (finding or {}).get("candidate_documents", [])
                )
                for source_id in source_ids:
                    self.library.original(source_id, case_id)
        except (ValueError, KeyError):
            raise _InputsChanged() from None

    @staticmethod
    def _result(request, finding, state):
        checks = state.get("checks") or {
            "status": "needs_changes",
            "issues": [],
            "local_checks": [],
        }
        draft = state.get("draft") or {"status": "needs_evidence", "paragraphs": [], "pending": []}
        status = "needs_evidence" if checks["status"] != "passed" else draft["status"]
        return dict(
            request_id=request["id"],
            label=request["label"],
            title=request["title"],
            status=status,
            plan=state.get("plan"),
            draft={**draft, "status": status},
            checks=checks,
            repair=deepcopy(state.get("repair")),
            supports=finding["supports"],
            request_intent=finding.get("request_intent"),
            evidence_states=deepcopy(finding.get("evidence_states", [])),
            source_checks=deepcopy(finding.get("checks", [])),
            verifications=deepcopy(finding.get("verifications", [])),
            sufficiency=deepcopy(finding.get("sufficiency", {})),
            error=None,
        )

    @track_case("draft", "case")
    def run(self, case, findings, run):
        try:
            from .draft_engine import OpenAIDraftEngine
            from .draft_graph import build_draft_graph

            engine = self.engine or OpenAIDraftEngine(self.settings.api_key, self.settings.model)
            with SqliteSaver.from_conn_string(
                str(self.settings.data_dir / "draft_checkpoints.sqlite")
            ) as warmup:
                warmup.get_tuple({"configurable": {"thread_id": "__schema_initialization__"}})
            requests = [
                r
                for r in build_source_requests(
                    case, allowed_collection_ids=case["allowed_collection_ids"]
                )
                if r["id"] in findings
            ]
            intake = getattr(self, "initial_review", None)
            if intake and intake.enabled and not intake.pilot_bypassed(case["id"]):
                initial_review = intake.saved(case["id"])
                requests = [
                    {**request, "initial_review": drafting_context(initial_review, request["id"])}
                    for request in requests
                ]
            order = {r["id"]: i for i, r in enumerate(case["identification"]["requests"])}
            concurrency = min(6, max(1, self.settings.draft_concurrency))
            run.update(
                concurrency=concurrency, request_states={r["id"]: "queued" for r in requests}
            )
            progress_lock = threading.RLock()

            def progress(request_id, step):
                with progress_lock:
                    run["request_states"][request_id] = step or "completed"
                    run.update(current_request_id=request_id, current_step=step)
                    self.store.save(run)

            def evaluate(request):
                with operation("draft.request", request_id=request["id"]):
                    return evaluate_request(request)

            def evaluate_request(request):
                started = perf_counter()
                validation_seconds = 0.0
                validation_calls = 0
                finding = deepcopy(findings[request["id"]])
                # Absent and empty decisions have identical meaning in both draft modes.
                finding.setdefault("human_decisions", [])
                state = {}

                def validate_inputs():
                    self._ensure_current(case["id"], run["fingerprint"], finding)
                    expected = run.get("review_snapshots", {}).get(request["id"])
                    if (
                        expected
                        and self._review_input(self.reviews.store.get(case["id"], request["id"]))
                        != expected
                    ):
                        raise DomainError(
                            "Los puntos de esta solicitud cambiaron durante la redacción. "
                            "Se conserva el avance; vuelve a prepararla."
                        )

                def check_inputs():
                    nonlocal validation_seconds, validation_calls
                    before = perf_counter()
                    try:
                        validate_inputs()
                    finally:
                        validation_seconds += perf_counter() - before
                        validation_calls += 1

                guarded = _GuardedEngine(engine, check_inputs)

                def result_with_timings():
                    result = self._result(request, finding, state)
                    result["timings"] = {
                        "total_seconds": round(perf_counter() - started, 3),
                        "validation_seconds": round(validation_seconds, 3),
                        "validation_calls": validation_calls,
                        "engine": deepcopy(guarded.timings),
                    }
                    return result

                try:
                    check_inputs()
                    with SqliteSaver.from_conn_string(
                        str(self.settings.data_dir / "draft_checkpoints.sqlite")
                    ) as saver:
                        graph = build_draft_graph(guarded, saver)
                        key = digest(
                            {
                                "request": request,
                                "finding": finding,
                                "model": self.settings.model,
                                "version": DRAFT_VERSION,
                                "engine_policy": getattr(engine, "cache_key", None),
                                "original": case["sha256"],
                            }
                        )
                        config = {
                            "configurable": {"thread_id": f"{case['id']}:{request['id']}:{key}"}
                        }
                        progress(request["id"], "planificar")
                        checkpoint = graph.get_state(config)
                        state = deepcopy(checkpoint.values)
                        if not state.get("checks") or checkpoint.next:
                            initial = None if state else {"request": request, "finding": finding}
                            for update in graph.stream(initial, config, stream_mode="updates"):
                                for node, values in update.items():
                                    state.update(values)
                                    step = {
                                        "planificar": "redactar",
                                        "redactar": "comprobar",
                                        "comprobar": None,
                                        "ajustar_citas": "recomprobar",
                                        "recomprobar": None,
                                    }.get(node)
                                    if (
                                        node == "comprobar"
                                        and guarded.can_repair
                                        and repair_targets(state["checks"], state["draft"])
                                    ):
                                        step = "ajustar_citas"
                                    progress(request["id"], step)
                                check_inputs()
                        check_inputs()
                        return result_with_timings()
                except _InputsChanged:
                    # Retain any text already produced; the run is marked stale below.
                    return result_with_timings()
                except Exception as exc:
                    error = user_error(
                        exc
                        if not isinstance(exc, ValueError) or isinstance(exc, DomainError)
                        else RuntimeError()
                    )
                    result = result_with_timings()
                    result.update(status="error", error=error)
                    return result

            with ThreadPoolExecutor(
                max_workers=concurrency, thread_name_prefix="draft-request"
            ) as workers:
                pending = {}
                remaining = iter(requests)

                def fill_slots():
                    while len(pending) < concurrency:
                        request = next(remaining, None)
                        if request is None:
                            break
                        pending[submit_context(workers, evaluate, request)] = request

                fill_slots()
                while pending:
                    finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in finished:
                        request = pending.pop(future)
                        result = future.result()
                        with progress_lock:
                            run["results"].append(result)
                            run["results"].sort(key=lambda item: order[item["request_id"]])
                            run["request_states"][request["id"]] = (
                                "error" if result["status"] == "error" else "completed"
                            )
                            run["completed_count"] = len(run["results"])
                            self.store.save(run)
                    fill_slots()
            self._ensure_current(case["id"], run["fingerprint"], full=True)
            errors = sum(result["status"] == "error" for result in run["results"])
            pending = len(run["results"]) < run["total_count"] or any(
                result["status"] != "needs_review" for result in run["results"]
            )
            run.update(
                status="failed"
                if errors == run["total_count"]
                else "partial"
                if pending
                else "ready",
                error=f"No se pudieron preparar {errors} solicitudes. "
                "Reintenta para recuperar el avance."
                if errors
                else None,
            )
        except _InputsChanged:
            run.update(
                status="stale",
                stale=True,
                error="Las solicitudes o sus fuentes cambiaron. "
                "Actualiza el mapa y los borradores.",
            )
        except Exception as exc:
            run.update(
                status="failed",
                error=user_error(exc if not isinstance(exc, ValueError) else RuntimeError()),
            )
        finally:
            run.update(current_request_id=None, current_step=None, finished_at=now())
            self.store.save(run)
            with self.lock:
                self.active.discard(case["id"])

    def recover(self):
        self.store.recover()

    def close(self):
        self.pool.shutdown(wait=True)
