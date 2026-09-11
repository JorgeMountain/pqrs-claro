"""Borradores recuperables con un único ajuste de citas y nueva comprobación."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from .draft_repair import CitationRepairRejected, repair_targets


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
    repair: dict[str, Any]


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

    def siguiente(state: DraftState) -> str:
        capable = getattr(engine, "can_repair", callable(getattr(engine, "repair", None)))
        return (
            "ajustar_citas"
            if capable and repair_targets(state["checks"], state["draft"])
            else END
        )

    def ajustar_citas(state: DraftState) -> dict:
        before = deepcopy(state["draft"])
        try:
            adjusted = engine.repair(
                state["request"], state["finding"], state["plan"], before, state["checks"]
            )
        except CitationRepairRejected as exc:
            checks = deepcopy(state["checks"])
            checks["status"] = "needs_changes"
            checks["issues"].append({
                "code": "citation_repair_rejected",
                "description": (
                    "El ajuste automático fue rechazado; se conserva el borrador anterior "
                    f"para revisión. {exc}"
                ),
                "paragraph_index": None,
            })
            return {
                "draft": deepcopy(state["draft"]),
                "checks": checks,
                "repair": {
                    "attempts": 1,
                    "status": "rejected",
                    "reason": str(exc),
                    "target_indices": repair_targets(state["checks"], state["draft"]),
                    "removed_request_scope_indices": [],
                    "before_draft": deepcopy(state["draft"]),
                    "before_checks": deepcopy(state["checks"]),
                    "changed": False,
                },
            }
        removed = adjusted.pop("_removed_request_scope_indices", [])
        return {
            "draft": adjusted,
            "repair": {
                "attempts": 1,
                "target_indices": repair_targets(state["checks"], before),
                "removed_request_scope_indices": removed,
                "before_draft": state["draft"],
                "before_checks": state["checks"],
                "changed": adjusted != state["draft"],
            },
        }

    graph = StateGraph(DraftState)
    graph.add_node("planificar", planificar)
    graph.add_node("redactar", redactar)
    graph.add_node("comprobar", comprobar)
    graph.add_node("ajustar_citas", ajustar_citas)
    graph.add_node("recomprobar", comprobar)
    graph.add_edge(START, "planificar")
    graph.add_edge("planificar", "redactar")
    graph.add_edge("redactar", "comprobar")
    graph.add_conditional_edges("comprobar", siguiente, ["ajustar_citas", END])
    graph.add_conditional_edges(
        "ajustar_citas",
        lambda state: END if state["repair"].get("status") == "rejected" else "recomprobar",
        ["recomprobar", END],
    )
    graph.add_edge("recomprobar", END)
    return graph.compile(checkpointer=checkpointer)
