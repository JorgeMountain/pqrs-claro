"""Tres pasos visibles: leer, identificar y pausar para revisión humana."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .models import Identification, Page, validate_identification, validate_pages


class Extractor(Protocol):
    def extract(self, path: str) -> list[Page]: ...


class Identifier(Protocol):
    def identify(self, pages: list[Page]) -> Identification: ...


class CaseState(TypedDict, total=False):
    case_id: str
    pdf_path: str
    pages: list[dict[str, Any]]
    identification: dict[str, Any]
    confirmed: bool
    phase: str


def build_graph(extractor: Extractor, identifier: Identifier, checkpointer: Any):
    """El checkpointer guarda el avance; el expediente original lo administra storage."""

    def read_pdf(state: CaseState) -> dict:
        pages = ([Page.model_validate(p) for p in state["pages"]]
                 if state.get("pages") else extractor.extract(state["pdf_path"]))
        validate_pages(pages)
        return {
            "pages": [page.model_dump(mode="json") for page in pages],
            "confirmed": False,
            "phase": "read",
        }

    def identify_requests(state: CaseState) -> dict:
        pages = [Page.model_validate(page) for page in state["pages"]]
        identification = identifier.identify(pages)
        validate_identification(identification, pages)
        return {"identification": identification.model_dump(mode="json"), "phase": "review"}

    def review_identification(state: CaseState) -> dict:
        # Este nodo se reinicia al reanudar: no contiene OCR, llamadas IA ni escrituras.
        reviewed = interrupt(
            {
                "case_id": state["case_id"],
                "message": "Revisa las solicitudes con el original y confirma la identificación.",
            }
        )
        identification = Identification.model_validate(reviewed)
        pages = [Page.model_validate(page) for page in state["pages"]]
        validate_identification(identification, pages)
        return {
            "identification": identification.model_dump(mode="json"),
            "confirmed": True,
            "phase": "confirmed",
        }

    graph = StateGraph(CaseState)
    graph.add_node("read_pdf", read_pdf)
    graph.add_node("identify_requests", identify_requests)
    graph.add_node("review_identification", review_identification)
    graph.add_edge(START, "read_pdf")
    graph.add_edge("read_pdf", "identify_requests")
    graph.add_edge("identify_requests", "review_identification")
    graph.add_edge("review_identification", END)
    return graph.compile(checkpointer=checkpointer)
