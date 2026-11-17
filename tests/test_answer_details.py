"""Literal named identities and semantically reviewed alternatives, without providers."""

import re
from copy import deepcopy

import pytest

from pqrs_claro.answer_coverage import (
    DETAIL_POLICY_HASH,
    DetailCheck,
    DetailedPlanUnitProposal,
    aliased_units,
    detail_issues,
    has_current_details,
    materialize_detailed_units,
    materialize_units,
    numbered_detail_lines,
    numbered_detail_paragraphs,
    unit_issues,
    validate_units,
)
from pqrs_claro.models import DomainError

A = "Mesa de Diseño Rural"
B = "Comisión de Acceso Remoto"
KEY = "norma-ficticia:2:1:4"
TEXT = (
    "Reglamento ficticio de proyectos\r\n"
    f"La {A} o la {B} expide el informe, según el caso.\r\n"
    "La Dirección de Proyectos comunica el resultado en el tablero.\r\n"
    "La petición puede presentarse por escrito o mediante comparecencia oral.\r\n"
)


def word_range(text, quote):
    start = text.index(quote)
    end = start + len(quote)
    words = list(re.finditer(r"\S+", text))
    selected = [i + 1 for i, word in enumerate(words) if word.start() < end and word.end() > start]
    return {"word_start": selected[0], "word_end": selected[-1]}


def fixture():
    request = {
        "id": "P1",
        "allowed_collection_ids": ["normas"],
        "request_requirements": [{"id": "R1", "text": "Quién expide el informe."}],
    }
    index = {
        KEY: {
            "chunk_id": KEY,
            "quote": TEXT,
            "category": "institutional_norm",
            "collection_id": "normas",
            "case_id": None,
            "is_latest": True,
        }
    }
    aliases = {KEY: "S1"}
    citation = {"chunk_id": "S1", "line_start": 2, "line_end": 2}
    details = [
        {
            "kind": "authority",
            "citation": citation,
            "members": [word_range(TEXT, name)],
            "reason": "Identifica el órgano competente.",
        }
        for name in (A, B)
    ]
    details.append(
        {
            "kind": "alternatives",
            "citation": citation,
            "members": [word_range(TEXT, name) for name in (A, B)],
            "reason": "Conserva las autoridades alternativas según el caso.",
        }
    )
    proposal = {
        "requirement_id": "R1",
        "kind": "answer",
        "required": True,
        "claim": "El órgano correspondiente expide el informe.",
        "citations": [citation],
        "reason": "Identifica al emisor.",
        "details": details,
        "no_details_reason": "",
    }
    return request, index, aliases, proposal


def units_and_draft():
    request, index, aliases, proposal = fixture()
    units = materialize_detailed_units([proposal], request, index, aliases)
    draft = {
        "paragraphs": [
            {
                "text": f"El informe lo expide la {A} o la {B}, según corresponda.",
                "cited_chunk_ids": [KEY],
            }
        ],
        "pending": [],
    }
    return units, draft


def checks_for(draft):
    text = draft["paragraphs"][0]["text"]
    evidence = [
        {"paragraph_index": 0, "member_index": i, **word_range(text, name)}
        for i, name in enumerate((A, B), 1)
    ]
    return [
        {
            "detail_id": "U1-K1",
            "status": "answered",
            "evidence": [evidence[0]],
            "pending_indexes": [],
            "explanation": "Nombra la primera autoridad.",
        },
        {
            "detail_id": "U1-K2",
            "status": "answered",
            "evidence": [{**evidence[1], "member_index": 1}],
            "pending_indexes": [],
            "explanation": "Nombra la segunda autoridad.",
        },
        {
            "detail_id": "U1-K3",
            "status": "answered",
            "evidence": evidence,
            "pending_indexes": [],
            "explanation": "Son opciones alternativas según corresponda, no deberes conjuntos.",
        },
    ]


def codes(issues):
    return {issue["code"] for issue in issues}


