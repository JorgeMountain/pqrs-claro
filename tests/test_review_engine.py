"""Revisión ficticia: atribución, referencias cerradas y aprobación recuperable."""

import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from openai import APIConnectionError
from pydantic import ValidationError

from pqrs_claro.models import DomainError
from pqrs_claro.review_engine import OpenAIReviewEngine
from pqrs_claro.review_graph import build_review_graph
from pqrs_claro.review_models import FactInput, PendingResolutionInput, ReviewApprove, ReviewEdit

HASH = "a" * 64


def inquiry(**changes):
    return {
        "id": "P1",
        "case_id": "caso-ficticio",
        "title": "Estado del trámite",
        "description": "Informe el estado del trámite al 7 de septiembre de 2026.",
        "allowed_collection_ids": ["coleccion-ficticia"],
        **changes,
    }


def support(**changes):
    return {
        "chunk_id": "oficio:1:1:1-2",
        "source_id": "source-1",
        "document_id": "oficio",
        "version": 1,
        "title": "Oficio 950 de 2026",
        "filename": "00950-2026_Respuesta.pdf",
        "sha256": HASH,
        "category": "historical_response",
        "role": "antecedent",
        "collection_id": "coleccion-ficticia",
        "case_id": None,
        "validity": "not_applicable",
        "review_status": "pending",
        "document_status": "issued",
        "verification_status": "reported_by_user",
        "verification_note": "El usuario informó que quien entregó los archivos los verificó.",
        "quote": "Al 7 de septiembre de 2026 el trámite estaba en revisión.",
        "page": 1,
        "line_start": 1,
        "line_end": 2,
        "location_kind": "page",
        "origin_selection": "automatic",
        **changes,
    }


def fact(**changes):
    return {
        "id": "fact-1",
        "text": "Consulté el sistema y el trámite estaba en revisión.",
        "author": "Responsable ficticio",
        "basis": "Consulta directa al sistema del trámite.",
        "observed_at": "2026-09-07",
        "recorded_at": "2026-09-07T15:00:00+00:00",
        "sha256": "b" * 64,
        **changes,
    }


def paragraph(**changes):
    return {
        "text": "El oficio 950 de 2026 informa que al 7 de septiembre de 2026 "
        "el trámite estaba en revisión.",
        "cited_chunk_ids": [support()["chunk_id"]],
        "cited_fact_ids": [],
        **changes,
    }


def pending(**changes):
    return {
        "id": "pending-1",
        "kind": "clarification",
        "description": "Confirmar la fecha de corte del estado.",
        "resolution": None,
        **changes,
    }


def resolution(**changes):
    return {
        "action": "resolved",
        "note": "La fecha aparece en el oficio citado.",
        "cited_chunk_ids": [support()["chunk_id"]],
        "cited_fact_ids": [],
        "by": "Responsable ficticio",
        "at": "2026-09-07T15:00:00+00:00",
        **changes,
    }


def review(**changes):
    return {
        "case_id": "caso-ficticio",
        "request_id": "P1",
        "paragraphs": [paragraph()],
        "available_supports": [support()],
        "facts": [],
        "pending": [],
        **changes,
    }


def provider_result(**changes):
    return {"status": "passed", "issues": [], **changes}


def issue(**changes):
    return {
        "code": "claim_not_supported",
        "description": "S1 no sustenta la afirmación actual.",
        "paragraph_index": 0,
        **changes,
    }


def engine(value=None):
    worker = OpenAIReviewEngine("fictitious-key", "test-model")
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        result = value if value is not None else provider_result()
        if isinstance(result, Exception):
            raise result
        if hasattr(result, "status"):
            return result
        return SimpleNamespace(
            status="completed", output_parsed=kwargs["text_format"].model_validate(result)
        )

    worker.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    return worker, calls


def test_assess_is_one_structured_call_without_changing_human_content():
    worker, calls = engine()
    value = review(pending=[pending(resolution=resolution())])
    before = deepcopy(value)
    result = worker.assess(inquiry(), value)
    assert result["status"] == "passed"
    assert len(calls) == 1
    assert calls[0]["store"] is False
    assert calls[0]["truncation"] == "disabled"
    assert value == before
    assert set(result) == {"status", "issues", "local_checks"}
    context = json.loads(calls[0]["input"])
    assert context["review"]["paragraphs"][0]["cited_chunk_ids"] == ["S1"]
    assert context["review"]["available_supports"][0]["quote"] == support()["quote"]
    assert context["review"]["pending"][0]["id"] == "M1"
    assert context["review"]["pending"][0]["resolution"]["cited_chunk_ids"] == ["S1"]


