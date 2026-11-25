"""Information survives the plan/write/check boundary without erasing controls."""

import json
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from test_draft_engine import engine, finding, inquiry, proposed_plan, support

from pqrs_claro.draft_graph import build_draft_graph
from pqrs_claro.models import DomainError
from pqrs_claro.request_requirements import build_requirements


def inputs():
    request = inquiry(description="Explique qué límite se fijó y qué fundamento tuvo.")
    request["request_requirements"] = build_requirements(request)
    source = support(quote=(
        "En 2024 el comité fijó un límite de cuatro equipos.\n"
        "La decisión se basó en el estudio técnico de cargas.\n"
        "El informe también enumera un calendario de reuniones no consultado."
    ), line_end=3)
    data = finding(supports=[source], missing=[{
        "kind": "clarification", "description": "Cotejar la procedencia del oficio.",
        "basis": "metadata_only", "reason_code": "provenance", "stage": "evidence",
    }])
    plan = proposed_plan()
    plan["coverage_units"] = [
        {"requirement_id": rid, "role": role, "claim": claim,
         "citations": [{"chunk_id": "S1", "line_start": line, "line_end": line}],
         "reason": reason, "details": [],
         "no_details_reason": "Dato o fundamento sin identidad nombrada ni alternativa."}
        for rid, role, claim, line, reason in [
            ("R1", "required_answer", "El límite fijado fue de cuatro equipos.", 1,
             "Responde el límite preguntado."),
            ("R2", "required_basis", "El fundamento fue un estudio técnico de cargas.", 2,
             "Explica el fundamento expresamente preguntado."),
            ("R2", "optional_context", "El informe enumera un calendario de reuniones.", 3,
             "Es contexto que no condiciona ni responde el fundamento consultado."),
        ]
    ]
    return request, data, plan


def checks(*, omitted=False):
    return {"status": "passed", "issues": [], "requirement_checks": [
        {"requirement_id": rid, "status": "answered", "paragraph_indexes": [0],
         "pending_indexes": [], "explanation": "El modelo atribuye respuesta al párrafo."}
        for rid in ("R1", "R2")
    ], "unit_checks": [
        {"unit_id": uid, "status": "omitted" if omitted and uid == "U2" else "answered",
         "paragraph_indexes": [0], "pending_indexes": [],
         "explanation": "Falta el fundamento." if omitted and uid == "U2"
                        else "El contenido aparece con su cita."}
        for uid in ("U1", "U2")
    ]}


def test_literal_inventory_reaches_writer_and_reviewer_without_forcing_optional_context():
    request, data, proposed = inputs()
    text = ("Según el oficio de 2024, el comité fijó un límite de cuatro equipos "
            "con base en un estudio técnico de cargas.")
    worker, calls = engine(proposed, {"paragraphs": [
        {"text": text, "cited_chunk_ids": ["S1"]}], "pending": []}, checks())
    plan = worker.plan(request, data)
    assert [u["id"] for u in plan["coverage_units"]] == ["U1", "U2", "U3"]
    assert plan["coverage_units"][1]["citations"][0]["quote"] == (
        "La decisión se basó en el estudio técnico de cargas.\n")
    draft = worker.write(request, data, plan)
    before = deepcopy(draft)
    result = worker.check(request, data, plan, draft)
    assert result["status"] == "passed"
    assert draft == before and draft["pending"]
    assert not any("calendario" in p["description"] for p in draft["pending"])
    for call in calls[1:]:
        sent = json.loads(call["input"])["plan"]["coverage_units"]
        assert sent[1]["citations"][0]["chunk_id"] == "S1"
        assert sent[1]["id"] == "U2"