def test_materializes_details_inside_unit_citations_and_preserves_exact_originals():
    request, index, aliases, proposal = fixture()
    before = deepcopy((request, index, aliases, proposal))
    units = materialize_detailed_units(
        [DetailedPlanUnitProposal(**proposal)], request, index, aliases
    )
    assert has_current_details(units)
    assert units[0]["details_version"] == 1
    assert [d["id"] for d in units[0]["details"]] == ["U1-K1", "U1-K2", "U1-K3"]
    assert units[0]["details"][0]["members"][0] == {"chunk_id": KEY, "quote": A}
    assert units[0]["details"][2]["citation"]["quote"] == TEXT.splitlines(True)[1]
    assert validate_units(units, request, index) == units
    remapped = aliased_units(units, aliases)
    assert remapped[0]["details"][0]["citation"]["chunk_id"] == "S1"
    assert all(m["chunk_id"] == "S1" for d in remapped[0]["details"] for m in d["members"])
    assert units[0]["details"][0]["citation"]["chunk_id"] == KEY
    assert (request, index, aliases, proposal) == before
    assert len(DETAIL_POLICY_HASH) == 64


def test_source_and_answer_word_numbers_share_exact_unicode_crlf_positions():
    lines = numbered_detail_lines(TEXT)
    flat = [pair for _, words in lines for pair in words]
    assert [p[0] for p in flat] == list(range(1, len(TEXT.split()) + 1))
    assert [p[1] for p in flat] == TEXT.split()
    units, draft = units_and_draft()
    numbered = numbered_detail_paragraphs(draft["paragraphs"])
    assert numbered[0]["paragraph_index"] == 0
    assert [w[1] for w in numbered[0]["numbered_words"]] == draft["paragraphs"][0]["text"].split()
    before = deepcopy((units, draft))
    assert detail_issues(units, checks_for(draft), draft) == []
    assert (units, draft) == before


@pytest.mark.parametrize(
    "defect",
    [
        "unknown_source",
        "outside_unit",
        "outside_citation",
        "word_zero",
        "word_large",
        "word_bool",
        "reversed",
        "authority_two",
        "alternative_one",
        "duplicate_member",
        "empty_reason",
        "mixed_no_details",
        "missing_field",
    ],
)
def test_rejects_details_outside_authorized_literal_unit_context(defect):
    request, index, aliases, proposal = fixture()
    detail = proposal["details"][0]
    if defect == "unknown_source":
        detail["citation"] = {"chunk_id": "S9", "line_start": 2, "line_end": 2}
    elif defect == "outside_unit":
        detail["citation"] = {"chunk_id": "S1", "line_start": 3, "line_end": 3}
        detail["members"] = [word_range(TEXT, "Dirección de Proyectos")]
    elif defect == "outside_citation":
        detail["members"] = [word_range(TEXT, "Dirección de Proyectos")]
    elif defect in {"word_zero", "word_large", "word_bool", "reversed"}:
        detail["members"][0]["word_start"] = {
            "word_zero": 0,
            "word_large": 999,
            "word_bool": True,
            "reversed": 30,
        }[defect]
    elif defect == "authority_two":
        detail["members"].append(word_range(TEXT, B))
    elif defect == "alternative_one":
        proposal["details"][2]["members"].pop()
    elif defect == "duplicate_member":
        proposal["details"][2]["members"][1] = deepcopy(proposal["details"][2]["members"][0])
    elif defect == "empty_reason":
        detail["reason"] = " "
    elif defect == "mixed_no_details":
        proposal["no_details_reason"] = "No hay detalles."
    else:
        proposal.pop("details")
    with pytest.raises(DomainError):
        materialize_detailed_units([proposal], request, index, aliases)


@pytest.mark.parametrize(
    "defect",
    [
        "forged_member",
        "forged_member_source",
        "forged_citation",
        "wrong_id",
        "no_version",
        "wrong_version",
        "boolean_version",
    ],
)
def test_saved_detail_contract_cannot_forge_source_or_silently_become_legacy(defect):
    request, index, aliases, proposal = fixture()
    units = materialize_detailed_units([proposal], request, index, aliases)
    if defect == "forged_member":
        units[0]["details"][0]["members"][0]["quote"] = "Una entidad inventada"
    elif defect == "forged_member_source":
        units[0]["details"][0]["members"][0]["chunk_id"] = "other-source"
    elif defect == "forged_citation":
        units[0]["details"][0]["citation"]["quote"] = TEXT.splitlines(True)[2]
    elif defect == "wrong_id":
        units[0]["details"][0]["id"] = "U2-K1"
    elif defect == "no_version":
        units[0].pop("details_version")
    elif defect == "boolean_version":
        units[0]["details_version"] = True
    else:
        units[0]["details_version"] = 2
    assert has_current_details(units) is False
    with pytest.raises(DomainError):
        validate_units(units, request, index)


