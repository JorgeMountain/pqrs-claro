"""A generic summary cannot hide named actors or the source's alternatives."""

import json
from copy import deepcopy

from langgraph.checkpoint.memory import InMemorySaver
from test_draft_engine import engine, finding, inquiry, proposed_check, support

from pqrs_claro.draft_graph import build_draft_graph

SOURCE = "El Comité de Talleres o el Consejo de Oficios autoriza la reserva."
GENERIC = "El órgano correspondiente autoriza la reserva."


def inputs():
    request = inquiry(title="Autoridad de la reserva",
                      description="Indique qué órganos alternativos pueden autorizar la reserva.")
    src = support(category="institutional_norm", role="rule", title="Manual de reservas",
                  filename="manual.pdf", quote=SOURCE, line_start=1, line_end=1)
    found = finding(supports=[src], missing=[{
        "kind": "norm", "description": "Cotejar la vigencia del manual.",
        "reason_code": "validity", "basis": "metadata_only", "stage": "evidence",
    }])
    citation = {"chunk_id": "S1", "line_start": 1, "line_end": 1}
    first = {"word_start": 2, "word_end": 4}
    second = {"word_start": 7, "word_end": 9}
    details = [
        {"kind": "authority", "citation": citation, "members": [member],
         "reason": "Identifica una autoridad que puede autorizar."}
        for member in (first, second)
    ] + [{"kind": "alternatives", "citation": citation, "members": [first, second],
          "reason": "La fuente permite cualquiera de las dos autoridades."}]
    plan = {"objective": "Explicar quién puede autorizar.", "points": [{
        "description": "Indicar la autoridad y la relación alternativa.",
        "cited_chunk_ids": ["S1"]}],
        "coverage_units": [{
            "requirement_id": "R1", "role": "required_answer",
            "claim": "El órgano autoriza la reserva.",
            "citations": [citation], "reason": "Contesta la autoridad.",
            "details": details, "no_details_reason": "",
        }]}
    return request, found, plan


def checked(text=GENERIC):
    # Deliberately overconfident provider: all entries say answered. Python still
    # detects the missing identities in the actual paragraph, not in its citation.
    count = len(text.split())
    return proposed_check(unit_checks=[{
        "unit_id": "U1", "status": "answered", "paragraph_indexes": [0],
        "pending_indexes": [], "explanation": "El párrafo pretende contestar la unidad.",
    }], detail_checks=[{
        "detail_id": f"U1-K{n}", "status": "answered", "pending_indexes": [],
        "explanation": "El modelo atribuye presencia de todas las identidades y opciones.",
        "evidence": [{"paragraph_index": 0, "word_start": 1, "word_end": count,
                      "member_index": member} for member in ([1, 2] if n == 3 else [1])],
    } for n in range(1, 4)])


def test_named_details_force_bounded_repair_without_removing_pending_or_citations():
    request, found, plan = inputs()
    original = deepcopy(found)
    worker, calls = engine(plan, {"paragraphs": [{"text": GENERIC, "cited_chunk_ids": ["S1"]}],
                                 "pending": []}, checked(),
        {"paragraphs": [{"paragraph_index": 0, "text": SOURCE, "cited_chunk_ids": ["S1"]}]},
        checked(SOURCE))
    result = build_draft_graph(worker, InMemorySaver()).invoke(
        {"request": request, "finding": found}, {"configurable": {"thread_id": "detail-repair"}})
    assert len(calls) == 5 and result["checks"]["status"] == "passed"
    assert result["repair"]["attempts"] == 1
    assert sum(i["code"] == "answer_detail_omitted"
               for i in result["repair"]["before_checks"]["issues"]) == 2
    assert result["draft"]["paragraphs"][0]["text"] == SOURCE
    assert result["draft"]["pending"] == result["repair"]["before_draft"]["pending"]
    assert result["draft"]["paragraphs"][0]["cited_chunk_ids"] == [found["supports"][0]["chunk_id"]]
    assert found == original
    payload = json.loads(calls[2]["input"])
    assert payload["plan"]["coverage_units"][0]["details"][0]["members"][0]["quote"] == (
        "Comité de Talleres")
    assert payload["numbered_detail_paragraphs"][0]["numbered_words"][1][1] == "órgano"


def test_omitted_detail_checklist_cannot_pass_by_accepting_the_parent_unit():
    request, found, proposed = inputs()
    invalid = checked(SOURCE)
    invalid["detail_checks"] = []
    worker, calls = engine(proposed, {"paragraphs": [{"text": SOURCE, "cited_chunk_ids": ["S1"]}],
                                    "pending": []}, invalid, invalid)
    plan = worker.plan(request, found)
    draft = worker.write(request, found, plan)
    before = deepcopy(draft)
    result = worker.check(request, found, plan, draft)
    assert len(calls) == 4  # one structural retry; no rewritten text or semantic retries
    assert result["status"] == "needs_changes"
    assert any(i["code"] == "detail_review_incomplete" for i in result["issues"])
    assert draft == before


def test_sufficiency_uncertainty_uses_only_aliases_while_preserving_original():
    from pqrs_claro.draft_engine import aliased_sufficiency

    value = {"uncertainties": [{"passages": [{"chunk_id": "doc:1", "quote": SOURCE,
                                             "role": "rule"}]}]}
    before = deepcopy(value)
    output = aliased_sufficiency(value, {"doc:1": "S1"})
    assert output["uncertainties"][0]["passages"][0]["chunk_id"] == "S1"
    assert value == before


def test_old_inventory_is_readable_but_cannot_reuse_a_current_detail_check():
    from pqrs_claro.answer_coverage import detail_issues, validate_units

    request, found, plan = inputs()
    src = found["supports"][0]
    worker, _ = engine(plan)
    units = worker.plan(request, found)["coverage_units"]
    for unit in units:
        for key in ("details_version", "details", "no_details_reason"):
            unit.pop(key)
    assert validate_units(units, request, {src["chunk_id"]: src}) == units
    assert detail_issues(units, [], {"paragraphs": [], "pending": []})[0]["code"] == (
        "detail_inventory_stale")