@pytest.mark.parametrize("sections", [
    ["context"], ["conclusion"], ["context", "conclusion"],
])
def test_context_and_conclusion_alone_cannot_pass_as_a_response(sections):
    worker, calls = engine()
    value = review(paragraphs=[paragraph(office_section=section) for section in sections])
    original = deepcopy(value)
    result = worker.assess(inquiry(), value)
    assert result["status"] == "needs_changes"
    assert {item["code"] for item in result["issues"]} == {"response_section_present"}
    assert result["issues"][0]["paragraph_index"] is None
    assert calls == []
    assert value == original


@pytest.mark.parametrize("section", [None, "response"])
def test_legacy_or_explicit_response_with_context_keeps_cites_and_can_be_reviewed(section):
    worker, calls = engine()
    answer = paragraph(**({"office_section": section} if section else {}))
    value = review(paragraphs=[paragraph(office_section="context"), answer])
    original = deepcopy(value)
    result = worker.assess(inquiry(), value)
    assert result["status"] == "passed"
    assert len(calls) == 1
    paragraphs = json.loads(calls[0]["input"])["review"]["paragraphs"]
    assert [item["office_section"] for item in paragraphs] == ["context", "response"]
    assert [item["cited_chunk_ids"] for item in paragraphs] == [["S1"], ["S1"]]
    assert value == original


def test_context_section_does_not_exempt_its_paragraph_from_citations():
    worker, calls = engine()
    result = worker.assess(inquiry(), review(paragraphs=[
        paragraph(office_section="context", cited_chunk_ids=[]), paragraph(),
    ]))
    assert result["status"] == "needs_changes"
    assert any(item["code"] == "paragraph_cited" and item["paragraph_index"] == 0
               for item in result["issues"])
    assert calls == []


def test_written_declaration_can_sustain_attributed_fact_without_attachment():
    worker, calls = engine()
    result = worker.assess(
        inquiry(),
        review(
            available_supports=[],
            facts=[fact()],
            paragraphs=[
                paragraph(
                    text="Según la consulta que declaró Responsable ficticio, al 7 de septiembre "
                    "de 2026 el trámite estaba en revisión.",
                    cited_chunk_ids=[],
                    cited_fact_ids=["fact-1"],
                )
            ],
        ),
    )
    assert result["status"] == "passed"
    body = json.loads(calls[0]["input"])["review"]
    assert body["paragraphs"][0]["cited_fact_ids"] == ["F1"]
    assert body["facts"][0]["basis"] == fact()["basis"]
    assert body["facts"][0]["author"] == fact()["author"]


def test_candidate_is_available_but_not_silently_cited_in_other_paragraph():
    worker, calls = engine()
    extra = support(chunk_id="candidate-1", source_id="source-2", origin_selection="candidate")
    worker.assess(inquiry(), review(available_supports=[support(), extra]))
    body = json.loads(calls[0]["input"])["review"]
    assert body["available_supports"][1]["chunk_id"] == "S2"
    assert body["paragraphs"][0]["cited_chunk_ids"] == ["S1"]


@pytest.mark.parametrize(
    "changes",
    [
        {"case_id": "otro"},
        {"collection_id": "no-vinculada"},
        {"role": "rule"},
        {"validity": "superseded"},
        {"sha256": "inventado"},
        {"line_end": 0},
        {"line_start": 3, "line_end": 2},
        {"version": True},
        {"quote": " "},
        {"origin_selection": "inventada"},
        {"location_kind": "inventada"},
    ],
)
def test_invalid_source_is_rejected_before_provider(changes):
    worker, calls = engine()
    with pytest.raises(DomainError):
        worker.assess(inquiry(), review(available_supports=[support(**changes)]))
    assert not calls


@pytest.mark.parametrize("changes", [{"case_id": "otro"}, {"request_id": "P2"}])
def test_review_and_fact_scopes_are_bound_to_request(changes):
    worker, calls = engine()
    with pytest.raises(DomainError):
        worker.assess(inquiry(), review(**changes))
    with pytest.raises(DomainError):
        worker.assess(inquiry(), review(facts=[fact(**changes)]))
    assert not calls


