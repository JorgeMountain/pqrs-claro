"""Coordina búsquedas por solicitud sin modificar la identificación confirmada."""

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from .evidence_contract import apply_evidence_contract, catalog_audit, group_checks
from .request_intent import classify_request_intent
from .service import user_error
from .source_assessment import OpenAISourceAssessor
from .source_context import build_source_requests
from .source_graph import build_source_graph
from .source_library import digest
from .source_retrieval import RetrievalIndex, retrieve
from .source_semantic import MODEL_FILE, MODEL_KEY, MODEL_REVISION, SemanticIndex
from .storage import Conflict, now

SOURCE_ANALYSIS_VERSION = 14


def retrieval_signature(data_dir):
    return {
        "version": SOURCE_ANALYSIS_VERSION,
        "semantic_model": MODEL_KEY,
        "semantic_installed": (
            data_dir / "semantic" / "models" / MODEL_REVISION / MODEL_FILE
        ).is_file(),
    }


class SourceService:
    def __init__(self, settings, cases, library, *, assessor=None, verifications=None):
        self.settings, self.cases, self.library = settings, cases, library
        self.assessor = assessor
        self.verifications = verifications
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sources")
        self.lock = threading.RLock()
        self.active = set()

    def catalog(self, case_id):
        linked = set(self.library.linked_collections(case_id))
        return [source for source in self.library.list(case_id)
                if source.get("is_latest", True) and source.get("validity") != "superseded"
                and (not source.get("collection_id") or source["collection_id"] in linked)
                and source.get("category") != "previous_response"]

    def verification_fingerprint(self, case_id, sources):
        return self.verifications.fingerprint(case_id, sources) if self.verifications else None

    def inputs(self, case_id):
        with self.library.lock:
            case = self.cases.get(case_id)
            case["allowed_collection_ids"] = self.library.linked_collections(case_id)
            sources, chunks = self.library.snapshot(case_id)
            fingerprint = digest(
                {
                    "identification": case["identification"],
                    "catalog": self.catalog(case_id),
                    "verifications": self.verification_fingerprint(case_id, sources),
                    "sources": sources,
                    "model": self.settings.model,
                    "analysis_version": SOURCE_ANALYSIS_VERSION,
                    "retrieval": retrieval_signature(self.settings.data_dir),
                    "collections": case["allowed_collection_ids"],
                }
            )
        return case, sources, chunks, fingerprint

    def get(self, case_id):
        case = self.cases.get(case_id)
        run = self.library.latest_run(case_id)
        sources = self.library.eligible(case_id)
        fingerprint = digest(
            {
                "identification": case["identification"],
                "catalog": self.catalog(case_id),
                "verifications": self.verification_fingerprint(case_id, sources),
                "sources": sources,
                "model": self.settings.model,
                "analysis_version": SOURCE_ANALYSIS_VERSION,
                "retrieval": retrieval_signature(self.settings.data_dir),
                "collections": self.library.linked_collections(case_id),
            }
        )
        if not run:
            return dict(
                status="idle",
                results=[],
                source_count=len(sources),
                searched_at=None,
                error=None,
                completed_count=0,
                total_count=case["request_count"],
                stale=False,
            )
        stale = run["fingerprint"] != fingerprint
        return {
            **run,
            "status": "stale" if stale and run["status"] != "running" else run["status"],
            "stale": stale,
            "source_count": len(sources),
        }

    def start(self, case_id, version):
        with self.lock:
            case, sources, chunks, fingerprint = self.inputs(case_id)
            if case["status"] != "confirmed":
                raise Conflict("Confirma primero las solicitudes identificadas.")
            if case["version"] != version:
                raise Conflict("El expediente cambió. Recarga antes de buscar fuentes.")
            if case_id in self.active:
                raise Conflict("La búsqueda de este expediente ya está en curso.")
            if not self.settings.api_key and self.assessor is None:
                raise ValueError(
                    "Falta configurar OpenAI para evaluar la pertinencia de las fuentes."
                )
            if not sources:
                raise ValueError(
                    "Carga al menos una norma o un soporte de este caso antes de buscar."
                )
            previous = self.library.latest_run(case_id)
            if (
                previous
                and previous["fingerprint"] == fingerprint
                and previous["status"] == "ready"
                and not (
                    previous.get("retrieval_warning")
                    and retrieval_signature(self.settings.data_dir)["semantic_installed"]
                )
            ):
                return self.get(case_id)
            retrieval_attempt = ""
            if previous and previous["fingerprint"] == fingerprint:
                retrieval_attempt = previous.get("retrieval_attempt", "")
            if (
                previous
                and previous.get("retrieval_warning")
                and retrieval_signature(self.settings.data_dir)["semantic_installed"]
            ):
                retrieval_attempt = uuid4().hex
            # La aplicación de una comprobación humana cambia el resultado, pero
            # no exige repetir recuperación/IA de fuentes idénticas.
            analysis_fingerprint = digest({
                "analysis_version": SOURCE_ANALYSIS_VERSION,
                "identification": case["identification"], "sources": sources,
                "catalog": self.catalog(case_id), "model": self.settings.model,
                "retrieval": retrieval_signature(self.settings.data_dir),
                "collections": case["allowed_collection_ids"],
            })
            run = dict(
                id=uuid4().hex,
                analysis_fingerprint=analysis_fingerprint,
                case_id=case_id,
                status="running",
                fingerprint=fingerprint,
                results=[],
                source_count=len(sources),
                source_snapshot=sources,
                allowed_collection_ids=case["allowed_collection_ids"],
                searched_at=now(),
                error=None,
                completed_count=0,
                total_count=len(case["identification"]["requests"]),
                stale=False,
                retrieval_attempt=retrieval_attempt,
            )
            self.library.save_run(run)
            self.active.add(case_id)
            self.pool.submit(self.run, case, chunks, run)
            return self.get(case_id)

    def run(self, case, chunks, run):
        try:
            assessor = self.assessor or OpenAISourceAssessor(
                self.settings.api_key, self.settings.model
            )
            catalog = self.catalog(case["id"])
            applications = (self.verifications.active_applications(case)
                            if self.verifications else [])
            lexical = RetrievalIndex(chunks)
            semantic = SemanticIndex(self.settings.data_dir / "semantic")
            last_progress_save = 0.0

            def index_progress(progress):
                nonlocal last_progress_save
                run["retrieval_progress"] = {"phase": "indexing", **progress}
                if time.monotonic() - last_progress_save >= 2:
                    self.library.save_run(run)
                    last_progress_save = time.monotonic()

            semantic.prepare(chunks, progress=index_progress)
            run["retrieval_warning"] = semantic.warning
            run["retrieval_progress"] = {"phase": "searching", **semantic.diagnostics}
            requests = build_source_requests(case, allowed_collection_ids=run.get("allowed_collection_ids", []))
            order = {request["id"]: i for i, request in enumerate(requests)}
            retrieval_lock = threading.RLock()
            concurrency = min(3, max(1, getattr(self.settings, "source_concurrency", 3)))
            run["concurrency"] = concurrency
            run["request_states"] = {request["id"]: "queued" for request in requests}
            # Initialize SQLite/WAL once before concurrent connections open it.
            with SqliteSaver.from_conn_string(str(self.settings.data_dir / "source_checkpoints.sqlite")) as warmup:
                warmup.get_tuple({"configurable": {"thread_id": "__schema_initialization__"}})

            def locate(request, _):
                with retrieval_lock:
                    return retrieve(request, chunks, index=lexical, semantic=semantic)

            def evaluate(request):
                with SqliteSaver.from_conn_string(
                    str(self.settings.data_dir / "source_checkpoints.sqlite")
                ) as saver:
                    graph = build_source_graph(locate, assessor, saver)
                    request["request_intent"] = classify_request_intent(request)
                    analysis_key = run.get("analysis_fingerprint", run["fingerprint"])
                    thread_id = f"{case['id']}:{request['id']}:{analysis_key}"
                    if run.get("retrieval_attempt"):
                        thread_id += f":{run['retrieval_attempt']}"
                    config = {"configurable": {"thread_id": thread_id}}
                    try:
                        snapshot = graph.get_state(config)
                        if snapshot.values.get("finding") and not snapshot.next:
                            finding = snapshot.values["finding"]
                        else:
                            initial = (
                                None if snapshot.values else {"request": request, "chunks": []}
                            )
                            finding = graph.invoke(initial, config)["finding"]
                        scoped_request = catalog_audit(request, finding, catalog, chunks=chunks,
                                                       retrieval_error=semantic.warning)
                        finding = apply_evidence_contract(scoped_request, finding,
                                                          applications=applications)
                        if self.verifications:
                            records = []
                            for declaration in finding.get("verifications", []):
                                source = next(s for s in finding["supports"]
                                              if s["source_id"] == declaration["source_id"])
                                records.append(self.verifications.record_antecedent(
                                    case, source, declaration["passage"], declaration["fact"],
                                    declaration["basis"], declaration.get("attributed_to"),
                                    request_ids=[request["id"]]))
                            finding["verifications"] = records
                        if semantic.warning:
                            finding = {**finding, "warnings": list(dict.fromkeys(
                                [*finding.get("warnings", []), semantic.warning]
                            ))}
                        return finding
                    except Exception as exc:
                        return dict(
                            request_id=request["id"],
                            status="error",
                            evidence_states=["analysis_error"],
                            summary=user_error(exc),
                            supports=[],
                            missing=[],
                            warnings=[],
                        )

            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="source-request") as workers:
                pending = {}
                remaining = iter(requests)

                def fill_slots():
                    while len(pending) < concurrency:
                        request = next(remaining, None)
                        if request is None:
                            break
                        run["request_states"][request["id"]] = "searching"
                        pending[workers.submit(evaluate, request)] = request
                    self.library.save_run(run)

                fill_slots()
                while pending:
                    finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in finished:
                        request = pending.pop(future)
                        try:
                            finding = future.result()
                        except Exception as exc:
                            finding = dict(request_id=request["id"], status="error",
                                           evidence_states=["analysis_error"], summary=user_error(exc),
                                           supports=[], missing=[], warnings=[])
                        run["results"].append(finding)
                        run["results"].sort(key=lambda item: order[item["request_id"]])
                        run["request_states"][request["id"]] = "error" if finding["status"] == "error" else "completed"
                    run["shared_checks"] = group_checks(run["results"])
                    run["completed_count"] = len(run["results"])
                    run["retrieval_warning"] = semantic.warning
                    run["retrieval_progress"] = {"phase": "searching", **semantic.diagnostics}
                    fill_slots()
            errors = sum(f["status"] == "error" for f in run["results"])
            run.update(
                status="error" if errors else "ready",
                error=f"No se pudieron evaluar {errors} solicitudes. "
                "Reintenta para recuperar el avance."
                if errors
                else None,
            )
            run["retrieval_progress"]["phase"] = "completed"
        except Exception as exc:
            run.update(status="error", error=user_error(exc))
        finally:
            self.library.save_run(run)
            with self.lock:
                self.active.discard(case["id"])

    def close(self):
        self.pool.shutdown(wait=True)