def test_provider_schema_accepts_every_valid_role_and_excludes_required_context():
    request, data, proposed = inputs()
    expected = [
        (f"{prefix}_{kind}", kind, required)
        for kind in ("answer", "condition", "exception", "basis", "sequence")
        for prefix, required in (("required", True), ("optional", False))
    ] + [("optional_context", "context", False)]
    example = proposed["coverage_units"][0]
    proposed["coverage_units"] = [dict(example, role=role) for role, _, _ in expected]
    worker, calls = engine(proposed)
    result = worker.plan(request, data)
    assert [(u["kind"], u["required"]) for u in result["coverage_units"]] == [
        (kind, required) for _, kind, required in expected
    ]
    assert len(calls) == 1
    wire_schema = calls[0]["text_format"]
    for invalid in (dict(example, role="required_context"),
                    dict(example, role="optional_context", required=True)):
        with pytest.raises(ValidationError):
            wire_schema.model_validate({**proposed, "coverage_units": [invalid]})


def test_explicit_comparison_preserves_the_recommendation_without_making_it_a_deadline():
    request = inquiry(description="Distinga el plazo de entrega de la anticipación recomendada.")
    request["request_requirements"] = build_requirements(request)
    lines = [
        "El plazo termina a las cinco.",
        "Se recomienda llegar una hora antes.",
        "El edificio dispone de estacionamiento.",
    ]
    data = finding(supports=[support(quote="\n".join(lines), line_end=3)], missing=[])
    proposed = proposed_plan()
    proposed["coverage_units"] = [
        {"requirement_id": "R1", "role": role, "claim": claim,
         "citations": [{"chunk_id": "S1", "line_start": n, "line_end": n}],
         "reason": reason, "details": [], "no_details_reason": "No hay autoridades ni opciones."}
        for n, (role, claim, reason) in enumerate([
            ("required_answer", lines[0], "Se pide identificar el plazo."),
            (
                "required_answer",
                lines[1],
                "La petición pide distinguir la recomendación del plazo.",
            ),
            ("optional_context", lines[2], "El estacionamiento es accesorio a la comparación."),
        ], 1)
    ]
    response = "El plazo termina a las cinco. Llegar una hora antes es una recomendación."
    worker, calls = engine(proposed, {
        "paragraphs": [{"text": response, "cited_chunk_ids": ["S1"]}], "pending": [],
    })
    plan = worker.plan(request, data)
    draft = worker.write(request, data, plan)
    assert len(calls) == 2
    writer_units = json.loads(calls[1]["input"])["plan"]["coverage_units"]
    assert [(u["claim"], u["kind"], u["required"]) for u in writer_units] == [
        (lines[0], "answer", True), (lines[1], "answer", True), (lines[2], "context", False),
    ]
    assert writer_units[1]["citations"] == [{"chunk_id": "S1", "quote": lines[1] + "\n"}]
    assert draft["paragraphs"][0]["cited_chunk_ids"] == [data["supports"][0]["chunk_id"]]
    assert draft["pending"] == []


def test_omitted_grounded_unit_is_repaired_once_while_pending_controls_remain_identical():
    request, data, proposed = inputs()
    original = "Según el oficio de 2024, el comité fijó un límite de cuatro equipos."
    corrected = original[:-1] + " con base en un estudio técnico de cargas."
    worker, calls = engine(
        proposed,
        {"paragraphs": [{"text": original, "cited_chunk_ids": ["S1"]}], "pending": []},
        checks(omitted=True),
        {"paragraphs": [{"paragraph_index": 0, "text": corrected,
                          "cited_chunk_ids": ["S1"]}]},
        checks(),
    )
    graph = build_draft_graph(worker, InMemorySaver())
    result = graph.invoke({"request": request, "finding": data},
                          {"configurable": {"thread_id": "new-unit-grounding"}})
    assert len(calls) == 5  # plan, write, check, one correction, mandatory recheck
    assert result["checks"]["status"] == "passed"
    assert result["draft"]["paragraphs"][0]["text"] == corrected
    assert result["repair"]["before_checks"]["status"] == "needs_changes"
    assert any(i["code"] == "answer_unit_omitted"
               for i in result["repair"]["before_checks"]["issues"])
    before = json.loads(calls[2]["input"])["draft"]["pending"]
    after = json.loads(calls[4]["input"])["draft"]["pending"]
    assert before and before == after
    assert all(p.get("resolution", {}).get("status") != "resolved" for p in after)