@pytest.mark.parametrize(
    "value,code",
    [
        (review(paragraphs=[]), "response_present"),
        (review(paragraphs=[paragraph(cited_chunk_ids=[])]), "paragraph_cited"),
        (review(paragraphs=[paragraph(cited_chunk_ids=["retirada"])]), "current_references"),
        (review(paragraphs=[paragraph(cited_fact_ids=["retirado"])]), "current_references"),
        (
            review(pending=[pending(resolution=resolution(cited_fact_ids=["retirado"]))]),
            "current_resolution_references",
        ),
    ],
)
def test_dangling_references_and_missing_response_return_actionable_checks_without_api(value, code):
    worker, calls = engine()
    before = deepcopy(value)
    result = worker.assess(inquiry(), value)
    assert result["status"] == "needs_changes"
    assert any(item["code"] == code for item in result["issues"])
    assert not calls
    assert value == before


def test_open_pending_blocks_passed_even_when_provider_says_passed():
    worker, _ = engine()
    result = worker.assess(inquiry(), review(pending=[pending()]))
    assert result["status"] == "needs_changes"
    assert any(item["code"] == "pending_closed" for item in result["issues"])


def test_later_signature_remains_visible_without_circular_approval_requirement():
    worker, calls = engine()
    value = review(pending=[pending(
        description="Tramitar la firma de esta respuesta aprobada.",
        stage="fulfillment", blocks_approval=False,
    )])
    result = worker.assess(inquiry(), value)
    assert result["status"] == "passed"
    assert value["pending"][0]["resolution"] is None
    assert json.loads(calls[0]["input"])["review"]["pending"][0]["stage"] == "fulfillment"
    assert any(item["code"] == "fulfillment_deferred" for item in result["local_checks"])


def test_required_independent_action_still_blocks_final_approval():
    worker, _ = engine()
    result = worker.assess(inquiry(), review(pending=[pending(
        description="Obtener la certificación independiente exigida para esta respuesta.",
        stage="fulfillment", blocks_approval=True,
    )]))
    assert result["status"] == "needs_changes"
    assert any(item["code"] == "pending_closed" for item in result["issues"])


def test_evidence_check_cannot_disguise_itself_as_nonblocking():
    worker, _ = engine()
    with pytest.raises(DomainError, match="comprobación de evidencia"):
        worker.assess(inquiry(), review(pending=[pending(stage="evidence", blocks_approval=False)]))


def test_declaration_cannot_replace_requested_document():
    worker, _ = engine()
    value = review(
        facts=[fact()],
        pending=[
            pending(
                kind="document",
                resolution=resolution(cited_chunk_ids=[], cited_fact_ids=["fact-1"]),
            )
        ],
    )
    result = worker.assess(inquiry(), value)
    assert result["status"] == "needs_changes"
    assert any(item["code"] == "document_resolution_has_file" for item in result["issues"])


def test_rule_cannot_replace_requested_document():
    worker, _ = engine()
    value = review(
        available_supports=[support(category="institutional_norm", role="rule")],
        pending=[pending(kind="document", resolution=resolution())],
    )
    result = worker.assess(inquiry(), value)
    assert result["status"] == "needs_changes"
    assert any(item["code"] == "document_resolution_has_file" for item in result["issues"])


def test_not_applicable_is_sent_for_critical_review_and_does_not_override_provider_issue():
    worker, calls = engine(
        provider_result(
            status="needs_changes",
            issues=[
                issue(
                    code="unjustified_resolution",
                    description="M1 no queda justificado por F1.",
                    paragraph_index=None,
                )
            ],
        )
    )
    value = review(
        facts=[fact()],
        pending=[
            pending(
                resolution=resolution(
                    action="not_applicable",
                    note="No aplica porque queremos terminar.",
                    cited_chunk_ids=[],
                    cited_fact_ids=["fact-1"],
                )
            )
        ],
    )
    result = worker.assess(inquiry(), value)
    assert result["status"] == "needs_changes"
    assert "Responsable ficticio" in result["issues"][0]["description"]
    assert "Confirmar la fecha" in result["issues"][0]["description"]
    assert json.loads(calls[0]["input"])["review"]["pending"][0]["resolution"]["action"] == (
        "not_applicable"
    )


