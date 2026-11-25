"""Independent graph replays: a wholly omitted answer has no paragraph to patch.

These deliberately inject model omissions. They measure recovery and preservation,
not the spontaneous omission rate of the production model on the new PDF corpus.
"""

import json
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_draft_engine import engine, finding, inquiry, proposed_plan, support

from pqrs_claro.draft_graph import build_draft_graph
from pqrs_claro.request_requirements import build_requirements

EXAMPLES = [
    ("audio", "El acceso dura cinco días calendario.",
     "Si no recibe el correo, consulte el casillero y la carpeta de correo no deseado."),
    ("instrumentos", "La reserva dura dos días hábiles.",
     "Si no se recoge el instrumento, vuelve al inventario sin generar multa."),
    ("huerta", "Los bloques duran cuarenta minutos.",
     "El saldo se utiliza en otra visita y no equivale a devolución de dinero."),
]


def scenario(label, first, second):
    request = inquiry(description="Indique la duración; explique la condición adicional.")
    request["request_requirements"] = build_requirements(request)
    quoted = support(title=f"Documento ficticio de {label}", category="institutional_norm",
                     role="rule",
                     quote=first + "\n" + second, line_end=2)
    finding_row = finding(supports=[quoted], missing=[{
        "kind": "clarification", "description": "Cotejar la firma ilegible con el original.",
        "basis": "material_gap", "reason_code": "authenticity", "stage": "evidence",
        "affected_claim": "La firma corresponde a la persona indicada.",
        "why_unresolved": "La reproducción no permite leer la firma.",
    }])
    plan = proposed_plan()
    plan["coverage_units"] = [
        {"requirement_id": f"R{index}", "role": "required_answer", "claim": text,
         "citations": [{"chunk_id": "S1", "line_start": index, "line_end": index}],
         "reason": "Responde contenido expresamente solicitado.", "details": [],
         "no_details_reason": "Dato sin autoridad nombrada ni alternativa."}
        for index, text in enumerate((first, second), 1)
    ]
    draft = {"paragraphs": [{"text": first, "cited_chunk_ids": ["S1"]}], "pending": []}
    return request, finding_row, plan, draft


def review(omitted):
    return {"status": "passed", "issues": [], "requirement_checks": [
        {"requirement_id": f"R{i}", "status": "omitted" if omitted and i == 2 else "answered",
         "paragraph_indexes": [] if omitted and i == 2 else [i - 1], "pending_indexes": [],
         "explanation": "La segunda respuesta falta por completo." if omitted and i == 2
         else "La respuesta aparece con respaldo."} for i in (1, 2)
    ], "unit_checks": [
        {"unit_id": f"U{i}", "status": "omitted" if omitted and i == 2 else "answered",
         "paragraph_indexes": [] if omitted and i == 2 else [i - 1], "pending_indexes": [],
         "explanation": "No existe párrafo de esta unidad." if omitted and i == 2
         else "Se conserva la afirmación y su fuente."} for i in (1, 2)
    ]}


@pytest.mark.parametrize("label,first,second", EXAMPLES)
def test_new_domain_complete_omission_is_restored_without_rewriting_or_closing_checks(
    label, first, second,
):
    request, found, plan, draft = scenario(label, first, second)
    before = deepcopy(found)
    worker, calls = engine(plan, draft, review(True), {
        "paragraphs": [], "omitted_unit_paragraphs": [
            {"unit_id": "U2", "text": second, "cited_chunk_ids": ["S1"]}]}, review(False))
    graph = build_draft_graph(worker, InMemorySaver())
    result = graph.invoke({"request": request, "finding": found},
                          {"configurable": {"thread_id": f"independent-{label}"}})
    assert len(calls) == 5  # Plan/write/check plus the existing bounded repair/recheck.
    assert result["checks"]["status"] == "passed"
    assert [p["text"] for p in result["draft"]["paragraphs"]] == [first, second]
    assert result["repair"]["before_checks"]["status"] == "needs_changes"
    repair_input = json.loads(calls[3]["input"])
    assert repair_input["repair_targets"] == []
    assert [u["id"] for u in repair_input["missing_answer_units"]] == ["U2"]
    before_pending = json.loads(calls[2]["input"])["draft"]["pending"]
    assert before_pending and before_pending == result["draft"]["pending"]
    assert found == before
    assert all(p["cited_chunk_ids"] == [found["supports"][0]["chunk_id"]]
               for p in result["draft"]["paragraphs"])


def test_new_domain_failed_recheck_keeps_omission_and_does_not_loop():
    label, first, second = EXAMPLES[0]
    request, found, plan, draft = scenario(label, first, second)
    worker, calls = engine(plan, draft, review(True), {
        "paragraphs": [], "omitted_unit_paragraphs": []}, review(True))
    graph = build_draft_graph(worker, InMemorySaver())
    result = graph.invoke({"request": request, "finding": found},
                          {"configurable": {"thread_id": "independent-still-omitted"}})
    assert len(calls) == 5
    assert result["checks"]["status"] == "needs_changes"
    assert [p["text"] for p in result["draft"]["paragraphs"]] == [first]
    assert result["draft"]["pending"]