def test_missing_unit_checklist_has_only_one_structural_retry_and_cannot_pass_empty():
    request, data, proposed = inputs()
    invalid = checks()
    invalid["unit_checks"] = []
    worker, calls = engine(proposed, invalid, invalid)
    plan = worker.plan(request, data)
    draft = {"status": "needs_review", "paragraphs": [{
        "text": "Según el oficio de 2024, el comité fijó cuatro equipos.",
        "cited_chunk_ids": [data["supports"][0]["chunk_id"]]}], "pending": []}
    result = worker.check(request, data, plan, draft)
    assert len(calls) == 3
    assert result["status"] == "needs_changes"
    assert any(i["code"] == "unit_review_incomplete" for i in result["issues"])
    assert json.loads(calls[-1]["input"])["requirement_check_repair"]["previous_unit_checks"] == []


def test_supported_current_request_cannot_silently_skip_inventory():
    request, data, _ = inputs()
    data["sufficiency"] = {"coverage": [{"claim": "Contenido respaldado."}]}
    worker, calls = engine(proposed_plan(), proposed_plan())
    with pytest.raises(DomainError, match="inventariar"):
        worker.plan(request, data)
    assert len(calls) == 2


def test_copy_only_plan_does_not_fabricate_citable_units_for_controls_or_future_delivery():
    request, data, _ = inputs()
    data["sufficiency"] = {"coverage": [{
        "claim": "El original se localizó para preparar la copia.", "use": "document_delivery",
    }]}
    worker, calls = engine(proposed_plan())
    result = worker.plan(request, data)
    assert result["coverage_units"] == [] and len(calls) == 1
    assert data["missing"][0]["basis"] == "metadata_only"


def test_mixed_copy_and_content_still_requires_a_grounded_inventory():
    request, data, _ = inputs()
    data["sufficiency"] = {"coverage": [
        {"claim": "El original se localizó.", "use": "document_delivery"},
        {"claim": "El límite fue de cuatro equipos.", "use": "attributed_content"},
    ]}
    worker, calls = engine(proposed_plan(), proposed_plan())
    with pytest.raises(DomainError, match="inventariar"):
        worker.plan(request, data)
    assert len(calls) == 2


def test_copy_only_with_rejected_candidate_does_not_require_narrating_its_content():
    request, data, _ = inputs()
    request["description"] = (
        "Solicito copia firmada del acta de la sesión sobre horarios. "
        "Debe ser el ejemplar firmado, no la propuesta."
    )
    request["request_requirements"] = build_requirements(request)
    data["sufficiency"] = {"coverage": [{
        "claim": "El candidato es una propuesta sin firma; no acredita una decisión.",
        "use": "attributed_content",
    }]}
    data["missing"].append({
        "kind": "document", "description": "Localizar el ejemplar firmado de la sesión.",
        "reason_code": "document_search", "basis": "unavailable_document", "stage": "evidence",
    })
    original = deepcopy(data)
    worker, calls = engine(proposed_plan())
    plan = worker.plan(request, data)
    assert plan["coverage_units"] == [] and len(calls) == 1
    assert data == original
    assert len(json.loads(calls[0]["input"])["existing_pending"]) >= 2


def test_copy_with_explicit_content_question_cannot_skip_inventory():
    request, data, _ = inputs()
    request["description"] = "Faciliten copia del acta. Indiquen qué decisión se tomó."
    request["request_requirements"] = build_requirements(request)
    data["sufficiency"] = {"coverage": [{
        "claim": "La decisión queda atribuida al acta.", "use": "attributed_content",
    }]}
    worker, calls = engine(proposed_plan(), proposed_plan())
    with pytest.raises(DomainError, match="inventariar"):
        worker.plan(request, data)
    assert len(calls) == 2


def test_tampered_plan_cannot_introduce_a_source_or_trigger_a_writer_call():
    request, data, proposed = inputs()
    worker, calls = engine(proposed)
    plan = worker.plan(request, data)
    plan["coverage_units"][0]["citations"][0]["chunk_id"] = "unauthorized-source"
    with pytest.raises(DomainError):
        worker.write(request, data, plan)
    assert len(calls) == 1
