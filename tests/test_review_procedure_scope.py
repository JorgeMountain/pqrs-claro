"""Independent prose audit blocks approval without rewriting saved evidence/controls."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_review_service_api as service_tests
from langgraph.checkpoint.memory import InMemorySaver
from test_procedure_scope import encode_scope_response
from test_review_engine import HASH, inquiry, paragraph, pending, review, support
from test_review_service_api import approve, assess, current, prepare, save

from pqrs_claro import review_service
from pqrs_claro.models import DomainError
from pqrs_claro.review_engine import OpenAIReviewEngine
from pqrs_claro.review_graph import build_review_graph

review_app = service_tests.review_app

FIRST = "La revisión de la medición la resuelve un comité técnico."
SECOND = "La habilitación del equipo la decide una comisión de instrumentación."
EFFECT = "Su decisión sustituye el resultado inicial."
AMBIGUOUS = FIRST + " " + SECOND + " " + EFFECT
CLEAR = FIRST + " " + EFFECT + " " + SECOND
SAME_PROCEDURE_REFERENCE = "La solicitud de revisión se dirige al mismo comité."
SAME_PROCEDURE = FIRST + " " + SAME_PROCEDURE_REFERENCE + " " + EFFECT


def scope_text(paragraph):
    return paragraph["leading_whitespace"] + "".join(w[1] for w in paragraph["numbered_words"])


def scope_result(payload, *, ambiguous=False, invalid=False, closest_only=False):
    if invalid:
        return {}
    rows = []
    for p in payload["paragraphs"]:
        text = scope_text(p)
        is_ambiguous = ambiguous and text == AMBIGUOUS
        readings = []
        if EFFECT in text and FIRST in text:
            antecedents = [{"paragraph_index": p["paragraph_index"], "quote": FIRST}]
            if is_ambiguous:
                antecedents.append({"paragraph_index": p["paragraph_index"], "quote": SECOND})
            if closest_only and text == AMBIGUOUS:
                antecedents = [{"paragraph_index": p["paragraph_index"], "quote": SECOND}]
                is_ambiguous = False
            if text == SAME_PROCEDURE:
                antecedents.append({
                    "paragraph_index": p["paragraph_index"], "quote": SAME_PROCEDURE_REFERENCE,
                })
                is_ambiguous = True
            readings = [{
                "effect_quote": EFFECT, "antecedents": antecedents, "explicit_anchor": None,
                "explanation": "Dos posibles actuaciones." if is_ambiguous
                               else "El efecto precede a la introducción del otro procedimiento.",
            }]
        rows.append({
            "paragraph_index": p["paragraph_index"],
            "status": "ambiguous" if is_ambiguous else "clear",
            "effect_readings": readings,
            "no_effect_reason": "" if readings else "No atribuye efectos a procedimientos.",
        })
    return encode_scope_response({"paragraph_checks": rows}, payload)


def worker(*, ambiguous=True, invalid=False, reported_clear=False, closest_only=False,
           scope_judgment=None, omit_scope_checks=False):
    """Real two-pass engine; only the provider is replaced by declared responses."""
    engine = OpenAIReviewEngine("fictitious-key", "test-model", procedure_scope_pilot=True)
    calls = []

    def parse(**kwargs):
        payload = json.loads(kwargs["input"])
        calls.append((kwargs["text_format"], payload))
        if "request_scope" in payload:
            result = scope_result(payload, ambiguous=ambiguous, invalid=invalid,
                                  closest_only=closest_only)
            if reported_clear:
                for row in result.values():
                    row["status"] = "clear"
        else:
            result = {"status": "passed", "issues": [], "requirement_checks": [{
                "requirement_id": r["id"], "status": "answered", "paragraph_indexes": [0],
                "pending_indexes": [], "explanation": "Cobertura simulada por el doble.",
            } for r in payload["request"].get("request_requirements", [])]}
            if not omit_scope_checks:
                checks = []
                for reading in payload["procedure_scope_readings"]:
                    status = scope_judgment or (
                        "ambiguous" if ambiguous and len(reading["antecedents"]) > 1
                        else "supported"
                    )
                    checks.append({
                        "reading_id": reading["reading_id"], "status": status,
                        "cited_chunk_ids": ["S1"]
                                           if status in {"supported", "misattributed"} else [],
                        "reason": "El efecto se aplica a dos actuaciones sin distinguirlas."
                                  if status == "ambiguous" else
                                  "S1 atribuye ese efecto a la revisión, no a la habilitación."
                                  if status == "misattributed" else
                                  "S1 respalda el efecto para la revisión por el comité.",
                    })
                result["procedure_scope_checks"] = checks
        return SimpleNamespace(
            status="completed", output_parsed=kwargs["text_format"].model_validate(result),
        )

    engine.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    return engine, calls


def response(*, text=AMBIGUOUS, controls=True):
    return review(
        paragraphs=[paragraph(text=text)],
        available_supports=[support(quote="PASAJES-SECRETOS-DE-QA: " + FIRST + " " + EFFECT)],
        pending=[pending(description="Cotejar la procedencia del manual.", basis="metadata_only")]
                if controls else [],
    )


def test_scope_reader_cannot_use_sources_or_pending_to_resolve_ambiguous_prose():
    engine, calls = worker()
    value = response()
    before = deepcopy(value)
    result = engine.assess(inquiry(), value)
    assert len(calls) == 2
    assert result["status"] == "needs_changes"
    assert "procedure_scope_ambiguous" in {i["code"] for i in result["issues"]}
    assert "pending_closed" in {i["code"] for i in result["issues"]}
    assert value == before
    scope_payload = calls[0][1]
    assert set(scope_payload) == {"request_scope", "paragraphs"}
    assert len(scope_payload["paragraphs"]) == 1
    assert scope_payload["paragraphs"][0]["paragraph_index"] == 0
    assert scope_text(scope_payload["paragraphs"][0]) == AMBIGUOUS
    assert "text" not in scope_payload["paragraphs"][0]
    serialized = json.dumps(scope_payload)
    assert "PASAJES-SECRETOS" not in serialized and "Cotejar la procedencia" not in serialized
    assert "cited_chunk_ids" not in serialized and "coverage_units" not in serialized
    source_payload = calls[1][1]
    assert source_payload["procedure_scope_readings"]
    assert "PASAJES-SECRETOS" in json.dumps(source_payload)


@pytest.mark.parametrize("reported_clear", [False, True])
def test_semantic_evidence_pass_does_not_offer_approval_when_reading_check_finds_ambiguity(
    reported_clear,
):
    engine, calls = worker(reported_clear=reported_clear)
    result = build_review_graph(engine, InMemorySaver()).invoke(
        {"request": inquiry(), "review": response(controls=False), "input_hash": HASH},
        {"configurable": {"thread_id": "ambiguous-but-cited"}},
    )
    assert len(calls) == 2
    assert result["assessment"]["status"] == "needs_changes"
    assert result["approval"] is None and "__interrupt__" not in result


def test_clear_reference_preserves_future_fulfillment_without_circular_evidence_requirement():
    engine, _ = worker()
    value = response(text=CLEAR, controls=False)
    value["pending"] = [pending(description="Tramitar la firma de la futura respuesta.",
                                stage="fulfillment", blocks_approval=False)]
    before = deepcopy(value)
    result = engine.assess(inquiry(), value)
    assert result["status"] == "passed"
    assert any(c["code"] == "procedure_scope_review" and c["passed"]
               for c in result["local_checks"])
    assert value == before and value["pending"][0]["resolution"] is None


def test_closest_wrong_procedure_is_checked_against_sources_before_approval():
    engine, calls = worker(closest_only=True, scope_judgment="misattributed")
    value = response(controls=False)
    before = deepcopy(value)
    result = build_review_graph(engine, InMemorySaver()).invoke(
        {"request": inquiry(), "review": value, "input_hash": HASH},
        {"configurable": {"thread_id": "closest-referent-contradicts-source"}},
    )
    assert len(calls) == 2
    reading = calls[1][1]["procedure_scope_readings"][0]
    assert reading["blind_status"] == "clear" and len(reading["antecedents"]) == 1
    assert reading["antecedents"][0]["quote"] == SECOND
    assert result["assessment"]["status"] == "needs_changes"
    assert result["approval"] is None and "__interrupt__" not in result
    assert any("habilitación" in issue["description"] for issue in result["assessment"]["issues"])
    assert value == before


def test_two_spans_of_same_procedure_do_not_automatically_block_supported_response():
    engine, calls = worker(scope_judgment="supported")
    value = response(text=SAME_PROCEDURE, controls=False)
    result = engine.assess(inquiry(), value)
    reading = calls[1][1]["procedure_scope_readings"][0]
    assert len(reading["antecedents"]) == 2 and reading["blind_status"] == "ambiguous"
    assert result["status"] == "passed"
    assert not result["issues"]


def test_missing_source_judgment_fails_closed_without_changing_content_or_pending():
    engine, calls = worker(omit_scope_checks=True)
    value = response()
    before = deepcopy(value)
    with pytest.raises(DomainError):
        engine.assess(inquiry(), value)
    assert len(calls) == 2
    assert value == before


def test_scope_issue_labels_only_source_reason_and_keeps_literal_effect(monkeypatch):
    effect = "Su decisión sustituye el resultado inicial del lote F99."
    text = FIRST + " " + SECOND + " " + effect
    monkeypatch.setitem(globals(), "EFFECT", effect)
    monkeypatch.setitem(globals(), "AMBIGUOUS", text)
    engine, _ = worker(closest_only=True, scope_judgment="misattributed")
    value = response(text=text, controls=False)
    result = engine.assess(inquiry(), value)
    issue = next(i for i in result["issues"] if i["code"] == "procedure_scope_misattributed")
    assert effect in issue["description"]
    assert "Oficio 950 de 2026" in issue["description"]
    assert "S1" not in issue["description"]


def test_invalid_scope_check_fails_closed_without_editing_saved_pending_or_citations():
    engine, calls = worker(invalid=True)
    value = response()
    before = deepcopy(value)
    with pytest.raises(DomainError, match="salida inválida"):
        engine.assess(inquiry(), value)
    assert len(calls) == 1 and value == before


def test_scope_pass_preserves_existing_thirty_paragraph_six_thousand_character_limit():
    engine, calls = worker(ambiguous=False)
    value = response(text=CLEAR, controls=False)
    value["paragraphs"] = [paragraph(text="Contenido atribuido al oficio.") for _ in range(29)]
    value["paragraphs"].append(paragraph(text="Texto " * 1000))
    result = engine.assess(inquiry(), value)
    assert result["status"] == "passed" and len(calls) == 2
    assert len(calls[0][1]["paragraphs"]) == 30
    assert len(scope_text(calls[0][1]["paragraphs"][-1])) == 6000


def test_edit_discards_cached_scope_assessment_and_blocks_old_approval(review_app):
    app, client, _, _ = review_app
    app.state.reviews.settings = replace(app.state.reviews.settings, procedure_scope_pilot=True)
    case, _, row = prepare(app, client)
    engine, calls = worker()
    app.state.reviews.engine = engine
    row = save(client, case, row, paragraphs=[{**row["paragraphs"][0], "text": CLEAR}]).json()
    checked = assess(app, client, case, row)
    assert checked["assessment"]["status"] == "passed" and len(calls) == 2
    accepted = approve(client, case, checked)
    assert accepted.status_code == 200, accepted.text
    previous_pending = deepcopy(accepted.json()["pending"])
    edited = save(client, case, accepted.json(), paragraphs=[{
        **accepted.json()["paragraphs"][0], "text": AMBIGUOUS,
    }]).json()
    assert edited["assessment"] is None and edited["approval"] is None
    assert approve(client, case, checked).status_code == 409
    rejected = assess(app, client, case, edited)
    assert len(calls) == 4 and rejected["assessment"]["status"] == "needs_changes"
    assert rejected["pending"] == previous_pending
    assert approve(client, case, rejected).status_code == 409
    assert current(client, case)["approval"] is None


def test_failed_scope_call_keeps_service_text_and_legitimate_pending_for_retry(review_app):
    app, client, _, _ = review_app
    app.state.reviews.settings = replace(app.state.reviews.settings, procedure_scope_pilot=True)
    control = {"kind": "clarification", "description": "Cotejar la procedencia del soporte.",
               "basis": "metadata_only", "stage": "evidence", "reason_code": "provenance"}
    case, _, row = prepare(app, client, pending=[control])
    before = deepcopy(row)
    app.state.reviews.engine, calls = worker(invalid=True)
    result = assess(app, client, case, row)
    assert len(calls) == 1 and result["status"] == "error"
    assert result["paragraphs"] == before["paragraphs"] and result["pending"] == before["pending"]
    assert result["assessment"] is None and result["approval"] is None


def test_scope_policy_change_invalidates_approved_snapshot_without_rewriting_text(
    review_app, monkeypatch,
):
    app, client, _, _ = review_app
    app.state.reviews.settings = replace(app.state.reviews.settings, procedure_scope_pilot=True)
    case, _, row = prepare(app, client)
    checked = assess(app, client, case, row)
    accepted = approve(client, case, checked)
    assert accepted.status_code == 200
    before = accepted.json()
    monkeypatch.setattr(review_service, "PROCEDURE_SCOPE_POLICY_HASH", "b" * 64)
    invalidated = current(client, case)
    assert invalidated["stale"]
    assert invalidated["assessment"] is None and invalidated["approval"] is None
    assert invalidated["paragraphs"] == before["paragraphs"]
    assert invalidated["pending"] == before["pending"]
