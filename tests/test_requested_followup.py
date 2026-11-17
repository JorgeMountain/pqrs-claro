"""Requested future tasks preserve information-only answers and source scope."""

from copy import deepcopy

import pytest

from pqrs_claro.request_requirements import build_requirements
from pqrs_claro.requested_followup import requested_followups


def fixture(text=None, claim=None, quote=None):
    text = text or (
        "Expliquen qué decisión queda por comprobar, dónde se publicará y cuándo."
    )
    request = {"id": "P-NUEVA", "case_id": "nuevo-expediente", "description": text,
               "allowed_collection_ids": ["avisos-ficticios"]}
    request["request_requirements"] = build_requirements(request)
    quote = quote or (
        "La decisión final sobre la apertura del observatorio se publicará en el portal "
        "el viernes. El anuncio preventivo no confirma la apertura."
    )
    source = {"source_id": "aviso-ficticio-v1", "chunk_id": "aviso-ficticio:v1:p1",
              "document_id": "aviso-ficticio", "version": 1, "sha256": "hash-v1",
              "quote": quote, "collection_id": "avisos-ficticios",
              "category": "historical_attachment", "role": "historical_evidence"}
    coverage = {"claim": claim or quote, "use": "attributed_content", "citations": [
        {"chunk_id": source["chunk_id"], "quote": quote}]}
    finding = {"supports": [source], "sufficiency": {"coverage": [coverage],
        "requirement_checks": [
            {"requirement_id": r["id"], "status": "supported", "coverage_indexes": [0]}
            for r in request["request_requirements"]]}}
    return request, finding


def test_requested_pending_decision_creates_one_nonblocking_literal_followup():
    args = fixture()
    before = deepcopy(args)
    tasks = requested_followups(*args)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["reason_code"] == "requested_followup"
    assert task["stage"] == "fulfillment" and task["blocks_approval"] is False
    assert task["request_quote"] in args[0]["description"]
    assert task["affected_claim"] == args[1]["sufficiency"]["coverage"][0]["claim"]
    assert task["linked_chunk_ids"] == [args[1]["supports"][0]["chunk_id"]]
    assert task["replaces_generic_supervision"] is False
    assert args == before


@pytest.mark.parametrize("text", [
    "¿Cuándo se publicará la decisión?",
    "Explique el aviso preventivo y el canal en que se publicará la decisión.",
    "Explique en general qué decisión queda por comprobar en este procedimiento.",
    "Explique quién debe verificar cuando se publique la decisión.",
    "Describa cómo debe actuar quien verifique cuando se publique la decisión.",
    "No solicito seguimiento. Expliquen qué decisión queda por comprobar.",
    "No verifiquen cuando se publique; solo quiero conocer el aviso.",
    "Solicito información sobre cómo se debe verificar cuando llegue el aviso.",
    "El aviso dice: verifiquen cuando se publique la decisión.",
    "El reglamento indica que se compruebe cuando se publique el resultado.",
    "No solicito verificar el resultado cuando esté disponible.",
])
def test_information_third_party_or_exclusion_does_not_create_a_task(text):
    assert requested_followups(*fixture(text)) == []


def test_direct_followup_can_replace_only_single_generated_supervision():
    tasks = requested_followups(*fixture("Verifiquen cuando se publique la decisión final."))
    assert len(tasks) == 1 and tasks[0]["replaces_generic_supervision"]
    tasks = requested_followups(*fixture(
        "Verifiquen cuando se publique la decisión final. Además vigilen el archivo original."
    ))
    assert len(tasks) == 1 and not tasks[0]["replaces_generic_supervision"]


def test_excluding_a_definitive_claim_does_not_negate_requested_followup():
    tasks = requested_followups(*fixture(
        "Expliquen qué decisión queda por comprobar y dónde se publicará. "
        "No den por definitivo el aviso preventivo."
    ))
    assert len(tasks) == 1


