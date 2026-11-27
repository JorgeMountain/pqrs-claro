"""Prepare a provisional reply before human routing, then revise individual answers."""

import hashlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from functools import partial
from threading import Lock
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .draft_engine import OpenAIDraftEngine
from .draft_graph import build_draft_graph
from .evidence_contract import apply_evidence_contract, catalog_audit
from .extraction import OpenAIOCR, PDFExtractor
from .identification import OpenAIIdentifier
from .models import DomainError, Page
from .performance_metrics import submit_context, track_case
from .pool_integration import OpenAIPoolIntegration, apply_contributions, contribution_inputs
from .pool_progress import progress_step, report_requests, report_step
from .pool_text import reply_text
from .preanalysis_engine import CHECK_VERSION, OpenAIPreanalysisEngine, materialize
from .request_intent import classify_request_intent
from .source_assessment import OpenAISourceAssessor
from .source_context import build_source_requests
from .source_graph import build_source_graph
from .source_library import digest
from .source_retrieval import RetrievalIndex, retrieve
from .source_semantic import SemanticIndex
from .source_service import INTERACTIVE_SEMANTIC_BUDGET_SECONDS, retrieval_signature
from .workflow import build_graph


def _checkpoint(graph, key, inputs, output):
    config = {"configurable": {"thread_id": key}}
    saved = graph.get_state(config)
    if output == "finding" and saved.values.get("finding", {}).get("status") == "error":
        return graph.invoke(inputs, config)
    if output in saved.values:
        # Identification intentionally pauses at its human gate. A draft can
        # still have a repair queued after its first set of checks.
        if not saved.next or saved.next == ("review_identification",):
            return saved.values
    return graph.invoke(None if saved.values else inputs, config)


class _Result(TypedDict):
    result: dict


def _cached_result(saver, key, compute):
    """A completed check or integration can be read back after an interrupted job."""
    graph = StateGraph(_Result)
    graph.add_node("compute", lambda _: {"result": compute()})
    graph.add_edge(START, "compute")
    graph.add_edge("compute", END)
    return _checkpoint(graph.compile(checkpointer=saver), key, {"result": {}}, "result")["result"]


def _provider(stack, injected, settings, factory, **kwargs):
    if injected is not None:
        return injected
    if not settings.api_key:
        raise DomainError("Configura la clave de OpenAI y reintenta el análisis de la solicitud.")
    engine = factory(settings.api_key, settings.model, **kwargs)
    stack.callback(engine.client.close)
    return engine


def _identified_row(request):
    return {
        "id": request["id"], "text": request["description"], "title": request["title"],
        "label": request["label"], "parent_id": request.get("parent_id"),
        "source_refs": request["source_refs"], "sources": [], "source_status": None,
        "source_summary": "", "answer": "", "gaps": [], "gap": "", "paragraphs": [],
    }


def _source_result(finding):
    fields = ("source_id", "chunk_id", "title", "filename", "quote", "page", "line_start",
              "line_end", "role", "version")
    return {
        "sources": [{k: src[k] for k in fields if k in src} for src in finding["supports"]],
        "source_status": finding["status"], "source_summary": finding.get("summary") or "",
        **({"secondary_source_checks": finding["secondary_source_checks"]}
           if finding.get("secondary_source_checks") else {}),
    }


def _draft_result(request, finding, result):
    draft = result["draft"]
    paragraphs = draft["paragraphs"] if finding["supports"] else []
    answer = "\n\n".join(p["text"] for p in paragraphs).strip()
    gaps = []
    for item in (*finding.get("missing", []), *finding.get("actions", []), *draft["pending"]):
        resolution = item.get("resolution")
        status = resolution.get("status") if isinstance(resolution, dict) else resolution
        if status not in ("resolved", "not_applicable") and item.get("description"):
            gaps.append(item["description"])
    for issue in result["checks"].get("issues", []):
        gaps.append(issue.get("description") or issue.get("reason") or issue.get("message")
                    or "Revisar la observación de redacción antes de aprobar la respuesta.")
    if not gaps and result["checks"].get("status") != "passed":
        gaps.append("Verificar la redacción y sus fuentes para completar esta respuesta.")
    if not gaps and (not answer or finding["status"] in {"no_matches", "needs_evidence"}):
        gaps.append(f"Aportar información que permita responder: {request['description']}")
    gaps = list(dict.fromkeys(gaps))
    return {"answer": answer, "gaps": gaps, "gap": "\n".join(gaps), "paragraphs": paragraphs}