def test_legacy_units_remain_readable_but_cannot_approve_new_detail_review():
    request, index, aliases, proposal = fixture()
    core = {k: v for k, v in proposal.items() if k not in {"details", "no_details_reason"}}
    legacy = materialize_units([core], request, index, aliases)
    assert validate_units(legacy, request, index) == legacy
    assert "details_version" not in legacy[0] and not has_current_details(legacy)
    assert codes(detail_issues(legacy, [], {"paragraphs": [], "pending": []})) == {
        "detail_inventory_stale"
    }
    assert detail_issues(legacy, [], {"paragraphs": [], "pending": []}, require_current=False) == []


def test_explicit_no_details_reason_is_versioned_without_inventing_obligations():
    request, index, aliases, proposal = fixture()
    proposal.update(
        details=[],
        no_details_reason="Esta unidad no contiene identidades ni alternativas pertinentes.",
    )
    units = materialize_detailed_units([proposal], request, index, aliases)
    assert has_current_details(units)
    assert detail_issues(units, [], {"paragraphs": [], "pending": []}) == []
    proposal["no_details_reason"] = " "
    with pytest.raises(DomainError):
        materialize_detailed_units([proposal], request, index, aliases)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "unknown",
        "missing_member",
        "unknown_member",
        "outside_paragraph",
        "outside_words",
        "wrong_citation",
        "blank_explanation",
    ],
)
def test_current_inventory_requires_complete_numeric_answer_evidence(defect):
    units, draft = units_and_draft()
    checks = checks_for(draft)
    if defect == "missing":
        checks.pop()
    elif defect == "duplicate":
        checks.append(deepcopy(checks[0]))
    elif defect == "unknown":
        checks[0]["detail_id"] = "U9-K1"
    elif defect == "missing_member":
        checks[2]["evidence"].pop()
    elif defect == "unknown_member":
        checks[2]["evidence"][0]["member_index"] = 3
    elif defect == "outside_paragraph":
        checks[0]["evidence"][0]["paragraph_index"] = 99
    elif defect == "outside_words":
        checks[0]["evidence"][0]["word_end"] = 999
    elif defect == "wrong_citation":
        draft["paragraphs"][0]["cited_chunk_ids"] = ["other"]
    else:
        checks[0]["explanation"] = " "
    assert codes(detail_issues(units, checks, draft)) & {
        "detail_review_invalid",
        "detail_review_incomplete",
    }


def test_unit_answered_and_shared_source_cannot_hide_named_identity_omission():
    units, draft = units_and_draft()
    draft["paragraphs"][0]["text"] = "El órgano correspondiente expide el informe."
    proof = {"paragraph_index": 0, "member_index": 1, "word_start": 1, "word_end": 6}
    checks = [
        {
            "detail_id": detail["id"],
            "status": "answered",
            "evidence": [
                {**proof, "member_index": i} for i in range(1, len(detail["members"]) + 1)
            ],
            "pending_indexes": [],
            "explanation": "El doble declara cobertura.",
        }
        for detail in units[0]["details"]
    ]
    unit_check = {
        "unit_id": "U1",
        "status": "answered",
        "paragraph_indexes": [0],
        "pending_indexes": [],
        "explanation": "El claim genérico figura y su fuente está citada.",
    }
    assert unit_issues(units, [unit_check], draft) == []
    issues = detail_issues(units, checks, draft)
    assert [i["code"] for i in issues] == ["answer_detail_omitted", "answer_detail_omitted"]
    assert all(i["paragraph_index"] == 0 for i in issues)
    assert A in issues[0]["description"] and B in issues[1]["description"]
    assert draft["pending"] == []