def test_prior_verification_is_preserved_and_draft_filename_overrides_issued_metadata():
    worker, calls = engine()
    worker.assess(inquiry(), review(available_supports=[support(filename="Oficio XXXX.pdf")]))
    source = json.loads(calls[0]["input"])["review"]["available_supports"][0]
    assert source["document_status"] == "draft"
    assert source["verification_status"] == "reported_by_user"
    assert source["verification_note"] == support()["verification_note"]


def test_provider_issue_is_preserved_without_narrow_historical_attribution_regex():
    worker, _ = engine(provider_result(issues=[issue()]))
    result = worker.assess(inquiry(), review())
    assert result["status"] == "needs_changes"
    assert "Oficio 950 de 2026" in result["issues"][0]["description"]
    assert "S1" not in result["issues"][0]["description"]


@pytest.mark.parametrize(
    "value",
    [
        provider_result(issues=[issue(paragraph_index=1)]),
        provider_result(issues=[issue(description="F9 confirma el resultado.")]),
        provider_result(approval={"approved_by": "IA"}),
        SimpleNamespace(status="incomplete", output_parsed=None),
    ],
)
def test_invalid_provider_response_cannot_be_saved(value):
    worker, _ = engine(value)
    with pytest.raises(DomainError):
        worker.assess(inquiry(), review())


def test_provider_failure_is_recoverable_without_leaking_details():
    worker, _ = engine(APIConnectionError(request=SimpleNamespace(), message="secret-value"))
    with pytest.raises(DomainError, match="puedes reintentar") as error:
        worker.assess(inquiry(), review())
    assert "secret-value" not in str(error.value)


def test_needs_changes_without_issues_is_not_accepted_as_passed():
    worker, _ = engine(provider_result(status="needs_changes"))
    result = worker.assess(inquiry(), review())
    assert result["status"] == "needs_changes"
    assert result["issues"][0]["code"] == "assessment_incomplete"


def test_more_than_32_supports_or_30_facts_is_rejected_without_truncation():
    worker, calls = engine()
    with pytest.raises(DomainError):
        worker.assess(
            inquiry(), review(available_supports=[support(chunk_id=f"c-{n}") for n in range(33)])
        )
    with pytest.raises(DomainError):
        worker.assess(inquiry(), review(facts=[fact(id=f"f-{n}") for n in range(31)]))
    assert not calls


def test_required_human_details_and_exact_confirmation_are_validated():
    for field, invalid in (
        ("author", " "),
        ("basis", " "),
        ("observed_at", "2026-02-30"),
        ("observed_at", "2026090700"),
    ):
        data = {key: fact()[key] for key in ("text", "author", "basis", "observed_at")}
        with pytest.raises(ValidationError):
            FactInput.model_validate({"revision": 1, **data, field: invalid})
    for confirmed in (False, 1, "true"):
        with pytest.raises(ValidationError):
            ReviewApprove.model_validate(
                {
                    "revision": 1,
                    "assessment_hash": HASH,
                    "approved_by": "Responsable",
                    "confirmed": confirmed,
                }
            )
    for action in ("resolved", "not_applicable"):
        with pytest.raises(ValidationError):
            PendingResolutionInput.model_validate({"pending_id": "p", "action": action})
    with pytest.raises(ValidationError):
        ReviewEdit.model_validate({"revision": 1, "edited_by": " ", "paragraphs": []})


class PassingEngine:
    def __init__(self):
        self.calls = 0

    def assess(self, request, value):
        self.calls += 1
        return {"status": "passed", "issues": [], "local_checks": []}


def graph_state(**changes):
    return {"request": inquiry(), "review": review(), "input_hash": HASH, **changes}


def approval_decision(**changes):
    return {
        "approved_by": "Responsable ficticio",
        "note": "Solo prueba ficticia.",
        "confirmed": True,
        "input_hash": HASH,
        **changes,
    }


