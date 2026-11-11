"""Coordina búsquedas por solicitud sin modificar la identificación confirmada."""

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from .evidence_contract import apply_evidence_contract, catalog_audit, group_checks
from .performance_metrics import operation, submit_context, track_case
from .request_intent import classify_request_intent
from .service import user_error
from .source_assessment import OpenAISourceAssessor
from .source_context import build_source_requests
from .source_graph import build_source_graph
from .source_library import digest
from .source_passages import PASSAGE_SELECTION_VERSION, diagnostic
from .source_retrieval import RetrievalIndex, retrieve
from .source_semantic import (
    MODEL_FILE,
    MODEL_KEY,
    MODEL_REVISION,
    ResidentSemanticModel,
    SemanticIndex,
)
from .storage import Conflict, now

SOURCE_ANALYSIS_VERSION = 20
# Version the prompt, schema and validation policy used by a reader checkpoint.
SOURCE_READER_POLICY_VERSION = 1
INTERACTIVE_SEMANTIC_BUDGET_SECONDS = 15
logger = logging.getLogger(__name__)


def failed_finding(request_id, exc):
    return dict(request_id=request_id, status="error", evidence_states=["analysis_error"],
                summary=user_error(exc), supports=[], missing=[], warnings=[],
                analysis_diagnostic=getattr(exc, "diagnostic", None) or diagnostic(
                    "evidence_contract_error" if isinstance(exc, ValueError) else "internal_error"))


def retrieval_signature(data_dir):
    return {
        "version": SOURCE_ANALYSIS_VERSION,
        "semantic_model": MODEL_KEY,
        "semantic_installed": (
            data_dir / "semantic" / "models" / MODEL_REVISION / MODEL_FILE
        ).is_file(),
    }


def _request_checkpoint(case_id, request, context, attempt):
    key = digest({"context": context, "request": request,
                  "request_cache_version": SOURCE_READER_POLICY_VERSION})
    thread_id = f"{case_id}:{request['id']}:{key}"
    if attempt:
        thread_id += f":{attempt}"
    return {"configurable": {"thread_id": thread_id}}


def _matches_reader(run, policy):
    if "reader_policy" in run:
        return run["reader_policy"] == policy
    # A previously completed result remains available under the original reader
    # policy. It cannot supply a raw reading for a new catalog snapshot.
    return (policy["reader_version"] == 1
            and run.get("passage_selection_version", 1) == policy["passage_version"]
            and (policy["provider"] == "openai" or policy["reader"] is None))


