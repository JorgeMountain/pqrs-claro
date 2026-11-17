"""A blind text reader can reject a source checker pass without changing evidence."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_draft_engine import finding, inquiry, proposed_check, support

from pqrs_claro.config import Settings
from pqrs_claro.draft_engine import OpenAIDraftEngine
from pqrs_claro.draft_graph import build_draft_graph
from pqrs_claro.draft_service import DraftService
from pqrs_claro.evidence_contract import normalize_pending
from pqrs_claro.models import DomainError

FIRST = "La revisión del cargo la resuelven dos analistas distintos."
SECOND = "La inspección técnica también corresponde a dos analistas."
EFFECT = "La decisión de los analistas sustituye el cargo inicial."
AMBIGUOUS = " ".join((FIRST, SECOND, EFFECT))
CLEAR = (FIRST + " El ajuste de esa revisión sustituye el cargo inicial. " + SECOND
         + " Su concepto sólo determina si el equipo puede seguir usándose.")


def inputs():
    request = inquiry(title="Revisión de cargo e inspección del equipo", description=(
        "Compare quién resuelve la revisión del cargo y quién hace la inspección técnica, "
        "indicando el efecto de cada actuación."))
    src = support(category="institutional_norm", role="rule", title="Manual de préstamos",
                  quote=(FIRST + " El ajuste sustituye el cargo inicial.\n"
                         + SECOND
                         + " Su concepto sólo determina si el equipo puede seguir usándose."))
    found = finding(supports=[src], missing=[{
        "kind": "norm", "description": "Comprobar la vigencia del manual.",
        "basis": "metadata_only", "reason_code": "validity", "stage": "evidence",
    }])
    plan = {"objective": "Explicar ambas actuaciones sin transferir efectos.", "points": [{
        "description": "Conservar la revisión y la inspección con sus efectos.",
        "cited_chunk_ids": ["S1"]}]}
    return request, found, plan


def ambiguous_check():
    return {"paragraph_0": {"status": "ambiguous",
        "no_effect_reason": "", "effect_readings": [{
            "effect_span": {"paragraph_index": 0, "word_start": 18, "word_end": 26},
            "antecedents": [
            {"paragraph_index": 0, "word_start": 1, "word_end": 9},
            {"paragraph_index": 0, "word_start": 10, "word_end": 17}],
            "explicit_anchor": None,
            "explanation": "El efecto puede leerse como propio de la revisión o de la inspección.",
        }]}}


def clear_check():
    return {"paragraph_0": {"status": "clear",
        "no_effect_reason": "", "effect_readings": [{
            "effect_span": {"paragraph_index": 0, "word_start": 10, "word_end": 18},
            "antecedents": [{"paragraph_index": 0, "word_start": 1, "word_end": 9}],
            "explicit_anchor": {"paragraph_index": 0, "word_start": 13, "word_end": 14},
            "explanation": ("El efecto se vincula expresamente a la revisión "
                            "y precede a la inspección."),
        }]}}


def source_check(status):
    result = proposed_check()
    result["procedure_scope_checks"] = [{
        "reading_id": "L1", "status": status,
        "cited_chunk_ids": ["S1"],
        "reason": ("El texto debe atribuir el ajuste a la revisión del cargo; "
                   "la inspección sólo decide si el equipo puede utilizarse."),
    }]
    return result


def worker(*responses, procedure_scope_pilot=True):
    engine = OpenAIDraftEngine(
        "fictitious", "test-model", procedure_scope_pilot=procedure_scope_pilot,
    )
    queue, calls = list(responses), []

    def parse(**kwargs):
        calls.append(kwargs)
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(status="completed",
            output_parsed=kwargs["text_format"].model_validate(response))

    engine.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    return engine, calls


def test_blind_pass_overrides_source_pass_repairs_effect_and_rechecks_everything():
    request, found, plan = inputs()
    before = deepcopy((request, found))
    engine, calls = worker(plan,
        {"paragraphs": [{"text": AMBIGUOUS, "cited_chunk_ids": ["S1"]}], "pending": []},
        ambiguous_check(), source_check("ambiguous"),
        {"paragraphs": [{"paragraph_index": 0, "text": CLEAR, "cited_chunk_ids": ["S1"]}]},
        clear_check(), source_check("supported"))
    result = build_draft_graph(engine, InMemorySaver()).invoke(
        {"request": request, "finding": found}, {"configurable": {"thread_id": "scope-repair"}})
    assert len(calls) == 7
    assert result["checks"]["status"] == "passed"
    assert result["repair"]["attempts"] == 1
    assert result["repair"]["before_checks"]["status"] == "needs_changes"
    assert any(i["code"] == "procedure_scope_ambiguous"
               for i in result["repair"]["before_checks"]["issues"])
    assert result["draft"]["paragraphs"][0]["text"] == CLEAR
    assert FIRST in CLEAR and SECOND in CLEAR
    assert result["draft"]["pending"] == result["repair"]["before_draft"]["pending"]
    assert result["draft"]["pending"][0]["reason_code"] == "validity"
    assert result["draft"]["paragraphs"][0]["cited_chunk_ids"] == [found["supports"][0]["chunk_id"]]
    for n, expected in ((2, AMBIGUOUS), (5, CLEAR)):
        payload = json.loads(calls[n]["input"])
        assert set(payload) == {"request_scope", "paragraphs"}
        p = payload["paragraphs"][0]
        assert p["paragraph_index"] == 0 and "text" not in p
        assert p["leading_whitespace"] + "".join(
            w["text"] if isinstance(w, dict) else w[1] for w in p["numbered_words"]
        ) == expected
        assert "Manual de préstamos" not in calls[n]["input"]
    document_check = json.loads(calls[3]["input"])
    assert document_check["procedure_scope_readings"][0]["effect_quote"] == EFFECT
    assert document_check["finding"]["supports"]
    assert (request, found) == before


def test_invalid_blind_check_cannot_return_the_previous_source_pass():
    request, found, proposed = inputs()
    engine, calls = worker(proposed, {})
    plan = engine.plan(request, found)
    draft = {"status": "needs_review", "paragraphs": [{"text": AMBIGUOUS,
             "cited_chunk_ids": [found["supports"][0]["chunk_id"]]}], "pending": []}
    before = deepcopy(draft)
    with pytest.raises(DomainError, match="salida inválida"):
        engine.check(request, found, plan, draft)
    assert len(calls) == 2 and draft == before


def test_unresolved_ambiguity_after_the_only_repair_still_blocks():
    request, found, plan = inputs()
    engine, calls = worker(plan,
        {"paragraphs": [{"text": AMBIGUOUS, "cited_chunk_ids": ["S1"]}], "pending": []},
        ambiguous_check(), source_check("ambiguous"), {"paragraphs": []},
        ambiguous_check(), source_check("ambiguous"))
    result = build_draft_graph(engine, InMemorySaver()).invoke(
        {"request": request, "finding": found}, {"configurable": {"thread_id": "still-ambiguous"}})
    assert len(calls) == 7 and result["checks"]["status"] == "needs_changes"
    assert result["draft"] == result["repair"]["before_draft"]
    assert result["repair"]["attempts"] == 1


def test_clear_but_wrong_interpretation_must_be_checked_against_its_source():
    request, found, proposed = inputs()
    reading = ambiguous_check()
    reading["paragraph_0"]["status"] = "clear"
    effect = reading["paragraph_0"]["effect_readings"][0]
    effect["antecedents"] = [effect["antecedents"][1]]
    effect["explanation"] = "El lector lo atribuye a la inspección recién mencionada."
    engine, calls = worker(proposed, reading, source_check("misattributed"))
    plan = engine.plan(request, found)
    draft = {"status": "needs_review", "paragraphs": [{"text": AMBIGUOUS,
             "cited_chunk_ids": [found["supports"][0]["chunk_id"]]}], "pending": []}
    original = deepcopy(draft)
    result = engine.check(request, found, plan, draft)
    assert result["status"] == "needs_changes"
    assert any(i["code"] == "procedure_scope_misattributed" for i in result["issues"])
    source_input = json.loads(calls[2]["input"])
    assert source_input["procedure_scope_readings"][0]["antecedents"][0]["quote"] == SECOND
    assert draft == original


def test_out_of_scope_citation_fails_before_dispatching_the_blind_pass():
    request, found, proposed = inputs()
    engine, calls = worker(proposed)
    plan = engine.plan(request, found)
    with pytest.raises(DomainError):
        engine.check(request, found, plan, {"status": "needs_review", "paragraphs": [{
            "text": AMBIGUOUS, "cited_chunk_ids": ["revoked-source"]}], "pending": []})
    assert len(calls) == 1


def test_empty_draft_keeps_pending_without_a_blind_api_call():
    request, found, _ = inputs()
    found["supports"] = []
    engine, calls = worker()
    plan = engine.plan(request, found)
    draft = engine.write(request, found, plan)
    before = deepcopy(draft)
    engine.check(request, found, plan, draft)
    assert calls == [] and draft == before and draft["pending"]


def test_default_engine_keeps_single_check_without_pilot_payload_or_schema():
    request, found, proposed = inputs()
    engine, calls = worker(proposed, proposed_check(), procedure_scope_pilot=False)
    plan = engine.plan(request, found)
    draft = {"status": "needs_evidence", "paragraphs": [{"text": CLEAR,
             "cited_chunk_ids": [found["supports"][0]["chunk_id"]]}],
             "pending": normalize_pending(request, found, [])}
    result = engine.check(request, found, plan, draft)
    assert result["status"] == "passed" and len(calls) == 2
    assert "procedure_scope_readings" not in json.loads(calls[1]["input"])
    assert "procedure_scope_checks" not in calls[1]["text_format"].model_fields


def test_pilot_switch_and_policy_separate_draft_fingerprints(monkeypatch):
    import pqrs_claro.draft_service as module

    service = object.__new__(DraftService)
    service.settings = Settings()
    case = {"identification": {}, "version": 1, "status": "ready"}
    baseline = service._fingerprint(case, {})
    service.settings = replace(service.settings, procedure_scope_pilot=True)
    pilot = service._fingerprint(case, {})
    assert pilot != baseline
    monkeypatch.setattr(module, "PROCEDURE_SCOPE_POLICY_HASH", "new-pilot-policy")
    assert service._fingerprint(case, {}) != pilot
    service.settings = replace(service.settings, procedure_scope_pilot=False)
    assert service._fingerprint(case, {}) == baseline
