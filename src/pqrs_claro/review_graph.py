"""Comprobar una versión, pausar y registrar únicamente su aprobación explícita."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import Field, StrictBool, ValidationError

from .models import DomainError, StrictModel
from .review_engine import structural_checks, validate_review_input
from .review_models import Actor, InputHash, ReviewApprove


class ReviewEngine(Protocol):
    def assess(self, request: dict, review: dict) -> dict: ...


class ReviewState(TypedDict, total=False):
    request: dict[str, Any]
    review: dict[str, Any]
    input_hash: str
    assessment: dict[str, Any]
    evaluated_input_hash: str
    evaluated_content_hash: str
    approval_decision: dict[str, Any]
    approval: dict[str, Any] | None


class _Check(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    passed: StrictBool
    description: str = Field(min_length=1, max_length=10000)


class _GraphIssue(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=12000)
    paragraph_index: int | None = Field(ge=0)


class _GraphAssessment(StrictModel):
    status: Literal["passed", "needs_changes"]
    issues: list[_GraphIssue]
    local_checks: list[_Check]


class _Decision(StrictModel):
    approved_by: Actor
    note: str = Field(default="", max_length=3000)
    confirmed: StrictBool
    input_hash: InputHash


def _content_hash(state: ReviewState) -> str:
    text = json.dumps(
        {"request": state["request"], "review": state["review"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current(state: ReviewState) -> None:
    if state.get("evaluated_input_hash") != state.get("input_hash") or state.get(
        "evaluated_content_hash"
    ) != _content_hash(state):
        raise DomainError("La versión cambió después de comprobarla; vuelve a evaluar.")


def _approval_ready(state: ReviewState) -> bool:
    assessment = state["assessment"]
    _, issues = structural_checks(validate_review_input(state["request"], state["review"]))
    return (
        assessment["status"] == "passed"
        and not assessment["issues"]
        and all(item["passed"] is True for item in assessment["local_checks"])
        and not issues
    )


def build_review_graph(engine: ReviewEngine, checkpointer: Any):
    """El servicio comprueba además las entradas vivas y conserva el snapshot inmutable.

    Un thread identifica un intento. El interrupt persiste con el checkpointer:
    reanudarlo no vuelve a ejecutar la IA. Ningún resultado de la IA puede aprobar.
    """

    def comprobar_revision(state: ReviewState) -> dict:
        validate_review_input(state["request"], state["review"])
        try:
            _Decision.model_validate(
                {
                    "approved_by": "validación de huella",
                    "confirmed": True,
                    "input_hash": state["input_hash"],
                }
            )
        except ValidationError:
            raise DomainError("La revisión no tiene una huella de entrada válida.") from None
        content_hash = _content_hash(state)
        try:
            assessment = _GraphAssessment.model_validate(
                engine.assess(state["request"], state["review"])
            ).model_dump()
        except ValidationError:
            raise DomainError("El motor devolvió una comprobación inválida.") from None
        # Defensa independiente del proveedor: aunque sugiera passed, una respuesta
        # vacía, sin citas vigentes o con pendientes abiertos no puede llegar a aprobar.
        local, issues = structural_checks(state["review"])
        for item in local:
            if item not in assessment["local_checks"]:
                assessment["local_checks"].append(item)
        for issue in issues:
            if issue not in assessment["issues"]:
                assessment["issues"].append(issue)
        if assessment["issues"] or any(not item["passed"] for item in assessment["local_checks"]):
            assessment["status"] = "needs_changes"
        if _content_hash(state) != content_hash:
            raise DomainError("El motor alteró el texto de entrada; la comprobación se descartó.")
        return {
            "assessment": assessment,
            "approval": None,
            "evaluated_input_hash": state["input_hash"],
            "evaluated_content_hash": content_hash,
        }

    def esperar_aprobacion(state: ReviewState) -> dict:
        _current(state)
        if not _approval_ready(state):
            raise DomainError("Esta revisión todavía no permite aprobación.")
        decision = interrupt(
            {
                "kind": "review_approval",
                "request_id": state["request"]["id"],
                "input_hash": state["input_hash"],
                "assessment": state["assessment"],
            }
        )
        try:
            value = _Decision.model_validate(decision).model_dump()
            ReviewApprove.model_validate(
                {
                    "revision": 1,
                    "assessment_hash": value["input_hash"],
                    **{key: value[key] for key in ("approved_by", "note", "confirmed")},
                }
            )
        except ValidationError:
            raise DomainError(
                "Completa responsable y confirmación explícita de esta versión."
            ) from None
        if value["input_hash"] != state["input_hash"]:
            raise DomainError("La aprobación no corresponde a la versión comprobada.")
        _current(state)
        return {"approval_decision": value}

    def registrar_aprobacion(state: ReviewState) -> dict:
        _current(state)
        if not _approval_ready(state):
            raise DomainError("La evaluación vigente no permite aprobar la respuesta.")
        decision = state["approval_decision"]
        if decision["confirmed"] is not True or decision["input_hash"] != state["input_hash"]:
            raise DomainError("No existe confirmación explícita para esta versión.")
        return {
            "approval": {
                "id": uuid4().hex,
                "approved_by": decision["approved_by"],
                "note": decision["note"],
                "input_hash": state["input_hash"],
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
        }

    graph = StateGraph(ReviewState)
    graph.add_node("comprobar_revision", comprobar_revision)
    graph.add_node("esperar_aprobacion", esperar_aprobacion)
    graph.add_node("registrar_aprobacion", registrar_aprobacion)
    graph.add_edge(START, "comprobar_revision")
    graph.add_conditional_edges(
        "comprobar_revision",
        lambda state: ("esperar_aprobacion" if _approval_ready(state) else END),
    )
    graph.add_edge("esperar_aprobacion", "registrar_aprobacion")
    graph.add_edge("registrar_aprobacion", END)
    return graph.compile(checkpointer=checkpointer)