def test_alternative_options_accept_equivalent_paraphrases_with_each_member_evidenced():
    request, index, aliases, proposal = fixture()
    citation = {"chunk_id": "S1", "line_start": 4, "line_end": 4}
    proposal.update(
        citations=[citation],
        details=[
            {
                "kind": "alternatives",
                "citation": citation,
                "members": [
                    word_range(TEXT, "por escrito"),
                    word_range(TEXT, "mediante comparecencia oral"),
                ],
                "reason": "La fuente ofrece dos modalidades alternativas.",
            }
        ],
    )
    units = materialize_detailed_units([proposal], request, index, aliases)
    text = (
        "Puede enviarla en un documento; alternativamente, exponerla verbalmente ante la oficina."
    )
    draft = {"paragraphs": [{"text": text, "cited_chunk_ids": [KEY]}], "pending": []}
    checks = [
        {
            "detail_id": "U1-K1",
            "status": "answered",
            "pending_indexes": [],
            "evidence": [
                {"paragraph_index": 0, "member_index": i, **word_range(text, wording)}
                for i, wording in enumerate(("en un documento", "exponerla verbalmente"), 1)
            ],
            "explanation": "El doble verifica escritura y exposición oral como alternativas.",
        }
    ]
    assert detail_issues(units, checks, draft) == []
    text = "Debe enviarla en un documento y además exponerla verbalmente ante la oficina."
    draft["paragraphs"][0]["text"] = text
    checks[0]["evidence"] = [
        {"paragraph_index": 0, "member_index": i, **word_range(text, wording)}
        for i, wording in enumerate(("en un documento", "exponerla verbalmente"), 1)
    ]
    checks[0].update(
        status="omitted", explanation="El doble detecta que ambas opciones se exigen conjuntamente."
    )
    assert codes(detail_issues(units, checks, draft)) == {"answer_detail_omitted"}


@pytest.mark.parametrize("state,basis", [("closed", "content_gap"), ("open", "metadata_only")])
def test_closed_or_metadata_pending_cannot_cover_a_missing_detail(state, basis):
    units, draft = units_and_draft()
    draft["pending"] = [{"description": "Control heredado.", "basis": basis, "state": state}]
    checks = checks_for(draft)
    checks[0].update(status="pending", evidence=[], pending_indexes=[0])
    before = deepcopy(draft)
    assert "detail_review_invalid" in codes(detail_issues(units, checks, draft))
    assert draft == before


@pytest.mark.parametrize("stage,blocks_approval", [
    ("fulfillment", False), ("fulfillment", True), ("evidence", False),
])
def test_required_detail_pending_must_reference_a_blocking_evidence_gap(stage, blocks_approval):
    units, draft = units_and_draft()
    draft["pending"] = [{
        "description": "Preparar el documento solicitado.", "basis": "content_gap",
        "stage": stage, "blocks_approval": blocks_approval,
    }]
    checks = checks_for(draft)
    checks[0].update(status="pending", evidence=[], pending_indexes=[0])
    before = deepcopy(draft)
    assert codes(detail_issues(units, checks, draft)) == {"detail_review_invalid"}
    assert draft == before


def test_each_pending_link_must_still_be_open_evidence_without_altering_real_gaps():
    units, draft = units_and_draft()
    draft["pending"] = [
        {"description": "Contrastar qué autoridad cubre la situación concreta.",
         "basis": "content_gap", "stage": "evidence", "blocks_approval": True},
        {"description": "Preparar el envío futuro.", "basis": "content_gap",
         "stage": "fulfillment", "blocks_approval": False},
    ]
    checks = checks_for(draft)
    checks[0].update(status="pending", evidence=[], pending_indexes=[0])
    before = deepcopy(draft)
    assert detail_issues(units, checks, draft) == []
    checks[0]["pending_indexes"] = [0, 1]
    assert codes(detail_issues(units, checks, draft)) == {"detail_review_invalid"}
    assert draft == before