def test_graph_waits_for_explicit_human_decision_and_does_not_repeat_assessment():
    worker = PassingEngine()
    graph = build_review_graph(worker, InMemorySaver())
    config = {"configurable": {"thread_id": "test-approval"}}
    result = graph.invoke(graph_state(), config)
    assert result["assessment"]["status"] == "passed"
    assert result["approval"] is None
    assert result["__interrupt__"][0].value["kind"] == "review_approval"
    assert graph.get_state(config).next == ("esperar_aprobacion",)
    approved = graph.invoke(Command(resume=approval_decision()), config)
    assert worker.calls == 1
    assert approved["approval"]["approved_by"] == "Responsable ficticio"
    assert approved["approval"]["input_hash"] == HASH
    assert approved["approval"]["approved_at"]
    assert graph.get_state(config).next == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": False},
        {"confirmed": "true"},
        {"approved_by": " "},
        {"input_hash": "b" * 64},
        {"approval": {"approved_by": "IA"}},
    ],
)
def test_resume_rejects_missing_confirmation_wrong_hash_or_injected_fields(changes):
    graph = build_review_graph(PassingEngine(), InMemorySaver())
    config = {"configurable": {"thread_id": "invalid-approval"}}
    graph.invoke(graph_state(), config)
    with pytest.raises(DomainError):
        graph.invoke(Command(resume=approval_decision(**changes)), config)
    assert graph.get_state(config).values["approval"] is None


@pytest.mark.parametrize(
    "value",
    [
        review(paragraphs=[]),
        review(pending=[pending()]),
        review(paragraphs=[paragraph(cited_chunk_ids=[])]),
        review(paragraphs=[paragraph(cited_chunk_ids=["retirada"])]),
        review(paragraphs=[paragraph(office_section="context")]),
    ],
)
def test_graph_independently_blocks_structural_gaps_even_with_a_passing_engine(value):
    graph = build_review_graph(PassingEngine(), InMemorySaver())
    config = {"configurable": {"thread_id": "gap"}}
    result = graph.invoke(graph_state(review=value), config)
    assert result["assessment"]["status"] == "needs_changes"
    assert result["approval"] is None
    assert "__interrupt__" not in result
    assert graph.get_state(config).next == ()


@pytest.mark.parametrize(
    "change",
    [
        {"input_hash": "b" * 64},
        {"review": review(paragraphs=[paragraph(text="Texto cambiado después de comprobar.")])},
    ],
)
def test_content_or_hash_change_while_waiting_invalidates_approval(change):
    graph = build_review_graph(PassingEngine(), InMemorySaver())
    config = {"configurable": {"thread_id": "changed"}}
    graph.invoke(graph_state(), config)
    graph.update_state(config, change)
    with pytest.raises(DomainError, match="versión cambió"):
        graph.invoke(Command(resume=approval_decision()), config)
    assert graph.get_state(config).values["approval"] is None


def test_sqlite_interrupt_survives_rebuilding_graph_and_connection(tmp_path):
    path = tmp_path / "review-checkpoints.sqlite"
    worker = PassingEngine()
    config = {"configurable": {"thread_id": "durable-review"}}
    with sqlite3.connect(path, check_same_thread=False) as connection:
        graph = build_review_graph(worker, SqliteSaver(connection))
        graph.invoke(graph_state(), config)
    with sqlite3.connect(path, check_same_thread=False) as connection:
        graph = build_review_graph(worker, SqliteSaver(connection))
        assert graph.get_state(config).next == ("esperar_aprobacion",)
        result = graph.invoke(Command(resume=approval_decision()), config)
    assert worker.calls == 1
    assert result["approval"]["input_hash"] == HASH


def test_engine_cannot_change_review_during_assessment():
    class MutatingEngine(PassingEngine):
        def assess(self, request, value):
            value["paragraphs"][0]["text"] = "Alterado"
            return super().assess(request, value)

    graph = build_review_graph(MutatingEngine(), InMemorySaver())
    with pytest.raises(DomainError, match="alteró el texto"):
        graph.invoke(graph_state(), {"configurable": {"thread_id": "mutating"}})


def test_long_inherited_pending_is_not_truncated_by_graph_output_schema():
    value = review(pending=[pending(description="Comprobar " + "dato " * 1000)])
    worker, _ = engine()
    graph = build_review_graph(worker, InMemorySaver())
    result = graph.invoke(graph_state(review=value), {"configurable": {"thread_id": "long"}})
    assert result["assessment"]["status"] == "needs_changes"
    assert value["pending"][0]["description"] in result["assessment"]["issues"][0]["description"]
