"""Dos pasos por solicitud: localizar fragmentos y evaluar qué pueden respaldar."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph


class SourceAssessor(Protocol):
    def assess(self, request: dict, candidates: list[dict]) -> dict: ...


class SourceState(TypedDict, total=False):
    request: dict[str, Any]
    chunks: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    finding: dict[str, Any]


def build_source_graph(
    retriever: Callable[..., list[dict]], assessor: SourceAssessor, checkpointer: Any
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
        return {"finding": assessor.assess(state["request"], state["candidates"])}

    graph = StateGraph(SourceState)
    graph.add_node("retrieve_sources", retrieve_sources)
    graph.add_node("assess_sources", assess_sources)
    graph.add_edge(START, "retrieve_sources")
    graph.add_edge("retrieve_sources", "assess_sources")
    graph.add_edge("assess_sources", END)
    return graph.compile(checkpointer=checkpointer)