def test_numbering_selected_sources_keeps_original_paragraph_indexes_and_complete_words():
    units, draft = units_and_draft()
    original = deepcopy(draft["paragraphs"][0])
    paragraphs = [
        {"text": "Contenido de otra fuente.", "cited_chunk_ids": ["another-source"]},
        {**original, "text": "\t" + original["text"] + "\r\n"},
        {"text": "Otro aporte no vinculado.", "cited_chunk_ids": []},
    ]
    all_numbered = numbered_detail_paragraphs(paragraphs)
    assert numbered_detail_paragraphs(paragraphs, units) == [all_numbered[1]]
    assert numbered_detail_paragraphs(paragraphs, units)[0]["paragraph_index"] == 1
    assert numbered_detail_paragraphs(paragraphs, []) == []
    assert len(all_numbered) == 3 and paragraphs[1]["text"].endswith("\r\n")


@pytest.mark.parametrize("literal,answer", [
    ("Unidad A-\n1", "Unidad A1"),
    ("Unidad 1-\nA", "Unidad 1A"),
    ("Unidad 1-\n2", "Unidad 12"),
])
def test_line_hyphens_cannot_erase_meaningful_alphanumeric_identifiers(literal, answer):
    from pqrs_claro.answer_coverage import _contains_identity

    assert not _contains_identity(literal, answer)
    assert _contains_identity(literal, literal)


def test_correction_or_access_revocation_invalidates_details_through_unit_citations():
    request, index, aliases, proposal = fixture()
    units = materialize_detailed_units([proposal], request, index, aliases)
    index[KEY]["quote"] = TEXT.replace(A, "Mesa de Otra Región")
    with pytest.raises(DomainError):
        validate_units(units, request, index)
    index[KEY]["quote"] = TEXT
    request["allowed_collection_ids"] = []
    with pytest.raises(DomainError):
        validate_units(units, request, index)


def test_schema_requires_explicit_detail_review_evidence_and_one_based_member_numbers():
    schema = DetailCheck.model_json_schema()
    assert set(schema["required"]) == {
        "detail_id",
        "status",
        "evidence",
        "pending_indexes",
        "explanation",
    }
    assert schema["$defs"]["DetailEvidence"]["properties"]["member_index"]["minimum"] == 1
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "name,rendered,valid",
    [
        ("Consejo de Recursos", "CONSEJO  DE RECURSOS", True),
        ("Consejo Técnico-Regional", "Consejo Técnico Regional", True),
        ("Consejo de Recur-\r\nsos", "Consejo de Recursos", True),
        ("Comité de' \r\n Asignación", "Comité de Asignación", True),
        ("Comisio\u0301n de Áreas", "Comisión de Áreas", True),
        ("Comisión de Áreas", "Comision de Areas", False),
        ("Consejo A-1", "Consejo A1", False),
        ("Dirección de Proyectos", "dependencia encargada", False),
    ],
)
def test_named_identity_allows_typography_but_never_a_generic_label_or_changed_identifier(
    name,
    rendered,
    valid,
):
    request, index, aliases, proposal = fixture()
    source = f"La {name} expide el informe.\r\n"
    index[KEY]["quote"] = source
    citation = {"chunk_id": "S1", "line_start": 1, "line_end": len(source.splitlines())}
    proposal.update(
        citations=[citation],
        details=[
            {
                "kind": "authority",
                "citation": citation,
                "members": [word_range(source, name)],
                "reason": "La identidad del emisor debe conservarse.",
            }
        ],
    )
    units = materialize_detailed_units([proposal], request, index, aliases)
    text = f"El informe lo expide el {rendered}."
    draft = {"paragraphs": [{"text": text, "cited_chunk_ids": [KEY]}], "pending": []}
    checks = [
        {
            "detail_id": "U1-K1",
            "status": "answered",
            "pending_indexes": [],
            "evidence": [{"paragraph_index": 0, "member_index": 1, **word_range(text, rendered)}],
            "explanation": "El doble indica que el emisor está identificado.",
        }
    ]
    issues = detail_issues(units, checks, draft)
    assert (not issues) is valid
    if not valid:
        assert codes(issues) == {"answer_detail_omitted"}
    assert units[0]["details"][0]["members"][0]["quote"] == name
