"""Tres pasos recuperables para preparar un borrador por solicitud."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph


class DraftEngine(Protocol):
    def plan(self, request: dict, finding: dict) -> dict: ...

    def write(self, request: dict, finding: dict, plan: dict) -> dict: ...

    def check(self, request: dict, finding: dict, plan: dict, draft: dict) -> dict: ...


class DraftState(TypedDict, total=False):
    request: dict[str, Any]
    finding: dict[str, Any]
    plan: dict[str, Any]
    draft: dict[str, Any]
    checks: dict[str, Any]


def build_draft_graph(engine: DraftEngine, checkpointer: Any):
    """Un thread por solicitud y huella; reanudar no repite pasos ya conservados.

    El servicio comprueba que la identificación, la selección de fuentes y sus
    originales siguen correspondiendo a la huella antes de invocar o reanudar.
    Este grafo no aprueba respuestas ni envía documentos.
    """

    def planificar(state: DraftState) -> dict:
        return {"plan": engine.plan(state["request"], state["finding"])}

    def redactar(state: DraftState) -> dict:
        return {"draft": engine.write(state["request"], state["finding"], state["plan"])}

    def comprobar(state: DraftState) -> dict:
        return {
            "checks": engine.check(
                state["request"], state["finding"], state["plan"], state["draft"]
            )
        }

    graph = StateGraph(DraftState)
    graph.add_node("planificar", planificar)
    graph.add_node("redactar", redactar)
    graph.add_node("comprobar", comprobar)
    graph.add_edge(START, "planificar")
    graph.add_edge("planificar", "redactar")
    graph.add_edge("redactar", "comprobar")
    graph.add_edge("comprobar", END)
    return graph.compile(checkpointer=checkpointer)
