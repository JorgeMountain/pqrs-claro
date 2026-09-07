"""Borradores por solicitud con fuentes vigentes, avance durable y revisión humana."""

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from .draft_store import DraftStore
from .models import DomainError
from .service import user_error
from .source_library import digest
from .storage import Conflict, now

DRAFT_VERSION = 2


class _InputsChanged(Exception):
    """Las entradas dejaron de corresponder al borrador que se está preparando."""


class _GuardedEngine:
    def __init__(self, engine, check):
        self.engine, self.check_inputs = engine, check

    def plan(self, *args):
        self.check_inputs()
        return self.engine.plan(*args)

    def write(self, *args):
        self.check_inputs()
        return self.engine.write(*args)

    def check(self, *args):
        self.check_inputs()
        return self.engine.check(*args)


class DraftService:
    def __init__(self, settings, cases, library, sources_service, engine=None):
        self.settings, self.cases, self.library = settings, cases, library
        self.sources_service, self.engine = sources_service, engine
        self.store = DraftStore(settings.data_dir)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="drafts")
        self.lock = threading.RLock()
        self.active = set()

    def _fingerprint(self, case, source_run):
        return digest(
            {
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
                and source_run["status"] == "ready"
                and not source_run.get("stale")
            )
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
            if (
                len(findings) != len(request_ids)
                or {finding.get("request_id") for finding in findings} != set(request_ids)
                or any(finding.get("status") == "error" for finding in findings)
            ):
                raise Conflict("El mapa no contiene una evaluación completa de cada solicitud.")
            reconciled = {}
            for finding in findings:
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

    def start(self, case_id, version):
        with self.lock:
            if case_id in self.active:
                raise Conflict("Los borradores de este expediente ya se están preparando.")
            case, source_run, findings, fingerprint = self._inputs(case_id, version)
            if not self.settings.api_key and self.engine is None:
                raise ValueError("Falta configurar OpenAI para preparar los borradores.")
            previous = self.store.latest(case_id)
            if (
                previous
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
                results=[],
                completed_count=0,
                total_count=len(findings),
                current_request_id=None,
                current_step=None,
                error=None,
                started_at=now(),
                finished_at=None,
                requires_human_review=True,
            )
            self.store.save(run)
            self.active.add(case_id)
            self.pool.submit(self.run, case, findings, run)
            return self.get(case_id)

    def _ensure_current(self, case_id, fingerprint, finding=None, *, full=False):
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
            supports=finding["supports"],
            error=None,
        )

    def run(self, case, findings, run):
        try:
            from .draft_engine import OpenAIDraftEngine
            from .draft_graph import build_draft_graph

            engine = self.engine or OpenAIDraftEngine(self.settings.api_key, self.settings.model)
            with SqliteSaver.from_conn_string(
                str(self.settings.data_dir / "draft_checkpoints.sqlite")
            ) as saver:
                for raw_request in case["identification"]["requests"]:
                    request = {
                        **raw_request,
                        "case_id": case["id"],
                        "allowed_collection_ids": case["allowed_collection_ids"],
                    }
                    finding = findings[request["id"]]
                    self._ensure_current(case["id"], run["fingerprint"], finding)
                    guarded = _GuardedEngine(
                        engine,
                        lambda f=finding: self._ensure_current(case["id"], run["fingerprint"], f),
                    )
                    graph = build_draft_graph(guarded, saver)
                    config = {
                        "configurable": {
                            "thread_id": f"{case['id']}:{request['id']}:{run['fingerprint']}"
                        }
                    }
                    run.update(current_request_id=request["id"], current_step="planificar")
                    self.store.save(run)
                    state = {}
                    try:
                        checkpoint = graph.get_state(config)
                        state = deepcopy(checkpoint.values)
                        if not state.get("checks") or checkpoint.next:
                            initial = None if state else {"request": request, "finding": finding}
                            if checkpoint.next:
                                run["current_step"] = checkpoint.next[0]
                                self.store.save(run)
                            for update in graph.stream(initial, config, stream_mode="updates"):
                                for node, values in update.items():
                                    state.update(values)
                                    run["current_step"] = {
                                        "planificar": "redactar",
                                        "redactar": "comprobar",
                                        "comprobar": None,
                                    }.get(node)
                                    self.store.save(run)
                                self._ensure_current(case["id"], run["fingerprint"], finding)
                        run["results"].append(self._result(request, finding, state))
                    except _InputsChanged:
                        if state.get("plan") or state.get("draft"):
                            run["results"].append(self._result(request, finding, state))
                        raise
                    except Exception as exc:
                        # Un proveedor no puede filtrar su respuesta cruda ni su clave al API.
                        error = (
                            user_error(exc)
                            if isinstance(exc, DomainError)
                            else user_error(
                                exc if not isinstance(exc, ValueError) else RuntimeError()
                            )
                        )
                        result = self._result(request, finding, state)
                        result.update(status="error", error=error)
                        run["results"].append(result)
                    run["completed_count"] = len(run["results"])
                    self.store.save(run)
                self._ensure_current(case["id"], run["fingerprint"], full=True)
            errors = sum(result["status"] == "error" for result in run["results"])
            pending = any(result["status"] != "needs_review" for result in run["results"])
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