class SourceService:
    def __init__(self, settings, cases, library, *, assessor=None, verifications=None):
        self.settings, self.cases, self.library = settings, cases, library
        self.assessor = assessor
        self.verifications = verifications
        self.semantic_preparation = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sources")
        self.semantic_model = ResidentSemanticModel()
        self.lock = threading.RLock()
        self.active = set()

    def catalog(self, case_id):
        return self.library.scoped(case_id)

    def reader_policy(self):
        provider, key = "openai", "sources"
        if self.assessor is not None:
            cls = type(self.assessor)
            provider = f"{cls.__module__}.{cls.__qualname__}"
            key = getattr(self.assessor, "reader_cache_key", None)
        return {"provider": provider, "reader": key, "model": self.settings.model,
                "reader_version": SOURCE_READER_POLICY_VERSION,
                "passage_version": PASSAGE_SELECTION_VERSION}

    def verification_fingerprint(self, case_id, sources):
        return self.verifications.fingerprint(case_id, sources) if self.verifications else None

    def inputs(self, case_id, *, _catalog=None):
        with self.library.lock:
            case = self.cases.get(case_id)
            case["allowed_collection_ids"] = self.library.linked_collections(case_id)
            sources, chunks = self.library.snapshot(case_id)
            fingerprint = digest(
                {
                    "identification": case["identification"],
                    "catalog": self.catalog(case_id) if _catalog is None else _catalog,
                    "verifications": self.verification_fingerprint(case_id, sources),
                    "sources": sources,
                    "model": self.settings.model,
                    "analysis_version": SOURCE_ANALYSIS_VERSION,
                    "retrieval": retrieval_signature(self.settings.data_dir),
                    "collections": case["allowed_collection_ids"],
                }
            )
        return case, sources, chunks, fingerprint

    def progress(self, case_id):
        """Estado para sondeo; un resultado terminal siempre valida su vigencia."""
        with self.library.lock:
            case = self.cases.get(case_id)
            run = self.library.latest_run(case_id, compact=True)
            if run and run["status"] == "running" and not self._scope_revoked(case_id, run):
                # Partial findings have the same permission boundary as final citations.
                # Polling a modern run only checks its collection links.
                return {**run, "stale": None, "freshness_checked": False}
            return self._checked_map(case, run)

    def _scope_revoked(self, case_id, run, *, current=None):
        if "allowed_collection_ids" in run:
            return self.library.scope_revoked(
                case_id, run["allowed_collection_ids"], current=current)
        return self.library.run_scope_revoked(case_id, run["id"])

    def get(self, case_id, *, compact=False, _catalog=None):
        with self.library.lock:
            case = self.cases.get(case_id)
            run = self.library.latest_run(case_id, compact=compact)
            return self._checked_map(case, run, _catalog)

    def _checked_map(self, case, run, _catalog=None):
        case_id = case["id"]
        # A caller already holding library.lock may share this exact read within
        # one validation. Nothing is cached across requests or changes of scope.
        catalog = self.catalog(case_id) if _catalog is None else _catalog
        # Es el mismo alcance de scoped(evidence_only=True), sin decodificar
        # dos veces los metadatos del catálogo para una sola validación.
        sources = [source for source in catalog
                   if source.get("category") != "archive_only"
                   and ("extraction_status" not in source
                        or source["extraction_status"] in {"ready", "partial"})]
        collections = self.library.linked_collections(case_id)
        if run and self._scope_revoked(case_id, run, current=collections):
            # Free-text findings, pending actions and catalog audits may all quote
            # the withdrawn source. Only publish process state from this old run.
            return dict(
                id=run["id"], case_id=case_id,
                status="running" if run["status"] == "running" else "stale",
                stale=True, scope_revoked=True, results=[], shared_checks=[],
                source_count=len(sources), searched_at=run.get("searched_at"),
                error=None, completed_count=0, total_count=case["request_count"],
            )
        fingerprint_inputs = {
            "identification": case["identification"],
            "catalog": catalog,
            "verifications": self.verification_fingerprint(case_id, sources),
            "sources": sources,
            "model": self.settings.model,
            "analysis_version": SOURCE_ANALYSIS_VERSION,
            "retrieval": retrieval_signature(self.settings.data_dir),
            "collections": collections,
        }
        fingerprint = digest(fingerprint_inputs)
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
        # v19 relaciona cada fecha con el evento cercano, no con toda la página.
        # v18 amplía pasajes y evita que el cupo léxico cierre el canal semántico.
        # v17 recupera fechas explícitas; v16 busca dentro de documentos.
        # Un resultado anterior ya satisfactorio sigue siendo utilizable si TODAS sus
        # entradas actuales coinciden. No se promueven errores ni se reescribe el run.
        if (stale and SOURCE_ANALYSIS_VERSION in {15, 16, 17, 18, 19, 20}
                and run.get("status") == "ready" and not run.get("error")):
            results = run.get("results", [])
            compatible = len(results) == case["request_count"] and all(
                r.get("status") == "references_found"
                and not r.get("error")
                and not any(v.get("extraction_error") for v in r.get("verifications", []))
                and "analysis_error" not in r.get("evidence_states", [])
                and not any(m.get("state") == "analysis_error" for m in r.get("missing", []))
                for r in results
            )
            if compatible:
                for previous_version in range(14, SOURCE_ANALYSIS_VERSION):
                    previous = {
                        **fingerprint_inputs, "analysis_version": previous_version,
                        "retrieval": {
                            **fingerprint_inputs["retrieval"], "version": previous_version},
                    }
                    if run["fingerprint"] == digest(previous):
                        stale = False
                        break
        stale = stale or not _matches_reader(run, self.reader_policy())
        return {
            **run,
            "status": "stale" if stale and run["status"] != "running" else run["status"],
            "stale": stale,
            "source_count": len(sources),
        }

    def validate_failed_retry(self, case_id, version):
        case, _, _, fingerprint = self.inputs(case_id)
        previous = self.library.latest_run(case_id)
        if case["version"] != version or case["status"] != "confirmed":
            raise Conflict("El expediente cambió. Revisa las solicitudes antes de continuar.")
        if (not previous or previous["fingerprint"] != fingerprint
                or not _matches_reader(previous, self.reader_policy())
                or previous["status"] == "running"):
            raise Conflict("Las fuentes o el expediente cambiaron. Actualiza la búsqueda completa.")
        ids = {r["id"] for r in case["identification"]["requests"]}
        results = previous.get("results", [])
        if (len(results) != len(ids) or {r["request_id"] for r in results} != ids
                or not any(r["status"] == "error" for r in results)):
            raise Conflict("No hay un análisis completo con solicitudes fallidas para reintentar.")
        return previous

    def start(self, case_id, version, *, retry_analysis=False, retry_failed_only=False):
        with self.lock:
            self.cases.assert_open(case_id)
            if getattr(self, "initial_review", None):
                self.initial_review.assert_allowed(case_id)
            # Every input that can contribute text to a finding belongs to this
            # same permission snapshot, including catalog-only documents and checks.
            with self.library.lock:
                catalog = self.catalog(case_id)
                case, sources, chunks, fingerprint = self.inputs(case_id, _catalog=catalog)
                applications = (self.verifications.active_applications(case, sources)
                                if self.verifications else [])
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
            reader_policy = self.reader_policy()
            if retry_analysis and retry_failed_only:
                raise Conflict("Elige reintentar los errores o actualizar todo el análisis.")
            if retry_failed_only:
                previous = self.validate_failed_retry(case_id, version)
                if previous["fingerprint"] != fingerprint:
                    raise Conflict("Las fuentes cambiaron. Actualiza la búsqueda completa.")
            retry_semantic = (
                previous and previous.get("retrieval_warning")
                and retrieval_signature(self.settings.data_dir)["semantic_installed"]
            )
            if (
                previous
                and not retry_analysis
                and not retry_failed_only
                and previous["fingerprint"] == fingerprint
                and _matches_reader(previous, reader_policy)
                and previous["status"] == "ready"
                and not retry_semantic
            ):
                return self.get(case_id)
            retrieval_attempt = ""
            if previous and previous["fingerprint"] == fingerprint:
                retrieval_attempt = previous.get("retrieval_attempt", "")
            if retry_semantic or retry_analysis or retry_failed_only:
                retrieval_attempt = uuid4().hex
            # La aplicación de una comprobación humana cambia el resultado, pero
            # no exige repetir recuperación/IA de fuentes idénticas.
            analysis_fingerprint = digest({
                "analysis_version": SOURCE_ANALYSIS_VERSION,
                "reader_policy": reader_policy,
                "original": case["sha256"], "pages": case.get("pages"),
                "metadata": {k: v for k, v in case["identification"].items()
                             if k != "requests"}, "sources": sources,
                "catalog": catalog, "model": self.settings.model,
                "retrieval": retrieval_signature(self.settings.data_dir),
                "collections": case["allowed_collection_ids"],
            })
            retained = ([deepcopy(r) for r in previous["results"] if r["status"] != "error"]
                        if retry_failed_only else [])
            retry_ids = ([r["request_id"] for r in previous["results"] if r["status"] == "error"]
                         if retry_failed_only else [])
            prior_read = None
            if (reader_policy["reader"] and previous and previous.get("status") == "ready"
                    and previous.get("reader_policy") == reader_policy
                    and previous.get("analysis_version") == SOURCE_ANALYSIS_VERSION
                    and previous.get("analysis_fingerprint")
                    and previous["analysis_fingerprint"] != analysis_fingerprint
                    and not (retry_analysis or retry_failed_only or retry_semantic)):
                prior_read = (previous["analysis_fingerprint"], previous.get("retrieval_attempt"))
            run = dict(
                id=uuid4().hex,
                analysis_fingerprint=analysis_fingerprint,
                analysis_version=SOURCE_ANALYSIS_VERSION,
                reader_policy=reader_policy,
                case_id=case_id,
                status="running",
                fingerprint=fingerprint,
                results=retained,
                source_count=len(sources),
                source_snapshot=sources,
                allowed_collection_ids=case["allowed_collection_ids"],
                searched_at=now(),
                error=None,
                completed_count=len(retained),
                total_count=len(case["identification"]["requests"]),
                stale=False,
                retrieval_attempt=retrieval_attempt,
                retry_request_ids=retry_ids,
                retry_of_run_id=previous["id"] if retry_failed_only else None,
                passage_selection_version=PASSAGE_SELECTION_VERSION,
                shared_checks=group_checks(retained),
            )
            self.library.save_run(run)
            self.active.add(case_id)
            self.pool.submit(self.run, case, chunks, run, catalog=catalog,
                             applications=applications, prior_read=prior_read)
            return self.progress(case_id)

    @track_case("sources", "case")
    def run(self, case, chunks, run, *, catalog, applications, prior_read=None):
        try:
            assessor = self.assessor or OpenAISourceAssessor(
                self.settings.api_key, self.settings.model,
                service_tier=self.settings.source_service_tier,
            )
            lexical = RetrievalIndex(chunks, prepared_terms=self.library.prepared_terms(chunks))
            # No bloquear la primera consulta hasta indexar toda la biblioteca.
            # La recuperación léxica mantiene su alcance completo y el canal
            # semántico declara su cobertura real; el resto se prepara aparte.
            semantic = SemanticIndex(
                self.settings.data_dir / "semantic",
                model_factory=self.semantic_model,
                matrix_cache_bytes=self.settings.semantic_matrix_cache_mb * 1024 * 1024,
                preparation_budget_seconds=INTERACTIVE_SEMANTIC_BUDGET_SECONDS,
            )
            last_progress_save = 0.0

            def index_progress(progress):
                nonlocal last_progress_save
                run["retrieval_progress"] = {"phase": "indexing", **progress}
                if time.monotonic() - last_progress_save >= 2:
                    self.library.save_run_progress(run)
                    last_progress_save = time.monotonic()

            with operation("library.semantic_prepare"):
                semantic.prepare(chunks, progress=index_progress)
            run["retrieval_warning"] = semantic.warning
            run["retrieval_progress"] = {"phase": "searching", **semantic.diagnostics}
            if (semantic.diagnostics.get("budget_exhausted") and self.semantic_preparation
                    and retrieval_signature(self.settings.data_dir)["semantic_installed"]):
                try:
                    self.semantic_preparation.enqueue(run["source_snapshot"])
                except Exception:
                    # Una cola auxiliar no debe perder pasajes recuperables ni
                    # convertir una limitación de cobertura en un fallo del caso.
                    logger.warning("No se pudo encolar la preparación semántica pendiente.")
            requests = build_source_requests(
                case, allowed_collection_ids=run.get("allowed_collection_ids", []))
            order = {request["id"]: i for i, request in enumerate(requests)}
            retrieval_lock = threading.RLock()
            concurrency = min(3, max(1, getattr(self.settings, "source_concurrency", 3)))
            run["concurrency"] = concurrency
            retained_ids = {r["request_id"] for r in run["results"]}
            run["request_states"] = {r["id"]: "completed" if r["id"] in retained_ids else "queued"
                                     for r in requests}
            # Initialize SQLite/WAL once before concurrent connections open it.
            checkpoint_path = str(self.settings.data_dir / "source_checkpoints.sqlite")
            with SqliteSaver.from_conn_string(checkpoint_path) as warmup:
                warmup.get_tuple({"configurable": {"thread_id": "__schema_initialization__"}})

            def locate(request, _):
                with retrieval_lock:
                    with operation("library.retrieve", request_id=request["id"]):
                        return retrieve(request, chunks, index=lexical, semantic=semantic)

            def check_scope():
                if self._scope_revoked(case["id"], run):
                    raise Conflict("Cambió el permiso de las fuentes. Actualiza la búsqueda.")

            def evaluate(request):
                with operation("sources.request", request_id=request["id"]):
                    return evaluate_request(request)

            def evaluate_request(request):
                with SqliteSaver.from_conn_string(
                    str(self.settings.data_dir / "source_checkpoints.sqlite")
                ) as saver:
                    request["request_intent"] = classify_request_intent(request)
                    config = _request_checkpoint(
                        case["id"], request, run.get("analysis_fingerprint", run["fingerprint"]),
                        run.get("retrieval_attempt"),
                    )
                    prior_config = (_request_checkpoint(case["id"], request, *prior_read)
                                    if prior_read else None)
                    graph = build_source_graph(locate, assessor, saver, prior_config=prior_config,
                                               check_scope=check_scope)
                    try:
                        check_scope()
                        snapshot = graph.get_state(config)
                        if snapshot.values.get("finding") and not snapshot.next:
                            finding = snapshot.values["finding"]
                        else:
                            initial = (
                                None if snapshot.values else {"request": request, "chunks": []}
                            )
                            finding = graph.invoke(initial, config)["finding"]
                        check_scope()
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
                        return failed_finding(request["id"], exc)

            with ThreadPoolExecutor(
                max_workers=concurrency, thread_name_prefix="source-request"
            ) as workers:
                pending = {}
                remaining = iter(r for r in requests if r["id"] not in retained_ids)

                def fill_slots():
                    while len(pending) < concurrency:
                        request = next(remaining, None)
                        if request is None:
                            break
                        run["request_states"][request["id"]] = "searching"
                        pending[submit_context(workers, evaluate, request)] = request
                    self.library.save_run_progress(run)

                fill_slots()
                while pending:
                    finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in finished:
                        request = pending.pop(future)
                        try:
                            finding = future.result()
                        except Exception as exc:
                            finding = failed_finding(request["id"], exc)
                        run["results"].append(finding)
                        run["results"].sort(key=lambda item: order[item["request_id"]])
                        run["request_states"][request["id"]] = (
                            "error" if finding["status"] == "error" else "completed")
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
        self.semantic_model.clear()
