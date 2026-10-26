from copy import deepcopy

import pytest

from pqrs_claro.intake_drafting import drafting_context
from pqrs_claro.repetition_scope import optional_history_proposal


def inputs():
    request = {
        "id": "P1",
        "title": "Duración del examen",
        "description": "Informar cuánto dura el examen de admisión.",
    }
    check = {
        "key": "repetition",
        "state": "unverified",
        "sources": [],
        "summary": "No verificable",
        "reason": "Búsqueda parcial",
        "pending": ["Buscar antecedentes."],
    }
    review = {
        "report": {"document": {}, "requests": [{"request_id": "P1", "checks": [check]}]},
        "decisions": [{"request_id": "P1", "route": "continue", "note": ""}],
        "reviewed_by": "Gestora",
        "document_decision": {"route": "continue"},
    }
    return request, review, check


def test_general_question_keeps_diagnostic_without_imposing_a_history_search():
    request, review, check = inputs()
    original = deepcopy(review)
    result = drafting_context(review, "P1", request)
    observation = result["request"]["observations"][0]
    assert observation["required_for_response"] is False and observation["pending"] == []
    assert review == original and check["pending"]


def test_concrete_history_requests_evidence_and_human_decisions_keep_controls():
    for kind in ("request", "context", "evidence", "route", "note", "contradiction"):
        request, review, check = inputs()
        if kind == "request":
            request["description"] = "Comparar mi solicitud anterior con la respuesta recibida."
        if kind == "context":
            request["context"] = {"subject": "Seguimiento de una respuesta previa"}
        if kind == "evidence":
            check["sources"] = [{"source_id": "known"}]
        if kind == "route":
            review["decisions"][0]["route"] = "reiterate"
        if kind == "note":
            review["decisions"][0]["note"] = "Contrastar la respuesta anterior aportada."
        if kind == "contradiction":
            check["state"] = "potential_observation"
        obs = drafting_context(review, "P1", request)["request"]["observations"][0]
        assert obs["pending"] and obs.get("required_for_response") is not False, kind


def test_only_new_generic_history_proposals_are_filtered_when_content_is_covered():
    request, review, _ = inputs()
    request["initial_review"] = drafting_context(review, "P1", request)
    proposal = {
        "kind": "document",
        "description": (
            "Revisar si existe una solicitud y respuesta anterior de la misma persona "
            "sobre la duración."
        ),
        "basis": "content_gap",
    }
    finding = {"sufficiency": {"coverage_complete": True}}
    paragraphs = [{"text": "La guía establece una duración máxima de 3 horas."}]
    assert optional_history_proposal(request, finding, proposal, paragraphs)
    assert not optional_history_proposal(request, {}, proposal, paragraphs)
    assert not optional_history_proposal(request, finding, proposal, [])
    for change in (
        {"basis": "contradiction"},
        {"linked_source_ids": ["file"]},
        {"existing_check_keys": ["check-1"]},
        {"description": "Aportar la credencial individual solicitada."},
    ):
        assert not optional_history_proposal(request, finding, {**proposal, **change}, paragraphs)
    assert not optional_history_proposal(
        request, finding, proposal, [{"text": "No hay solicitudes anteriores de la persona."}]
    )


@pytest.mark.parametrize("description,paragraph", [
    ("Informar cuánto dura el examen de admisión.",
     "Según la guía, la duración máxima del examen es de tres horas."),
    ("Indicar los requisitos para solicitar una constancia académica.",
     "Según la guía, se requiere completar el formulario de solicitud."),
    ("Informar el horario de atención de la biblioteca.",
     "Según la guía, la biblioteca atiende de lunes a viernes, de 8 a 17 horas."),
    ("Informar las fechas de la convocatoria de becas.",
     "Según la guía, la convocatoria está abierta del 1 al 15 de noviembre."),
    ("Explicar cómo solicitar una homologación de asignaturas.",
     "Según la guía, la homologación se solicita con el formulario y el plan de estudios."),
    ("Indicar el costo de una copia de la constancia de matrícula.",
     "Según la guía, la copia de la constancia cuesta diez mil pesos."),
])
def test_draft_pipeline_keeps_saved_checks_but_does_not_create_generic_history_work(
    description, paragraph,
):
    from test_draft_engine import engine, finding, proposed_draft, proposed_plan, support

    request, review, _ = inputs()
    request.update(id="P1", title="Consulta institucional", description=description,
                   case_id="expediente-ordinario", is_demo=False)
    request["initial_review"] = drafting_context(review, "P1", request)
    proposal = {
        "kind": "document",
        "description": "Comparar si existe una solicitud y respuesta anterior de la misma persona.",
    }
    draft = proposed_draft(paragraph)
    draft["pending"] = [proposal]
    source_finding = finding(
        missing=[],
        supports=[support(category="institutional_norm", role="rule", quote=paragraph,
                          collection_id=None)],
        sufficiency={"coverage_complete": True},
    )
    worker, _ = engine(proposed_plan(), deepcopy(draft))
    result = worker.write(request, source_finding, worker.plan(request, source_finding))
    assert result["pending"] == [] and result["status"] == "needs_review"
    assert result["paragraphs"][0]["text"] == paragraph
    assert result["pending_not_required"][0]["proposal"]["description"] == proposal["description"]

    # A saved/source finding stays open; this rule never resolves existing work.
    source_finding["missing"] = [proposal]
    worker, _ = engine(proposed_plan(), deepcopy(draft))
    result = worker.write(request, source_finding, worker.plan(request, source_finding))
    assert result["status"] == "needs_evidence"
    assert any(p["description"] == proposal["description"] for p in result["pending"])