@pytest.mark.parametrize("change", [
    "permission", "version", "literal", "other_requirement", "no_mapping", "rule", "unreadable",
])
def test_task_needs_its_own_current_authorized_literal_coverage(change):
    request, finding = fixture()
    source = finding["supports"][0]
    if change == "permission":
        request["allowed_collection_ids"] = []
    elif change == "version":
        source["is_latest"] = False
    elif change == "literal":
        source["quote"] = "Se corrigió la fecha y el objeto del aviso."
    elif change == "other_requirement":
        finding["sufficiency"]["requirement_checks"] = [
            {"requirement_id": "OTRA", "coverage_indexes": [0]}]
    elif change == "no_mapping":
        finding["sufficiency"]["requirement_checks"] = []
    elif change == "rule":
        finding["sufficiency"]["coverage"][0]["use"] = "rule"
    elif change == "unreadable":
        source["extraction_status"] = "pending"
    assert requested_followups(request, finding) == []


@pytest.mark.parametrize("quote", [
    "La decisión ya se publicó en el portal el viernes.",
    "Se anunciaba que se publicará el viernes; finalmente se publicó el jueves.",
    "La decisión no se publicará por ese canal.",
    "La revisión concluyó y la decisión está resuelta.",
])
def test_completed_or_negated_publication_does_not_create_future_task(quote):
    assert requested_followups(*fixture(quote=quote)) == []


def test_summary_cannot_turn_present_source_into_a_future_task():
    args = fixture(claim="La decisión se publicará el viernes.",
                   quote="La oficina conserva el aviso preventivo de apertura.")
    assert requested_followups(*args) == []


def test_exact_existing_control_is_reused_even_when_resolved_and_is_not_mutated():
    request, finding = fixture()
    original = requested_followups(request, finding)[0]
    finding["checks"] = [{**original, "resolution": {"status": "resolved"}}]
    before = deepcopy(finding)
    assert requested_followups(request, finding) == []
    assert finding == before


def test_different_followup_or_source_version_never_reuses_previous_resolution():
    request, finding = fixture()
    original = requested_followups(request, finding)[0]
    finding["checks"] = [{**original, "resolution": {"status": "resolved"}}]
    finding["supports"][0]["version"] = 2
    finding["supports"][0]["sha256"] = "hash-v2"
    assert len(requested_followups(request, finding)) == 1
    finding["checks"][0]["affected_claim"] = "Otra decisión con un plazo distinto."
    finding["checks"][0]["request_quote"] = "Otro seguimiento."
    finding["checks"][0]["source_versions"] = []
    assert len(requested_followups(request, finding)) == 1


def test_unknown_or_repeated_mapping_cannot_create_task():
    args = fixture()
    args[1]["sufficiency"]["requirement_checks"].append(
        deepcopy(args[1]["sufficiency"]["requirement_checks"][0]))
    assert requested_followups(*args) == []


@pytest.mark.parametrize("text", [
    "Solicito verificar la decisión final cuando se publique.",
    "Les pido hacer seguimiento a la inspección y comprobar el resultado cuando esté disponible.",
])
def test_governed_infinitive_is_an_explicit_future_mandate(text):
    tasks = requested_followups(*fixture(text))
    assert len(tasks) == 1 and tasks[0]["replaces_generic_supervision"]


def test_governed_followup_keeps_an_independent_supervision():
    tasks = requested_followups(*fixture(
        "Solicito verificar la decisión cuando se publique. Les pido vigilar el archivo original."
    ))
    assert len(tasks) == 1 and not tasks[0]["replaces_generic_supervision"]


@pytest.mark.parametrize("claim,quote", [
    ("El resultado se registraría el viernes.", "El resultado se registrará el viernes."),
    ("El resultado estará disponible el viernes.", "El resultado estará disponible el viernes."),
])
def test_registration_and_availability_are_observable_future_events(claim, quote):
    assert len(requested_followups(*fixture(claim=claim, quote=quote))) == 1


@pytest.mark.parametrize("quote", [
    "El resultado se registrará el viernes; ya se registró el jueves.",
    "El resultado estará disponible el viernes; ya está disponible en el portal.",
    "El resultado no estará disponible el viernes.",
])
def test_registration_or_availability_already_resolved_or_negated(quote):
    assert requested_followups(*fixture(quote=quote)) == []


