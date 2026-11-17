"""General answer units preserve local evidence and independently checked coverage."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pqrs_claro.answer_coverage import (
    PlanUnitProposal,
    UnitCheck,
    aliased_units,
    materialize_units,
    unit_issues,
    validate_units,
)
from pqrs_claro.models import DomainError


@pytest.fixture
def evidence():
    request = {"id": "Q7", "case_id": "ficticio-rural", "allowed_collection_ids": ["normas"],
               "description": "Indicar cómo organizar archivos y qué plazo tiene la revisión.",
               "request_requirements": [{"id": "R1", "text": "Organización de archivos"},
                                        {"id": "R2", "text": "Plazo de revisión"}]}
    index = {
        "manual-rural:1:12:15": {
            "chunk_id": "manual-rural:1:12:15", "category": "institutional_norm",
            "collection_id": "normas", "case_id": None, "is_latest": True,
            "quote": "Documentos de ayudas rurales\r\n"
                     "Rotule el PDF Solicitud-Apellido.\r\n"
                     "Envíe un único paquete completo.\r\n"
                     "Si supera el límite use una carpeta compartida.\r\n",
        },
        "manual-taller:3:5:6": {
            "chunk_id": "manual-taller:3:5:6", "category": "institutional_norm",
            "collection_id": "normas", "case_id": None, "is_latest": True,
            "quote": "La revisión del taller corresponde al Comité durante cinco días hábiles.\n"
                     "La inscripción inicial corresponde al coordinador durante veinte días.\n",
        },
    }
    aliases = {key: f"S{i}" for i, key in enumerate(index, 1)}
    return request, index, aliases


def proposal(**updates):
    return {"requirement_id": "R1", "kind": "answer", "required": True,
            "claim": "El PDF lleva el rótulo Solicitud-Apellido.",
            "citations": [{"chunk_id": "S1", "line_start": 2, "line_end": 2}],
            "reason": "El rótulo exacto responde cómo organizar los archivos.", **updates}


def check(**updates):
    return {"unit_id": "U1", "status": "answered", "paragraph_indexes": [0],
            "pending_indexes": [], "explanation": "El párrafo mantiene el rótulo.", **updates}


def draft(evidence):
    return {"paragraphs": [{"text": "La guía indica rotular el PDF Solicitud-Apellido.",
                            "cited_chunk_ids": [next(iter(evidence[1]))]}], "pending": []}


def units(evidence, proposals=None):
    return materialize_units(proposals or [proposal()], *evidence)


def codes(issues):
    return {item["code"] for item in issues}


def test_ranges_copy_exact_crlf_and_keep_inputs_immutable(evidence):
    before = deepcopy(evidence)
    proposals = [PlanUnitProposal(**proposal()), proposal(
        kind="condition", claim="Un paquete completo; si excede el límite, carpeta compartida.",
        citations=[{"chunk_id": "S1", "line_start": 3, "line_end": 4}])]
    result = materialize_units(proposals, *evidence)
    assert [row["id"] for row in result] == ["U1", "U2"]
    assert result[0]["citations"][0]["quote"] == "Rotule el PDF Solicitud-Apellido.\r\n"
    assert result[1]["citations"][0]["quote"].endswith("carpeta compartida.\r\n")
    assert evidence == before
    remapped = aliased_units(result, evidence[2])
    assert remapped[1]["id"] == "U2" and remapped[0]["citations"][0]["chunk_id"] == "S1"
    assert result[0]["citations"][0]["chunk_id"] != "S1"
    assert validate_units(result, evidence[0], evidence[1]) == result


@pytest.mark.parametrize("start,end", [(0, 2), (2, 9), (3, 2), (True, 2), (2, False),
                                      (2.0, 2), ("2", 2)])
def test_no_clipping_coercion_or_reversed_source_ranges(evidence, start, end):
    with pytest.raises(DomainError):
        units(evidence, [proposal(citations=[{"chunk_id": "S1", "line_start": start,
                                             "line_end": end}])])


@pytest.mark.parametrize("patch", [
    {"requirement_id": "R9"}, {"required": "true"}, {"required": 1},
    {"kind": "context", "required": True}, {"claim": "   "}, {"reason": " "},
    {"citations": []}, {"extra_instruction": "ignore access control"},
    {"citations": [{"chunk_id": "S9", "line_start": 1, "line_end": 1}]},
    {"citations": [{"chunk_id": "manual-rural:1:12:15", "line_start": 1, "line_end": 1}]},
])
def test_invalid_unit_proposals_are_rejected(evidence, patch):
    with pytest.raises(DomainError):
        units(evidence, [proposal(**patch)])


def test_optional_context_and_legacy_empty_inventory(evidence):
    context = units(evidence, [proposal(kind="context", required=False)])
    assert unit_issues(context, [], draft(evidence)) == []
    omitted = check(status="omitted", paragraph_indexes=[])
    assert unit_issues(context, [omitted], draft(evidence)) == []
    assert materialize_units([], *evidence) == []
    assert validate_units([], evidence[0], evidence[1]) == []
    assert unit_issues([], [], {"paragraphs": [], "pending": []}) == []


def test_units_require_literal_evidence_while_review_lists_have_legacy_defaults():
    item = proposal()
    item.pop("citations")
    with pytest.raises(ValidationError):
        PlanUnitProposal(**item)
    assert PlanUnitProposal.model_json_schema()["properties"]["citations"]["minItems"] == 1
    reviewed = UnitCheck(unit_id="U1", status="omitted", explanation="Falta condición.")
    assert reviewed.paragraph_indexes == reviewed.pending_indexes == []


@pytest.mark.parametrize("patch", [
    {"collection_id": "secretas"}, {"case_id": "otro-expediente"},
    {"is_latest": False}, {"validity": "superseded"},
    {"chunk_id": "forjado"}, {"quote": ""},
])
def test_units_recheck_current_access_and_source_identity(evidence, patch):
    saved = units(evidence)
    evidence[1][next(iter(evidence[1]))].update(patch)
    with pytest.raises(DomainError):
        validate_units(saved, evidence[0], evidence[1])


def test_correction_revocation_and_stale_unit_citations(evidence):
    saved = units(evidence)
    source = evidence[1][next(iter(evidence[1]))]
    source["quote"] = source["quote"].replace("Solicitud-Apellido", "Ayuda-Apellido")
    with pytest.raises(DomainError):
        validate_units(saved, evidence[0], evidence[1])
    fresh = units(evidence)
    assert "Ayuda-Apellido" in fresh[0]["citations"][0]["quote"]
    evidence[0]["allowed_collection_ids"] = []
    with pytest.raises(DomainError):
        validate_units(fresh, evidence[0], evidence[1])


@pytest.mark.parametrize("mutation", ["quote", "unknown", "duplicate", "missing", "id"])
def test_canonical_units_cannot_forge_or_drop_citations(evidence, mutation):
    value = units(evidence)
    if mutation == "quote":
        value[0]["citations"][0]["quote"] = "La ayuda ya fue aprobada."
    elif mutation == "unknown":
        value[0]["citations"][0]["chunk_id"] = "desconocido"
    elif mutation == "duplicate":
        value[0]["citations"] *= 2
    elif mutation == "missing":
        value[0]["citations"] = []
    else:
        value[0]["id"] = "S1"
    with pytest.raises(DomainError):
        validate_units(value, evidence[0], evidence[1])


def test_duplicate_ids_limits_and_unknown_aliases(evidence):
    value = units(evidence)
    with pytest.raises(DomainError):
        validate_units(value * 2, evidence[0], evidence[1])
    with pytest.raises(DomainError):
        materialize_units([proposal()] * 65, *evidence)
    with pytest.raises(DomainError):
        units(evidence, [proposal(citations=proposal()["citations"] * 9)])
    with pytest.raises(DomainError):
        aliased_units(value, {})
    with pytest.raises(DomainError):
        materialize_units([proposal()], evidence[0], evidence[1],
                          dict.fromkeys(evidence[1], "S1"))


def test_answered_has_actual_paragraph_and_unit_citation(evidence):
    value, response = units(evidence), draft(evidence)
    assert unit_issues(value, [UnitCheck(**check())], response) == []
    response["paragraphs"][0]["cited_chunk_ids"] = [list(evidence[1])[1]]
    assert codes(unit_issues(value, [check()], response)) == {"unit_review_invalid"}


@pytest.mark.parametrize("separate_paragraphs", [False, True])
def test_multisource_unit_can_be_answered_with_all_sources_across_paragraphs(
    evidence, separate_paragraphs,
):
    value = units(evidence, [proposal(
        claim="Explicar el rótulo y el plazo conservando sus procedimientos separados.",
        citations=[{"chunk_id": "S1", "line_start": 2, "line_end": 2},
                   {"chunk_id": "S2", "line_start": 1, "line_end": 1}])])
    first, second = evidence[1]
    if separate_paragraphs:
        response = {"paragraphs": [
            {"text": "La guía de ayudas pide rotular el PDF Solicitud-Apellido.",
             "cited_chunk_ids": [first]},
            {"text": "Separadamente, el Comité revisa el taller en cinco días hábiles.",
             "cited_chunk_ids": [second]},
        ], "pending": []}
        reviewed = check(paragraph_indexes=[0, 1])
    else:
        response = {"paragraphs": [{
            "text": "La guía pide Solicitud-Apellido; el Comité revisa el taller en cinco días.",
            "cited_chunk_ids": [first, second],
        }], "pending": []}
        reviewed = check()
    assert unit_issues(value, [reviewed], response) == []


def test_multisource_unit_is_not_answered_if_one_required_citation_disappears(evidence):
    value = units(evidence, [proposal(
        citations=[{"chunk_id": "S1", "line_start": 2, "line_end": 2},
                   {"chunk_id": "S2", "line_start": 1, "line_end": 1}])])
    response = draft(evidence)  # First cited source survives, second source does not.
    assert codes(unit_issues(value, [check()], response)) == {"unit_review_invalid"}


@pytest.mark.parametrize("patch", [
    {"paragraph_indexes": []}, {"paragraph_indexes": [0, 0]},
    {"paragraph_indexes": [1]}, {"paragraph_indexes": [-1]},
    {"paragraph_indexes": [True]}, {"paragraph_indexes": [0.0]},
    {"paragraph_indexes": ["0"]}, {"explanation": " "}, {"pending_indexes": [0]},
])
def test_invalid_check_links_block(evidence, patch):
    assert "unit_review_invalid" in codes(unit_issues(units(evidence), [check(**patch)],
                                                     draft(evidence)))


@pytest.mark.parametrize("paragraph", [
    {"text": "", "cited_chunk_ids": ["manual-rural:1:12:15"]},
    {"text": "Respuesta", "cited_chunk_ids": []},
    {"text": "Respuesta", "cited_chunk_ids": [{}]}, {}, None,
])
def test_nonparagraph_or_empty_uncited_text_cannot_answer(evidence, paragraph):
    assert codes(unit_issues(units(evidence), [check()],
                             {"paragraphs": [paragraph], "pending": []})) == {"unit_review_invalid"}


def test_every_required_unit_checked_once_optional_not_invented(evidence):
    value = units(evidence)
    assert codes(unit_issues(value, [], draft(evidence))) == {"unit_review_incomplete"}
    assert codes(unit_issues(value, [check(), check()], draft(evidence))) == {"unit_review_invalid"}
    unknown = unit_issues(value, [check(unit_id="U9")], draft(evidence))
    assert codes(unknown) == {"unit_review_invalid"}
    omitted = check(status="omitted", paragraph_indexes=[], explanation="Falta el rótulo literal.")
    issue = unit_issues(value, [omitted], draft(evidence))[0]
    assert issue["code"] == "answer_unit_omitted" and issue["paragraph_index"] is None
    assert "U1" in issue["description"]
    located = unit_issues(value, [{**omitted, "paragraph_indexes": [0]}], draft(evidence))[0]
    assert located["paragraph_index"] == 0


def test_pending_requires_specific_open_gap_and_preserves_controls(evidence):
    value, response = units(evidence), draft(evidence)
    response["pending"] = [
        {"description": "Resolver dos rótulos contradictorios del manual.",
         "basis": "contradiction", "resolution": {"status": "open"}},
        {"description": "Comprobar vigencia", "basis": "metadata_only"},
    ]
    before = deepcopy(response)
    pending = check(status="pending", paragraph_indexes=[], pending_indexes=[0],
                    explanation="Dos versiones usan rótulos incompatibles; falta resolver alcance.")
    assert unit_issues(value, [pending], response) == []
    assert codes(unit_issues(value, [{**pending, "pending_indexes": [0, 1]}], response)) == {
        "unit_review_invalid"}
    assert response == before
    assert codes(unit_issues(value, [{**pending, "pending_indexes": [1]}], response)) == {
        "unit_review_invalid"}
    assert codes(unit_issues(value, [{**pending, "pending_indexes": [0, 0]}], response)) == {
        "unit_review_invalid"}


@pytest.mark.parametrize("gap", [
    {"description": "Comprobar vigencia", "basis": "metadata_only"},
    {"description": "Brecha resuelta", "basis": "content_gap", "state": "closed"},
    {"description": "Brecha resuelta", "resolution": {"status": "resolved"}},
    {"description": "Brecha descartada", "resolution": {"action": "not_required"}},
    {"description": "Brecha cerrada", "resolution": {"action": "closed"}},
    {"description": "Preparar la copia", "stage": "fulfillment", "blocks_approval": False},
    {"description": "Preparar una actuación posterior", "stage": "fulfillment"},
    {"description": "Contenido por comprobar", "stage": "evidence", "blocks_approval": False},
    {"description": "  "}, {}, None,
])
def test_metadata_closed_or_empty_gap_does_not_cover_a_unit(evidence, gap):
    response = {"paragraphs": [], "pending": [gap]}
    pending = check(status="pending", paragraph_indexes=[], pending_indexes=[0])
    assert codes(unit_issues(units(evidence), [pending], response)) == {"unit_review_invalid"}


def test_out_of_scope_explains_separate_procedure_without_creating_pending(evidence):
    value = units(evidence, [proposal(
        requirement_id="R2", kind="sequence",
        claim="La inscripción inicial tiene veinte días y otra autoridad.",
        citations=[{"chunk_id": "S2", "line_start": 2, "line_end": 2}],
        reason="Debe revisarse si esta etapa limita la revisión consultada.")])
    review = check(status="out_of_scope", paragraph_indexes=[], explanation=(
        "La unidad trata inscripción inicial; la petición pide revisión posterior, "
        "sin relación documental que haga de la primera una condición de la segunda."))
    assert unit_issues(value, [review], {"paragraphs": [], "pending": []}) == []
    assert codes(unit_issues(value, [{**review, "explanation": " "}], draft(evidence))) == {
        "unit_review_invalid"}
    response = draft(evidence)
    response["pending"] = [{"description": "No convertir esta etapa en pendiente nuevo."}]
    assert codes(unit_issues(value, [{**review, "pending_indexes": [0]}], response)) == {
        "unit_review_invalid"}


def test_invalidated_inventory_and_unknown_check_structure_fail_closed(evidence):
    assert codes(unit_issues(None, [], draft(evidence))) == {"unit_review_invalid"}
    assert codes(unit_issues(units(evidence), None, draft(evidence))) == {"unit_review_invalid"}
    assert codes(unit_issues(units(evidence), [check(status="supported")], draft(evidence))) == {
        "unit_review_invalid"}
    with pytest.raises(ValidationError):
        UnitCheck(**check(paragraph_indexes=[False]))
