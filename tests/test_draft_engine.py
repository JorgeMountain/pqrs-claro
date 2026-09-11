"""Borradores ficticios: referencias cerradas, límites históricos y recuperación."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pqrs_claro.draft_engine import OpenAIDraftEngine
from pqrs_claro.draft_graph import build_draft_graph
from pqrs_claro.models import DomainError


def pending_content(items):
    return [{key: item[key] for key in ("kind", "description")} for item in items]


def inquiry(**changes):
    return {
        "id": "P1",
        "title": "Decisión del comité",
        "description": "Explique qué respondió el comité sobre la plaza de prácticas en 2024.",
        "case_id": "nuevo-caso",
        "allowed_collection_ids": ["historia-ficticia"],
        **changes,
    }


def support(**changes):
    return {
        "chunk_id": "oficio:version1:p1:1-2",
        "source_id": "oficio-v1",
        "document_id": "oficio",
        "version": 1,
        "title": "Oficio 0123 de 2024",
        "filename": "oficio0123.pdf",
        "case_id": None,
        "collection_id": "historia-ficticia",
        "category": "historical_response",
        "document_status": "issued",
        "verification_status": "reported_by_user",
        "verification_note": "El usuario informó de verificación previa por quien entregó fuentes.",
        "review_status": "pending",
        "validity": "not_applicable",
        "role": "antecedent",
        "page": 1,
        "line_start": 1,
        "line_end": 2,
        "quote": "En 2024 el comité informó que aprobó la plaza de prácticas.\nMencionó el acta.",
        "reason": "Contenido atribuido a una respuesta anterior.",
        **changes,
    }


def finding(**changes):
    return {
        "request_id": "P1",
        "status": "needs_evidence",
        "supports": [support()],
        "missing": [
            {"kind": "clarification", "description": "Cotejar la aplicabilidad al trámite actual."}
        ],
        "warnings": [],
        **changes,
    }


def proposed_plan(ids=None):
    return {
        "objective": "Explicar el contenido de la respuesta previa y sus límites.",
        "points": [
            {
                "description": "Atribuir lo respondido al oficio de 2024.",
                "cited_chunk_ids": ["S1"] if ids is None else ids,
            }
        ],
    }


def proposed_draft(text=None, ids=None):
    return {
        "paragraphs": [
            {
                "text": text or "Según el oficio 0123 de 2024, el comité informó la aprobación.",
                "cited_chunk_ids": ["S1"] if ids is None else ids,
            }
        ],
        "pending": [],
    }


def proposed_check(**changes):
    return {"status": "passed", "issues": [], **changes}


def candidate_document():
    return {
        "source_id": "candidate",
        "document_id": "candidate-doc",
        "version": 1,
        "title": "Oficio candidato 0999 de 2023",
        "filename": "oficio0999.pdf",
        "category": "historical_response",
        "location_status": "candidate_located",
        "selected_as_support": False,
        "chunks": [
            {
                "chunk_id": "candidate:1",
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "quote": "En 2023 se respondió acerca de otra plaza.",
                "location_kind": "page",
            }
        ],
    }


def engine(*values):
    result = OpenAIDraftEngine("fictitious-key-for-tests", "test-model")
    calls = []
    queue = list(values)

    def parse(**kwargs):
        calls.append(kwargs)
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        if hasattr(value, "status"):
            return value
        return SimpleNamespace(
            status="completed", output_parsed=kwargs["text_format"].model_validate(value)
        )

    result.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    return result, calls


def run(text=None, source=None, request=None, source_finding=None, check=None):
    request = request or inquiry()
    source_finding = source_finding or finding(supports=[source or support()])
    worker, calls = engine(proposed_plan(), proposed_draft(text), check or proposed_check())
    plan = worker.plan(request, source_finding)
    draft = worker.write(request, source_finding, plan)
    checks = worker.check(request, source_finding, plan, draft)
    return plan, draft, checks, calls


def test_three_structured_calls_keep_literal_sources_and_never_approve():
    source_finding = finding()
    before = deepcopy(source_finding)
    plan, draft, checks, calls = run(source_finding=source_finding)
    assert len(calls) == 3
    assert source_finding == before
    assert draft["status"] == "needs_evidence"
    assert pending_content(draft["pending"]) == source_finding["missing"]
    assert checks["status"] == "passed"
    assert plan["points"][0]["cited_chunk_ids"] == [support()["chunk_id"]]
    assert draft["paragraphs"][0]["cited_chunk_ids"] == [support()["chunk_id"]]
    assert "quote" not in draft["paragraphs"][0]
    for call in calls:
        payload = json.loads(call["input"])
        assert payload["finding"]["supports"][0]["quote"] == support()["quote"]
        assert payload["finding"]["supports"][0]["chunk_id"] == "S1"
        assert call["store"] is False
        assert call["truncation"] == "disabled"
        assert call["model"] == "test-model"
    assert json.loads(calls[1]["input"])["plan"]["points"][0]["cited_chunk_ids"] == ["S1"]
    assert json.loads(calls[2]["input"])["draft"]["paragraphs"][0]["cited_chunk_ids"] == ["S1"]


def test_sources_without_pending_still_require_human_review():
    _, draft, checks, _ = run(source_finding=finding(status="references_found", missing=[]))
    assert draft["status"] == "needs_review"
    assert checks["status"] == "passed"
    assert "approved" not in draft


def test_natural_historical_prose_keeps_internal_citations_without_display_labels():
    texts = [
        "El comité informó la aprobación de la plaza en el Oficio 0123 de 2024.",
        "Esa respuesta histórica describe la aprobación informada por el comité; "
        "no acredita por sí sola una decisión actual.",
    ]
    proposal = proposed_draft()
    proposal["paragraphs"] = [{"text": text, "cited_chunk_ids": ["S1"]} for text in texts]
    worker, calls = engine(proposed_plan(), proposal, proposed_check())
    selected = finding()
    plan = worker.plan(inquiry(), selected)
    draft = worker.write(inquiry(), selected, plan)
    checks = worker.check(inquiry(), selected, plan, draft)
    assert checks["status"] == "passed"
    assert [paragraph["text"] for paragraph in draft["paragraphs"]] == texts
    assert [paragraph["cited_chunk_ids"] for paragraph in draft["paragraphs"]] == [
        [support()["chunk_id"]], [support()["chunk_id"]],
    ]
    assert pending_content(draft["pending"]) == selected["missing"]
    payload = json.loads(calls[-1]["input"])
    assert [paragraph["text"] for paragraph in payload["draft"]["paragraphs"]] == texts
    assert all(paragraph["cited_chunk_ids"] == ["S1"]
               for paragraph in payload["draft"]["paragraphs"])
    assert payload["local_reference_labels"]  # La ubicación sigue disponible internamente.


def test_natural_attribution_does_not_authorize_an_unverified_current_claim():
    text = "El comité informó la aprobación de la plaza en el Oficio 0123 de 2024. "
    text += "Actualmente la plaza está aprobada."
    _, draft, checks, _ = run(text=text)
    assert draft["paragraphs"][0]["text"] == text
    assert checks["status"] == "needs_changes"
    assert any(issue["code"] == "historical_current_fact" for issue in checks["issues"])


@pytest.mark.parametrize("ids", [["S2"], ["S1", "S1"], ["oficio-v1"], ["s1"], [" S1"]])
def test_plan_rejects_unknown_near_or_duplicate_aliases(ids):
    worker, _ = engine(proposed_plan(ids))
    with pytest.raises(DomainError, match="fragmento desconocido o repetido"):
        worker.plan(inquiry(), finding())


@pytest.mark.parametrize("ids", [["S2"], ["S1", "S1"], ["oficio-v1"]])
def test_writing_rejects_invented_references(ids):
    worker, _ = engine(proposed_plan(), proposed_draft(ids=ids))
    plan = worker.plan(inquiry(), finding())
    with pytest.raises(DomainError, match="fragmento desconocido o repetido"):
        worker.write(inquiry(), finding(), plan)


def test_writing_requires_reference_for_every_substantive_paragraph():
    worker, _ = engine(proposed_plan(), proposed_draft(ids=[]))
    plan = worker.plan(inquiry(), finding())
    with pytest.raises(DomainError, match="incompleto"):
        worker.write(inquiry(), finding(), plan)


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "fact"},
        {"category": "national_norm", "role": "antecedent"},
        {"category": "previous_response"},
        {"collection_id": "otro-corpus"},
        {"case_id": "otro-caso"},
        {"validity": "superseded"},
        {"quote": " "},
    ],
)
def test_invalid_sources_are_rejected_before_sending_to_provider(changes):
    worker, calls = engine()
    with pytest.raises(DomainError):
        worker.plan(inquiry(), finding(supports=[support(**changes)]))
    assert calls == []


def test_candidate_inventory_is_visible_for_comparison_but_has_no_citable_alias():
    source_finding = finding(
        candidate_documents=[candidate_document()],
        selection_status="additional_candidates_available",
    )
    _, draft, checks, calls = run(source_finding=source_finding)
    for call in calls:
        context = json.loads(call["input"])["finding"]
        assert context["selection_status"] == "additional_candidates_available"
        assert context["candidate_documents"][0]["citable"] is False
        assert context["candidate_documents"][0]["chunks"][0]["chunk_id"] == "candidate:1"
        assert context["candidate_documents"][0]["chunks"][0]["quote"] == (
            candidate_document()["chunks"][0]["quote"]
        )
        assert [item["chunk_id"] for item in context["supports"]] == ["S1"]
    assert pending_content(draft["pending"]) == source_finding["missing"]
    assert checks["status"] == "passed"


@pytest.mark.parametrize("ids", [["candidate:1"], ["candidate"], ["S2"]])
def test_candidate_inventory_does_not_authorize_extra_citations(ids):
    source_finding = finding(candidate_documents=[candidate_document()])
    worker, _ = engine(proposed_plan(), proposed_draft(ids=ids))
    plan = worker.plan(inquiry(), source_finding)
    with pytest.raises(DomainError, match="fragmento desconocido o repetido"):
        worker.write(inquiry(), source_finding, plan)


def test_citing_a_support_does_not_justify_a_year_only_found_in_candidate():
    _, _, checks, _ = run(
        text="Según el oficio 0123, el comité aprobó la plaza en 2023.",
        source_finding=finding(candidate_documents=[candidate_document()]),
    )
    assert checks["status"] == "needs_changes"
    assert "period_grounded" in {item["code"] for item in checks["issues"]}


def test_localized_candidate_missing_retains_action_without_becoming_support():
    missing = {
        "kind": "clarification",
        "description": "Cotejar integridad del acta candidata localizada.",
        "linked_source_ids": ["candidate"],
        "linked_chunk_ids": ["candidate:1"],
    }
    _, draft, checks, _ = run(source_finding=finding(missing=[missing]))
    assert pending_content(draft["pending"]) == pending_content([missing])
    assert draft["pending"][0]["linked_source_ids"] == ["candidate"]
    assert draft["pending"][0]["linked_chunk_ids"] == ["candidate:1"]
    assert draft["pending"][0]["request_ids"] == ["P1"]
    assert checks["status"] == "passed"
    assert draft["paragraphs"][0]["cited_chunk_ids"] == [support()["chunk_id"]]


def test_no_sources_produce_only_internal_pending_without_any_model_call():
    worker, calls = engine()
    state = build_draft_graph(worker, InMemorySaver()).invoke(
        {"request": inquiry(), "finding": finding(supports=[], missing=[], status="no_matches")},
        {"configurable": {"thread_id": "no-sources"}},
    )
    assert calls == []
    assert state["draft"]["paragraphs"] == []
    assert state["draft"]["status"] == "needs_evidence"
    assert "no demuestra inexistencia" in state["draft"]["pending"][0]["description"]


@pytest.mark.parametrize(
    "text,code",
    [
        ("El comité aprobó la plaza de prácticas.", "historical_attribution"),
        ("Según el oficio 0123 de 2024, el comité aprobó la plaza en 2025.", "period_grounded"),
        ("Según el oficio de 2024, actualmente la plaza está aprobada.", "historical_current_fact"),
        ("Según el oficio de 2024, se adjunta el acta.", "no_operational_claim"),
        ("Según el oficio de 2024, se certifica que la plaza se aprobó.", "no_operational_claim"),
        ("No existe el acta solicitada.", "no_nonexistence_inference"),
        ("Se niega la petición.", "no_operational_claim"),
    ],
)
def test_local_controls_override_model_pass_when_context_or_evidence_is_wrong(text, code):
    _, draft, checks, _ = run(text=text)
    assert draft["status"] == "needs_evidence"
    assert checks["status"] == "needs_changes"
    assert code in {issue["code"] for issue in checks["issues"]}


def test_new_certification_remains_future_action_even_if_model_omits_it():
    request = inquiry(description="Certifique que se aprobó la plaza de prácticas en 2024.")
    _, draft, _, _ = run(request=request, source_finding=finding(missing=[]))
    assert any(
        item["stage"] == "fulfillment" and "certificación solicitada" in item["description"]
        for item in draft["pending"]
    )
    assert draft["status"] == "needs_review"
    assert all(item["state"] != "document_missing" for item in draft["pending"])


def test_question_about_who_issued_certificate_adds_no_issuance_action():
    request = inquiry(description="Solicito aclarar quién expidió la certificación en 2024.")
    _, draft, _, _ = run(request=request, source_finding=finding(missing=[]))
    assert draft["pending"] == []
    assert draft["status"] == "needs_review"


def test_structured_check_is_preserved_through_write_and_check_calls():
    item = {
        "kind": "clarification", "description": "Cotejar el periodo del antecedente.",
        "check_key": "check-period", "id": "check-period", "reason_code": "applicability",
        "state": "confirmation_pending", "stage": "evidence", "scope_key": "person-period",
        "request_ids": ["P1"], "linked_source_ids": ["oficio-v1"],
        "linked_chunk_ids": [support()["chunk_id"]],
        "source_versions": [{"source_id": "oficio-v1", "version": 1}],
        "resolution": {"status": "open"},
    }
    _, draft, checks, calls = run(source_finding=finding(missing=[item], checks=[item]))
    assert draft["pending"] == [item]
    assert json.loads(calls[2]["input"])["draft"]["pending"] == [item]
    assert checks["status"] == "passed"


def test_resolved_structured_check_is_not_reintroduced_by_redaction():
    from pqrs_claro.evidence_contract import normalize_pending

    source_finding = finding()
    resolved = normalize_pending(inquiry(), source_finding, [])[0]
    resolved["resolution"] = {"status": "resolved", "verification_id": "verification-1"}
    source_finding.update(missing=[], checks=[resolved], status="references_found")
    selected = proposed_draft()
    selected["pending"] = pending_content([resolved])
    worker, calls = engine(proposed_plan(), selected, proposed_check())
    plan = worker.plan(inquiry(), source_finding)
    draft = worker.write(inquiry(), source_finding, plan)
    worker.check(inquiry(), source_finding, plan, draft)
    assert draft["pending"] == []
    assert draft["status"] == "needs_review"
    assert json.loads(calls[2]["input"])["finding"]["checks"][0]["resolution"] == (
        resolved["resolution"]
    )


@pytest.mark.parametrize("resolved", [False, True])
def test_paraphrase_reuses_existing_check_without_changing_scope_or_resolution(resolved):
    from pqrs_claro.evidence_contract import normalize_pending

    request = inquiry(description="Solicito que se tramite la supervisión de esta respuesta.")
    source_finding = finding()
    existing = normalize_pending(request, source_finding, [])[0]
    existing["resolution"] = {"status": "resolved" if resolved else "open"}
    source_finding.update(checks=[existing], missing=[] if resolved else [existing])
    selected = proposed_draft()
    selected["pending"] = [{
        "kind": "document", "description": "Otra redacción del mismo control.",
        "existing_check_keys": [existing["check_key"]], "stage": "fulfillment",
    }]
    worker, calls = engine(proposed_plan(), selected, proposed_check())
    plan = worker.plan(request, source_finding)
    draft = worker.write(request, source_finding, plan)
    assert all(item["description"] != "Otra redacción del mismo control."
               for item in draft["pending"])
    matches = [item for item in draft["pending"] if item["check_key"] == existing["check_key"]]
    assert matches == ([] if resolved else [existing])
    assert existing in json.loads(calls[1]["input"])["existing_pending"]


def test_redactor_cannot_reference_a_check_from_another_question():
    selected = proposed_draft()
    selected["pending"] = [{"kind": "fact", "description": "Cotejar el periodo.",
                            "existing_check_keys": ["check-other-question"]}]
    worker, _ = engine(proposed_plan(), selected)
    plan = worker.plan(inquiry(), finding())
    with pytest.raises(DomainError, match="no corresponde a la pregunta"):
        worker.write(inquiry(), finding(), plan)


def test_new_pending_requires_a_concrete_uncovered_difference():
    selected = proposed_draft()
    selected["pending"] = [{"kind": "fact", "description": "Revisar todo de nuevo."}]
    worker, _ = engine(proposed_plan(), selected)
    plan = worker.plan(inquiry(), finding())
    with pytest.raises(DomainError, match="diferencia concreta"):
        worker.write(inquiry(), finding(), plan)


def test_reported_verification_does_not_turn_a_draft_office_into_issued():
    _, _, checks, calls = run(source=support(filename="Oficio_XXXX_2024.pdf"))
    assert checks["status"] == "needs_changes"
    assert "draft_status_preserved" in {item["code"] for item in checks["issues"]}
    payload = json.loads(calls[0]["input"])
    assert payload["finding"]["supports"][0]["verification_status"] == "reported_by_user"
    assert "fueron verificados previamente" in calls[0]["instructions"]


def test_model_semantic_issues_cannot_be_hidden_by_status_passed():
    _, _, checks, _ = run(
        check=proposed_check(
            issues=[
                {
                    "code": "unsupported_person",
                    "description": "El párrafo cambia la persona a quien se refiere el oficio.",
                    "paragraph_index": 0,
                }
            ]
        )
    )
    assert checks["status"] == "needs_changes"


def test_model_failure_request_must_have_explanation():
    _, _, checks, _ = run(check=proposed_check(status="needs_changes"))
    assert checks["issues"][0]["code"] == "incomplete_review"
    assert checks["status"] == "needs_changes"


def test_reviewer_cannot_reference_a_nonexistent_paragraph():
    with pytest.raises(DomainError, match="párrafo que no existe"):
        run(
            check=proposed_check(
                issues=[
                    {"code": "problem", "description": "No está sustentado.", "paragraph_index": 20}
                ]
            )
        )


def test_interrupted_response_is_rejected_instead_of_saved_as_partial_plan():
    worker, _ = engine(SimpleNamespace(status="incomplete", output_parsed=None))
    with pytest.raises(DomainError, match="salida parcial"):
        worker.plan(inquiry(), finding())


def test_check_rejects_removed_source_pending_and_approval_status():
    worker, _ = engine(proposed_plan(), proposed_draft(), proposed_check())
    plan = worker.plan(inquiry(), finding())
    draft = worker.write(inquiry(), finding(), plan)
    draft["status"] = "approved"
    with pytest.raises(DomainError, match="pendiente de evidencia o revisión"):
        worker.check(inquiry(), finding(), plan, draft)
    draft["status"] = "needs_evidence"
    draft["pending"] = []
    checks = worker.check(inquiry(), finding(), plan, draft)
    assert "pending_preserved" in {issue["code"] for issue in checks["issues"]}


def test_checkpoint_resume_preserves_plan_and_draft_after_check_failure():
    worker, calls = engine(
        proposed_plan(),
        proposed_draft(),
        SimpleNamespace(status="incomplete", output_parsed=None),
        proposed_check(),
    )
    graph = build_draft_graph(worker, InMemorySaver())
    config = {"configurable": {"thread_id": "case:request:immutable-fingerprint"}}
    with pytest.raises(DomainError):
        graph.invoke({"request": inquiry(), "finding": finding()}, config)
    saved = graph.get_state(config)
    assert saved.next == ("comprobar",)
    assert "plan" in saved.values and "draft" in saved.values
    result = graph.invoke(None, config)
    assert result["checks"]["status"] == "passed"
    assert len(calls) == 4
    assert [call["text_format"].__name__ for call in calls] == [
        "_Plan", "_DraftSelection", "_Checks", "_Checks"
    ]


def test_inherited_pending_can_exceed_remote_selection_limit_without_truncation():
    inherited = [
        {"kind": "clarification", "description": f"Cotejar componente heredado {number}."}
        for number in range(78)
    ]
    proposed = [
        {"kind": "fact", "description": f"Confirmar dato propuesto {number}.",
         "difference": f"Dato adicional {number} no incluido en los componentes heredados."}
        for number in range(60)
    ]
    selected = proposed_draft()
    selected["pending"] = proposed
    worker, calls = engine(proposed_plan(), selected, proposed_check())
    source_finding = finding(missing=inherited)
    plan = worker.plan(inquiry(), source_finding)
    draft = worker.write(inquiry(), source_finding, plan)
    checks = worker.check(inquiry(), source_finding, plan, draft)
    assert pending_content(draft["pending"]) == inherited + pending_content(proposed)
    assert len(draft["pending"]) == 138
    assert len(json.loads(calls[2]["input"])["draft"]["pending"]) == 138
    assert checks["status"] == "passed"


def test_prose_aliases_are_materialized_with_original_title_and_location_in_every_step():
    selected_plan = proposed_plan()
    selected_plan["objective"] = "Explicar lo documentado por S1."
    selected_plan["points"][0]["description"] = "Atribuir a S1 el contenido de la respuesta."
    selected_draft = proposed_draft(text="Según S1, el comité informó la aprobación en 2024.")
    selected_draft["pending"] = [
        {"kind": "clarification", "description": "Cotejar la aplicabilidad de S1.",
         "difference": "Diferencia concreta en las condiciones del soporte individual."}
    ]
    selected_check = proposed_check(
        issues=[
            {
                "code": "context_required",
                "description": "Conservar el contexto de S1.",
                "paragraph_index": 0,
            }
        ]
    )
    source_finding = finding()
    original_quote = source_finding["supports"][0]["quote"]
    worker, _ = engine(selected_plan, selected_draft, selected_check)
    plan = worker.plan(inquiry(), source_finding)
    draft = worker.write(inquiry(), source_finding, plan)
    checks = worker.check(inquiry(), source_finding, plan, draft)
    label = "«Oficio 0123 de 2024» (página 1, líneas 1–2)"
    assert label in plan["objective"]
    assert label in plan["points"][0]["description"]
    assert label in draft["paragraphs"][0]["text"]
    assert label in draft["pending"][-1]["description"]
    assert label in checks["issues"][0]["description"]
    assert "S1" not in json.dumps({"plan": plan, "draft": draft, "checks": checks})
    assert source_finding["supports"][0]["quote"] == original_quote
    assert draft["paragraphs"][0]["cited_chunk_ids"] == [support()["chunk_id"]]


@pytest.mark.parametrize("stage", ["objective", "point", "paragraph", "pending", "issue"])
def test_unknown_alias_in_any_model_prose_is_rejected(stage):
    selected_plan = proposed_plan()
    selected_draft = proposed_draft()
    selected_check = proposed_check()
    if stage == "objective":
        selected_plan["objective"] = "Explicar S9."
    elif stage == "point":
        selected_plan["points"][0]["description"] = "Explicar S9."
    elif stage == "paragraph":
        selected_draft["paragraphs"][0]["text"] = "Según S9, la plaza se aprobó."
    elif stage == "pending":
        selected_draft["pending"] = [{"kind": "clarification", "description": "Cotejar S9."}]
    else:
        selected_check["issues"] = [
            {"code": "context", "description": "Revisar S9.", "paragraph_index": None}
        ]
    worker, _ = engine(selected_plan, selected_draft, selected_check)
    with pytest.raises(DomainError, match="alias de fuente desconocido"):
        plan = worker.plan(inquiry(), finding())
        draft = worker.write(inquiry(), finding(), plan)
        worker.check(inquiry(), finding(), plan, draft)


def test_alias_in_paragraph_prose_must_also_be_in_that_paragraph_citations():
    source_finding = finding(
        supports=[support(), support(chunk_id="other:1", source_id="other")]
    )
    worker, _ = engine(
        proposed_plan(),
        proposed_draft(text="Según S2, el comité informó la aprobación en 2024.", ids=["S1"]),
    )
    plan = worker.plan(inquiry(), source_finding)
    with pytest.raises(DomainError, match="no incluyó entre sus citas"):
        worker.write(inquiry(), source_finding, plan)


@pytest.mark.parametrize(
    "title,filename",
    [
        ("Oficio 00888-2026_Respuesta", "oficio.pdf"),
        ("Respuesta del comité", "Oficio_00888-2026_Respuesta.pdf"),
    ],
)
def test_year_adjacent_to_underscore_in_source_metadata_is_supported(title, filename):
    _, _, checks, _ = run(
        text="Según el oficio 00888 de 2026, el comité informó la aprobación de la plaza.",
        source=support(title=title, filename=filename, quote="El comité informó la aprobación."),
    )
    assert checks["status"] == "passed"
    assert all(
        item["passed"] for item in checks["local_checks"] if item["code"] == "period_grounded"
    )


def test_year_like_digits_inside_long_identifier_do_not_support_an_invented_year():
    _, _, checks, _ = run(
        text="Según el oficio, el comité aprobó la plaza en 2026.",
        source=support(
            title="Radicado 12026001",
            filename="radicado12026001.pdf",
            quote="El comité aprobó la plaza de prácticas.",
        ),
    )
    assert checks["status"] == "needs_changes"
    assert "period_grounded" in {issue["code"] for issue in checks["issues"]}


def test_checker_receives_python_reference_labels_for_materialized_plan_and_draft():
    selected_plan = proposed_plan()
    selected_plan["points"][0]["description"] = "Explicar qué respondió S1."
    worker, calls = engine(
        selected_plan,
        proposed_draft(text="Según S1, el comité informó la aprobación en 2024."),
        proposed_check(),
    )
    plan = worker.plan(inquiry(), finding())
    draft = worker.write(inquiry(), finding(), plan)
    checks = worker.check(inquiry(), finding(), plan, draft)
    context = json.loads(calls[2]["input"])
    label = "«Oficio 0123 de 2024» (página 1, líneas 1–2)"
    assert context["local_reference_labels"] == [{"alias": "S1", "label": label}]
    assert label in context["plan"]["points"][0]["description"]
    assert label in context["draft"]["paragraphs"][0]["text"]
    assert context["finding"]["supports"][0]["quote"] == support()["quote"]
    assert checks["status"] == "passed"


@pytest.mark.parametrize("verification", ["reported_by_user", "documented"])
def test_verified_file_does_not_clear_authorship_issue_in_forwarded_text(verification):
    attachment = support(
        category="historical_attachment",
        role="historical_evidence",
        title="Correo reenviado sobre la plaza de prácticas",
        quote=(
            "Mensaje reenviado. Texto aportado: considero que la decisión carece de sustento. "
            "Solicito revisar los documentos."
        ),
        verification_status=verification,
    )
    _, _, checks, calls = run(
        source=attachment,
        text=(
            "Según el correo reenviado, una revisión realizada en el trámite previo "
            "concluyó que la decisión carece de sustento."
        ),
        check=proposed_check(
            issues=[
                {
                    "code": "unsupported_authorship",
                    "description": (
                        "El pasaje es una afirmación de autoría no identificada. "
                        "Atribuirlo al texto aportado o identificar su autor; "
                        "el correo no acredita una revisión institucional."
                    ),
                    "paragraph_index": 0,
                }
            ]
        ),
    )
    assert checks["status"] == "needs_changes"
    assert "unsupported_authorship" in {issue["code"] for issue in checks["issues"]}
    for call in calls:
        provided = json.loads(call["input"])["finding"]["supports"][0]
        assert provided["category"] == "historical_attachment"
        assert provided["role"] == "historical_evidence"
        assert provided["quote"] == attachment["quote"]
        assert provided["verification_status"] == verification