def test_include_existing_preserves_closed_control_and_its_key():
    request, finding = fixture("Verifiquen cuando se publique la decisión final.")
    original = requested_followups(request, finding)[0]
    original.update(check_key="human-control",
                    resolution={"status": "resolved", "actor": "reviewer"})
    finding["checks"] = [original]
    before = deepcopy(finding)
    kept = requested_followups(request, finding, include_existing=True)
    assert len(kept) == 1 and kept[0] == original
    assert kept[0] is not original and finding == before


def mapped_action_fixture():
    request, finding = fixture("Solicito verificar la decisión final cuando se publique.")
    task = requested_followups(request, finding)[0]
    action = {**task, "reason_code": "fact_confirmation", "check_key": "existing-temporal",
              "description": "Comprobar el resultado final cuando esté disponible.",
              "affected_claim": "La comprobación posterior del resultado solicitado."}
    for key in ("request_quote", "requirement_ids", "followup_passages", "followup_claims"):
        action.pop(key)
    finding["actions"] = [action]
    finding["sufficiency"]["requirement_checks"][0]["missing_indexes"] = [0]
    finding["sufficiency"]["evaluated_gaps"] = [{
        "description": action["description"], "affected_claim": action["affected_claim"],
        "stage": "fulfillment", "source_chunk_ids": task["linked_chunk_ids"],
    }]
    return request, finding


def test_exact_requirement_gap_mapping_reuses_model_action_with_other_reason():
    request, finding = mapped_action_fixture()
    finding["actions"][0]["resolution"] = {"status": "resolved"}
    before = deepcopy(finding)
    assert requested_followups(request, finding) == []
    kept = requested_followups(request, finding, include_existing=True)
    assert len(kept) == 1 and kept[0]["check_key"] == "existing-temporal"
    assert kept[0]["resolution"] == {"status": "resolved"}
    assert kept[0]["replaces_generic_supervision"] is True
    assert finding == before


@pytest.mark.parametrize("change", ["gap", "link", "claim", "version", "delivery", "mapping"])
def test_different_existing_actions_are_not_suppressed(change):
    request, finding = mapped_action_fixture()
    action = finding["actions"][0]
    if change == "gap":
        action["description"] = "Otra comprobación cuando se publique el resultado."
    elif change == "link":
        action["linked_chunk_ids"] = ["another-current-passage"]
    elif change == "claim":
        action["affected_claim"] = "Otra decisión independiente."
    elif change == "version":
        action["source_versions"][0]["version"] = 0
    elif change == "delivery":
        gap = finding["sufficiency"]["evaluated_gaps"][0]
        action["description"] = gap["description"] = "Entregar la copia cuando esté disponible."
    elif change == "mapping":
        finding["sufficiency"]["requirement_checks"][0]["missing_indexes"] = []
    tasks = requested_followups(request, finding, include_existing=True)
    assert len(tasks) == 1 and tasks[0]["reason_code"] == "requested_followup"
    assert finding["actions"][0] is action


def test_one_mandate_and_identical_literal_passage_preserve_all_coverage_claims_once():
    request, finding = fixture()
    coverage = finding["sufficiency"]["coverage"]
    coverage.append({**deepcopy(coverage[0]),
                     "claim": "La decisión final se publicará el viernes."})
    finding["sufficiency"]["requirement_checks"][0]["coverage_indexes"] = [0, 1]
    tasks = requested_followups(request, finding)
    assert len(tasks) == 1 and tasks[0]["coverage_indexes"] == [0, 1]
    assert tasks[0]["followup_claims"] == [c["claim"] for c in coverage]
    assert all(c["claim"] in tasks[0]["description"] for c in coverage)


def test_different_literal_passage_cannot_reuse_closed_followup_or_merge_claims():
    request, finding = fixture()
    original = requested_followups(request, finding)[0]
    original["resolution"] = {"status": "resolved"}
    finding["checks"] = [original]
    other_quote = "La decisión sobre otra jornada se publicará el martes."
    finding["supports"][0]["quote"] += " " + other_quote
    row = finding["sufficiency"]["coverage"][0]
    row["citations"][0]["quote"] = other_quote
    tasks = requested_followups(request, finding)
    assert len(tasks) == 1 and tasks[0]["followup_passages"][0]["quote"] == other_quote
