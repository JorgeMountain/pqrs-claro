"""Dos pasos por solicitud: localizar fragmentos y evaluar qué pueden respaldar."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from .performance_metrics import operation
from .source_library import digest
from .source_retrieval import source_in_scope

logger = logging.getLogger(__name__)
_VALID_FINDING_STATUSES = {"references_found", "needs_evidence", "no_matches"}


class SourceAssessor(Protocol):
    def assess(self, request: dict, candidates: list[dict]) -> dict: ...


class SourceState(TypedDict, total=False):
    request: dict[str, Any]
    chunks: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    finding: dict[str, Any]


def build_source_graph(
    retriever: Callable[..., list[dict]], assessor: SourceAssessor, checkpointer: Any,
    *, prior_config=None, check_scope: Callable[[], None] | None = None,
):
    """El servicio fija un thread_id por solicitud y versión de sus entradas.

    request conserva la pregunta atómica y el contexto del mismo escrito. Ambos
    nodos reciben ese mismo objeto, sin sustituir la pregunta por sus apartados.

    Un error al evaluar permite reanudar con invoke(None, config), conservando la
    recuperación previa. Los efectos sobre la biblioteca viven fuera de este grafo.
    """

    def retrieve_sources(state: SourceState) -> dict:
        return {"candidates": retriever(state["request"], state["chunks"])}

    def assess_sources(state: SourceState) -> dict:
        request, candidates = state["request"], state["candidates"]
        if check_scope is not None:
            check_scope()
        if previous and all(source_in_scope(request, row) for row in candidates):
            finding = previous.get("finding") or {}
            if (finding.get("request_id") == request["id"] and not finding.get("error")
                    and "analysis_error" not in finding.get("evidence_states", [])
                    and finding.get("status") in _VALID_FINDING_STATUSES
                    and digest([previous.get("request"), previous.get("candidates")])
                    == digest([request, candidates])):
                with operation("sources.read_reused"):
                    return {"finding": finding}
        return {"finding": assessor.assess(request, candidates)}

    graph = StateGraph(SourceState)
    graph.add_node("retrieve_sources", retrieve_sources)
    graph.add_node("assess_sources", assess_sources)
    graph.add_edge(START, "retrieve_sources")
    graph.add_edge("retrieve_sources", "assess_sources")
    graph.add_edge("assess_sources", END)
    compiled = graph.compile(checkpointer=checkpointer)
    previous = None
    if prior_config:
        # Only the recorded raw evaluation is reused. Catalog and human checks
        # are materialized by the service after this graph finishes.
        try:
            saved = compiled.get_state(prior_config)
            if not saved.next:
                previous = saved.values
        except Exception:
            logger.warning("No se pudo leer el checkpoint anterior; se evaluarán las fuentes.")
    return compiled