class PoolDrafts:
    def __init__(self, settings, cases, identification, sources_service, drafts_service, *,
                 preanalysis_engine=None, integration_engine=None):
        self.settings = settings
        self.cases = cases
        self.identification = identification
        self.sources = sources_service
        self.library = sources_service.library
        self.drafts = drafts_service
        self.preanalysis_engine = preanalysis_engine
        self.integration_engine = integration_engine

    def _read(self, case, stack):
        settings = self.settings
        with progress_step("reading") as reading:
            path = self.cases.original(case["id"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != case["sha256"]:
                raise DomainError("El PDF original cambió. Revisa el archivo de la solicitud.")
            extractor = self.identification.extractor
            if extractor is None:
                ocr = _provider(stack, None, settings, OpenAIOCR) if settings.api_key else None
                extractor = PDFExtractor(ocr)
            saver = stack.enter_context(SqliteSaver.from_conn_string(str(
                settings.data_dir / "checkpoints.sqlite")))
            identifier = self.identification.identifier
            provider_type = type(identifier) if identifier is not None else OpenAIIdentifier
            key = digest([
                case["sha256"], settings.model, provider_type.__qualname__, CHECK_VERSION
            ])
            thread = f"{case['id']}:pool:{key}"
            config = {"configurable": {"thread_id": thread}}
            graph = build_graph(extractor, identifier, saver)
            projection = graph.get_state(config).values
            if not projection.get("pages"):
                inputs = None if projection else {"case_id": case["id"], "pdf_path": str(path)}
                projection = graph.invoke(inputs, config, interrupt_after=["read_pdf"])
            pages = [Page.model_validate(p) for p in projection["pages"]]
            reading["pages"] = [p.model_dump(exclude={"text"}) for p in pages]
            reading["check_version"] = CHECK_VERSION
        checker = self.preanalysis_engine
        checks = None
        if checker is not None or settings.api_key:
            try:
                with progress_step("checks") as output:
                    if checker is None:
                        checker = OpenAIPreanalysisEngine(settings)
                        stack.callback(checker.close)
                    checks = _cached_result(
                        saver, thread + ":checks:" + digest(type(checker).__qualname__),
                        lambda: materialize(checker.assess(pages), pages),
                    )
                    output.update(checks)
            except ValueError:
                checks = None
        if checks is None:
            checks = {key: {"state": "unverified", "refs": [], "summary":
                      "La comprobación automática quedó pendiente. Revisa el PDF original."}
                      for key in ("requester", "respect", "integrity")}
            report_step("checks", "error", result=checks)
        with progress_step("identification") as output:
            if "identification" not in projection:
                identifier = _provider(stack, identifier, settings, OpenAIIdentifier)
                projection = _checkpoint(build_graph(extractor, identifier, saver), thread,
                                         {}, "identification")
            identification = projection["identification"]
            output.update(subject=identification["subject"],
                          identification_warnings=identification.get("warnings", []),
                          requests=[_identified_row(r) for r in identification["requests"]])
            report_requests(identification["requests"])
        return {**case, "pages": projection["pages"],
                "reading": reading, "identification": identification}, checks

    def _require_scope(self, case_id, collection_ids):
        if self.library.scope_revoked(case_id, collection_ids):
            raise DomainError("Cambió el acceso a la biblioteca de este expediente.")

    @track_case("pool_initial", "case_id")
    def initial(self, case_id):
        self.cases.assert_open(case_id)
        with ExitStack() as stack:
            case, checks = self._read(self.cases.get(case_id), stack)
            with progress_step("library") as library_output:
                with self.library.lock:
                    collections = self.library.linked_collections(case_id)
                    sources, chunks = self.library.snapshot(case_id)
                    catalog = self.sources.catalog(case_id)
                    applications = (self.sources.verifications.active_applications(case, sources)
                                    if self.sources.verifications else [])
                requests = build_source_requests(case, allowed_collection_ids=collections)
                assessor = _provider(
                    stack, self.sources.assessor, self.settings, OpenAISourceAssessor,
                    service_tier=self.settings.source_service_tier)
                writer = _provider(stack, self.drafts.engine, self.settings, OpenAIDraftEngine,
                                   procedure_scope_pilot=self.settings.procedure_scope_pilot)
                lexical = RetrievalIndex(chunks, prepared_terms=self.library.prepared_terms(chunks))
                semantic = SemanticIndex(
                    self.settings.data_dir / "semantic", model_factory=self.sources.semantic_model,
                    matrix_cache_bytes=self.settings.semantic_matrix_cache_mb * 1024 * 1024,
                    preparation_budget_seconds=INTERACTIVE_SEMANTIC_BUDGET_SECONDS,
                )
                if chunks:
                    semantic.prepare(chunks)
                library_output["allowed_collection_ids"] = collections
            retrieval_lock = Lock()

            def locate(request, _):
                with retrieval_lock:
                    return retrieve(request, chunks, index=lexical, semantic=semantic)

            read_saver, draft_saver = [stack.enter_context(SqliteSaver.from_conn_string(str(
                self.settings.data_dir / filename)))
                for filename in ("source_checkpoints.sqlite", "draft_checkpoints.sqlite")]
            source_graph = build_source_graph(
                locate, assessor, read_saver, check_scope=lambda: self._require_scope(
                    case_id, collections), independent_ocr_read=self.settings.independent_ocr_read)
            draft_graph = build_draft_graph(writer, draft_saver)
            catalog_key = digest([self.sources.reader_policy(), sources, catalog, collections,
                                  retrieval_signature(self.settings.data_dir), semantic.warning])

            def respond(request):
                with progress_step("sources", request["id"]) as source_output:
                    self._require_scope(case_id, collections)
                    request["request_intent"] = classify_request_intent(request)
                    key = f"{case_id}:pool:{request['id']}:{digest([request, catalog_key])}"
                    if chunks:
                        result = _checkpoint(source_graph, key, {"request": request, "chunks": []},
                                             "finding")
                        finding = result["finding"]
                        if finding.get("status") == "error":
                            raise DomainError(
                                "La búsqueda de fuentes falló. Reintenta el preanálisis.")
                    else:
                        finding = {"request_id": request["id"], "status": "no_matches",
                                   "summary": "La biblioteca vinculada no contiene texto "
                                              "consultable.",
                                   "supports": [], "missing": [], "warnings": []}
                    self._require_scope(case_id, collections)
                    audited = catalog_audit(request, finding, catalog, chunks=chunks,
                                            retrieval_error=semantic.warning)
                    finding = apply_evidence_contract(audited, finding, applications=applications)
                    source_output.update(_source_result(finding))
                with progress_step("drafting", request["id"]) as draft_output:
                    policy = getattr(writer, "cache_key", type(writer).__qualname__)
                    result = _checkpoint(draft_graph, key + ":" + digest([finding, policy]),
                                         {"request": request, "finding": finding}, "checks")
                    self._require_scope(case_id, collections)
                    draft_output.update(_draft_result(request, finding, result))
                return {**_identified_row(request), **source_output, **draft_output}

            limit = min(self.settings.source_concurrency, self.settings.draft_concurrency)
            with ThreadPoolExecutor(max_workers=max(1, limit)) as workers:
                futures = [submit_context(workers, respond, request) for request in requests]
                rows = [future.result() for future in futures]
            self._require_scope(case_id, collections)
            # The search and drafting can take minutes. Verify that the exact
            # cited originals still belong to the current authorized snapshot.
            cited = {s["source_id"] for row in rows for s in row["sources"]}
            if cited:
                self.library.snapshot(case_id, source_ids=cited)
            receipt, origin = case.get("receipt") or {}, case.get("origin") or {}
            letter = {
                "subject": receipt.get("subject") or case["identification"]["subject"],
                "reference": receipt.get("reference") or origin.get("reported_case_number") or "",
                "requester": checks["requester"].get("name")
                             or case["identification"].get("requester") or "",
            }
            return {"text": reply_text(rows, letter), "requests": rows, "checks": checks,
                    "reading": case["reading"],
                    "identification_warnings": case["identification"].get("warnings", []),
                    "subject": letter["subject"], "letter": letter,
                    "allowed_collection_ids": collections}

    @track_case("pool_integration", "case_id")
    def integrate(self, case_id, previous_snapshot, tasks):
        self.cases.assert_open(case_id)
        snapshot = deepcopy(previous_snapshot)
        collections = snapshot.get("allowed_collection_ids", [])
        self._require_scope(case_id, collections)
        # A later version in the library does not change what the previous
        # draft cited. Check the integrity and visibility of those versions.
        cited = {s["source_id"] for row in snapshot["requests"] for s in row.get("sources", [])}
        for source_id in cited:
            self.library.original(source_id, case_id)
        by_request = defaultdict(list)
        for task in tasks:
            by_request[task["request_id"]].extend(contribution_inputs(task))
        rows = snapshot["requests"]
        if set(by_request) - {row["id"] for row in rows}:
            raise DomainError("Hay aportes para una petición ajena a este borrador.")
        affected = [row for row in rows if row["id"] in by_request]
        report_requests(affected)
        with ExitStack() as stack:
            engine = _provider(stack, self.integration_engine, self.settings, OpenAIPoolIntegration)
            saver = stack.enter_context(SqliteSaver.from_conn_string(str(
                self.settings.data_dir / "draft_checkpoints.sqlite")))

            def integrate_row(row, inputs):
                revised = deepcopy(row)
                apply_contributions(engine, revised, inputs)
                return revised

            for row in affected:
                with progress_step("integration", row["id"]):
                    self._require_scope(case_id, collections)
                    inputs = by_request[row["id"]]
                    key = digest(["per-gap-citations-v2", self.settings.model,
                                  type(engine).__qualname__, collections, row, inputs])
                    revised = _cached_result(saver, f"{case_id}:pool:integration:{key}",
                                             partial(integrate_row, row, inputs))
                    row.clear()
                    row.update(revised)
        self._require_scope(case_id, collections)
        snapshot["text"] = reply_text(rows, snapshot.get("letter"))
        return snapshot
