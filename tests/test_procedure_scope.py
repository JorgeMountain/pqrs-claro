"""Blind procedural clarity contract; doubles do not claim semantic model accuracy."""

import json
import re
from copy import deepcopy
from types import SimpleNamespace

import pytest
from openai import APIConnectionError

from pqrs_claro.models import DomainError
from pqrs_claro.procedure_scope import (
    PROCEDURE_SCOPE_POLICY_HASH,
    _assessment_model,
    _payload,
    _validated_rows,
    assess_procedure_scope,
    procedure_scope_input_hash,
    reconcile_procedure_scope_checks,
)


def inputs():
    request = {
        "title": "Consulta sobre dos trámites",
        "description": "Explique cada consecuencia.",
        "source_refs": [{"quote": "NO ENVIAR LOCALIZADORES"}],
        "context": {
            "subject": "Consulta delimitada",
            "sufficiency": "NO ENVIAR SUFICIENCIA",
            "document_context": {
                "excerpts": [
                    {
                        "quote": "Consulta ficticia sin actuación particular.",
                        "page": 9,
                        "source_id": "NO ENVIAR IDENTIFICADOR",
                    }
                ]
            },
            "referenced_requests": [
                {
                    "title": "Trámite previo",
                    "description": "Consulta hermana.",
                    "source_refs": [{"quote": "NO ENVIAR REFERENCIAS"}],
                }
            ],
        },
        "plan": "NO ENVIAR PLAN",
        "supports": [{"quote": "NO ENVIAR FUENTES"}],
        "pending": [{"description": "NO ENVIAR PENDIENTES"}],
    }
    paragraphs = [
        {
            "text": "La comisión tarifaria resuelve la revisión de cobro.",
            "cited_chunk_ids": ["private:1"],
        },
        {
            "text": "La comisión técnica evalúa las condiciones de seguridad. "
            "Su decisión sustituye la determinación inicial.",
            "cited_chunk_ids": ["private:2"],
        },
    ]
    return request, paragraphs


def clear():
    return {
        "paragraph_checks": [
            {
                "paragraph_index": index,
                "status": "clear",
                "effect_readings": [],
                "no_effect_reason": "El doble del proveedor declara que sólo describe el trámite.",
            }
            for index in range(2)
        ]
    }


def ambiguous():
    result = clear()
    result["paragraph_checks"][1] = {
        "paragraph_index": 1,
        "status": "ambiguous",
        "no_effect_reason": "",
        "effect_readings": [
            {
                "effect_quote": "Su decisión sustituye la determinación inicial.",
                "explicit_anchor": None,
                "antecedents": [
                    {
                        "paragraph_index": 0,
                        "quote": "La comisión tarifaria resuelve la revisión de cobro.",
                    },
                    {
                        "paragraph_index": 1,
                        "quote": "La comisión técnica evalúa las condiciones de seguridad.",
                    },
                ],
                "explanation": "No determina si el efecto pertenece a la revisión de cobro "
                "o a la evaluación de seguridad.",
            }
        ],
    }
    return result


def paragraph_text(paragraph):
    return paragraph["leading_whitespace"] + "".join(
        word[1] for word in paragraph["numbered_words"]
    )


def encode_scope_response(canonical_response, payload):
    """Explicit test double: select enclosing whole words of an exact fixture quote.

    This is never used in production and does not repair provider outputs.
    """
    value = deepcopy(canonical_response)
    if not isinstance(value, dict):
        return value
    if "paragraph_checks" not in value:
        return value
    rows = value["paragraph_checks"]
    expected = set(range(len(payload["paragraphs"])))
    indexes = [row.get("paragraph_index") for row in rows]
    if (
        any(type(index) is not int for index in indexes)
        or len(indexes) != len(expected)
        or set(indexes) != expected
    ):
        # A malformed legacy fixture remains malformed, never silently collapsed
        # into a dict that would conceal missing, duplicate or invented rows.
        return value
    texts = [paragraph_text(p) for p in payload["paragraphs"]]

    def encode(span):
        if span is None or "quote" not in span:
            return span
        index, quote = span["paragraph_index"], span["quote"]
        text = texts[index]
        start = text.index(quote)
        end = start + len(quote)
        words = list(re.finditer(r"\S+", text))
        selected = [
            i + 1 for i, word in enumerate(words) if word.start() < end and word.end() > start
        ]
        assert quote.strip() and selected
        return {"paragraph_index": index, "word_start": selected[0], "word_end": selected[-1]}

    for row in value.get("paragraph_checks", []):
        for reading in row.get("effect_readings", []):
            if "effect_quote" not in reading or "effect_span" in reading:
                continue
            reading["effect_span"] = encode(
                {"paragraph_index": row["paragraph_index"], "quote": reading.pop("effect_quote")}
            )
            reading["antecedents"] = [encode(s) for s in reading["antecedents"]]
            context_anchor = reading.pop("context_anchor", None)
            if reading["explicit_anchor"] is None and context_anchor is not None:
                reading["explicit_anchor"] = context_anchor
            reading["explicit_anchor"] = encode(reading["explicit_anchor"])
    return {
        **{key: item for key, item in value.items() if key != "paragraph_checks"},
        **{
            f"paragraph_{row['paragraph_index']}": {
                key: item for key, item in row.items() if key != "paragraph_index"
            }
            for row in rows
        },
    }


def client_for(result, *, status="completed", callback=None, output_text=None):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        if callback:
            callback()
        if isinstance(result, Exception):
            raise result
        parsed = encode_scope_response(result, json.loads(kwargs["input"]))
        return SimpleNamespace(status=status, output_parsed=parsed, output_text=output_text)

    return SimpleNamespace(responses=SimpleNamespace(parse=parse)), calls


def test_payload_is_blind_and_preserves_exact_current_text_and_only_scope():
    request, paragraphs = inputs()
    before = deepcopy((request, paragraphs))
    client, calls = client_for(clear())
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert len(calls) == 1
    call = calls[0]
    payload = json.loads(call["input"])
    assert [paragraph_text(p) for p in payload["paragraphs"]] == [p["text"] for p in paragraphs]
    assert all("text" not in p for p in payload["paragraphs"])
    assert [p["paragraph_index"] for p in payload["paragraphs"]] == [0, 1]
    for p in payload["paragraphs"]:
        assert [w[0] for w in p["numbered_words"]] == list(range(1, len(p["numbered_words"]) + 1))
    assert payload["request_scope"]["original_petition_excerpts"] == [
        "Consulta ficticia sin actuación particular."
    ]
    assert payload["request_scope"]["related_requests"]["referenced_requests"] == [
        {"title": "Trámite previo", "description": "Consulta hermana."}
    ]
    assert "NO ENVIAR" not in call["input"] and "private:" not in call["input"]
    assert "cited_chunk_ids" not in call["input"]
    assert call["store"] is False and call["truncation"] == "disabled"
    assert call["max_output_tokens"] == 8000 and call["model"] == "test-model"
    assert call["text_format"] is _assessment_model(2)
    assert result["issues"] == [] and result["local_checks"] == [] and result["readings"] == []
    assert result["input_hash"] == procedure_scope_input_hash(request, paragraphs)
    assert result["policy_hash"] == PROCEDURE_SCOPE_POLICY_HASH
    assert (request, paragraphs) == before


def test_blind_ambiguity_records_reading_without_a_verdict_or_changes_to_text_and_pending():
    request, paragraphs = inputs()
    before = deepcopy((request, paragraphs))
    client, _ = client_for(ambiguous())
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["issues"] == [] and result["local_checks"] == []
    assert len(result["readings"]) == 1
    assert result["readings"][0]["reading_id"] == "L1"
    assert result["readings"][0]["paragraph_index"] == 1
    assert result["readings"][0]["blind_status"] == "ambiguous"
    assert (
        result["readings"][0]["effect_quote"] == "Su decisión sustituye la determinación inicial."
    )
    assert (request, paragraphs) == before


def test_multiple_antecedents_without_anchor_do_not_automatically_veto_a_reading():
    request, paragraphs = inputs()
    proposal = ambiguous()
    proposal["paragraph_checks"][1]["status"] = "clear"
    client, calls = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert len(calls) == 1
    assert result["paragraph_checks"][1]["status"] == "clear"
    assert len(result["readings"][0]["antecedents"]) == 2
    assert result["issues"] == [] and result["local_checks"] == []


def test_single_antecedent_with_textual_continuity_does_not_force_a_repeated_label():
    request, paragraphs = inputs()
    proposal = ambiguous()
    row = proposal["paragraph_checks"][1]
    row["status"] = "clear"
    row["effect_readings"][0]["antecedents"] = row["effect_readings"][0]["antecedents"][1:]
    row["effect_readings"][0]["explanation"] = "El doble atribuye continuidad al sujeto inmediato."
    client, _ = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["issues"] == []
    assert result["paragraph_checks"][1]["effect_readings"][0]["explicit_anchor"] is None


@pytest.mark.parametrize("anchor_location", ["preceding", "enclosing", "other_paragraph"])
@pytest.mark.parametrize("antecedent_count", [1, 2])
def test_valid_context_anchor_is_preserved_for_source_contrast_without_a_count_based_verdict(
    anchor_location, antecedent_count
):
    request, paragraphs = inputs()
    before = deepcopy((request, paragraphs))
    proposal = ambiguous()
    row = proposal["paragraph_checks"][1]
    row["status"] = "clear"
    reading = row["effect_readings"][0]
    anchors = {
        "preceding": deepcopy(reading["antecedents"][1]),
        "enclosing": {"paragraph_index": 1, "quote": paragraphs[1]["text"]},
        "other_paragraph": deepcopy(reading["antecedents"][0]),
    }
    expected_anchor = anchors[anchor_location]
    reading["explicit_anchor"] = expected_anchor
    if antecedent_count == 1:
        reading["antecedents"] = [reading["antecedents"][1]]
        reading["explanation"] = "El doble observa continuidad inequívoca con una actuación."
    client, calls = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    checked = result["paragraph_checks"][1]
    assert checked["effect_readings"][0]["context_anchor"] == expected_anchor
    assert checked["effect_readings"][0]["explicit_anchor"] is None
    assert checked["status"] == "clear"
    assert result["readings"][0]["context_anchor"] == expected_anchor
    assert len(result["readings"][0]["antecedents"]) == antecedent_count
    assert result["issues"] == [] and result["local_checks"] == []
    assert len(calls) == 1 and (request, paragraphs) == before


def test_explicit_literal_anchor_allows_a_clear_effect_after_multiple_procedures():
    request, paragraphs = inputs()
    proposal = ambiguous()
    effect = "En la revisión del cobro, la decisión sustituye la determinación inicial."
    paragraphs[1]["text"] = "La comisión técnica evalúa las condiciones de seguridad. " + effect
    row = proposal["paragraph_checks"][1]
    row["status"] = "clear"
    reading = row["effect_readings"][0]
    reading.update(
        effect_quote=effect,
        explicit_anchor={"paragraph_index": 1, "quote": "En la revisión del cobro"},
        explanation="La propia consecuencia se limita expresamente a la revisión de cobro.",
    )
    client, _ = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["issues"] == [] and result["local_checks"] == []
    assert result["paragraph_checks"][1]["effect_readings"][0]["context_anchor"] is None


def test_explicit_uncertainty_remains_clear_without_choosing_or_closing_a_pending():
    request, _ = inputs()
    pending = deepcopy(request["pending"])
    text = (
        "La regla A indica dos días; la regla B, tres días. "
        "No se ha determinado cuál de esos plazos aplica."
    )
    paragraphs = [{"text": text}]
    client, _ = client_for(
        {
            "paragraph_checks": [
                {
                    "paragraph_index": 0,
                    "status": "clear",
                    "no_effect_reason": "",
                    "effect_readings": [
                        {
                            "effect_quote": "No se ha determinado cuál de esos plazos aplica.",
                            "antecedents": [
                                {"paragraph_index": 0, "quote": "La regla A indica dos días"},
                                {"paragraph_index": 0, "quote": "la regla B, tres días"},
                            ],
                            "explicit_anchor": {
                                "paragraph_index": 0,
                                "quote": "No se ha determinado",
                            },
                            "explanation": "Se declara incertidumbre sobre los dos plazos "
                            "en vez de atribuir uno.",
                        }
                    ],
                }
            ]
        }
    )
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["issues"] == [] and request["pending"] == pending


def test_source_comparison_pending_can_be_outside_procedural_scope_without_closing_it():
    request, _ = inputs()
    request["pending"] = [{"description": "Cotejar la vigencia de las dos fuentes."}]
    paragraphs = [
        {
            "text": "El instructivo y el acuerdo describen el mismo trámite. "
            "Sigue pendiente cotejar su vigencia y aplicabilidad."
        }
    ]
    before = deepcopy((request, paragraphs))
    proposal = {
        "paragraph_checks": [
            {
                "paragraph_index": 0,
                "status": "clear",
                "effect_readings": [],
                "no_effect_reason": "Sólo declara un cotejo abierto de fuentes del mismo trámite; "
                "no atribuye una consecuencia de una actuación a otra.",
            }
        ]
    }
    client, calls = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["issues"] == [] and result["local_checks"] == []
    assert result["paragraph_checks"] == proposal["paragraph_checks"]
    assert (request, paragraphs) == before and len(calls) == 1


def invalid_cases():
    request, paragraphs = inputs()
    payload = _payload(request, paragraphs)

    def remote():
        mapping = encode_scope_response(ambiguous(), payload)
        return {
            "paragraph_checks": [
                {"paragraph_index": i, **mapping[f"paragraph_{i}"]} for i in range(2)
            ]
        }

    yield "missing", {"paragraph_checks": clear()["paragraph_checks"][:1]}
    yield "duplicate", {"paragraph_checks": [clear()["paragraph_checks"][0]] * 2}
    for label, index in (("outside", 8), ("bool_index", True), ("string_index", "1")):
        value = clear()
        value["paragraph_checks"][1]["paragraph_index"] = index
        yield label, value
    value = clear()
    value["paragraph_checks"][1]["status"] = "ambiguous"
    yield "empty_ambiguity", value
    for label, field, number in (
        ("negative_start", "word_start", -1),
        ("zero_start", "word_start", 0),
        ("out_of_bounds_end", "word_end", 999),
        ("reversed", "word_end", 1),
        ("boolean_word", "word_start", True),
        ("string_word", "word_start", "1"),
        ("effect_wrong_paragraph", "paragraph_index", 0),
    ):
        value = remote()
        value["paragraph_checks"][1]["effect_readings"][0]["effect_span"][field] = number
        yield label, value
    value = remote()
    value["paragraph_checks"][1]["effect_readings"][0]["effect_quote"] = "Invented prose."
    yield "provider_cannot_write_quote", value
    value = remote()
    value["paragraph_checks"][1]["effect_readings"][0]["explanation"] = " "
    yield "blank_explanation", value
    value = remote()
    spans = value["paragraph_checks"][1]["effect_readings"][0]["antecedents"]
    spans[1] = deepcopy(spans[0])
    yield "duplicate_antecedent", value
    value = remote()
    value["paragraph_checks"][1]["effect_readings"][0]["antecedents"][1]["word_end"] = 900
    yield "antecedent_word_outside", value
    value = remote()
    value["paragraph_checks"][1]["effect_readings"][0]["antecedents"][1]["paragraph_index"] = 9
    yield "antecedent_paragraph_outside", value
    for field in ("pending", "paragraphs"):
        value = clear()
        value[field] = []
        yield "prohibited_" + field, value
    value = clear()
    value["paragraph_checks"][1]["no_effect_reason"] = " "
    yield "unexplained_empty_effects", value
    value = remote()
    value["paragraph_checks"][1]["no_effect_reason"] = "Declara que no hay efectos."
    yield "effects_claimed_absent", value
    for label, field, replacement in (
        ("anchor_paragraph_outside", "paragraph_index", 9),
        ("anchor_word_outside", "word_end", 999),
        ("anchor_reversed", "word_start", 999),
        ("anchor_zero_start", "word_start", 0),
        ("anchor_cannot_add_text", "quote", "Invented prose."),
    ):
        value = remote()
        reading = value["paragraph_checks"][1]["effect_readings"][0]
        reading["explicit_anchor"] = deepcopy(reading["antecedents"][1])
        reading["explicit_anchor"][field] = replacement
        yield label, value
    value = remote()
    value["paragraph_checks"][1]["effect_readings"][0]["antecedents"] = []
    yield "effect_without_antecedent", value


@pytest.mark.parametrize(
    "label,value", list(invalid_cases()), ids=lambda v: v if isinstance(v, str) else None
)
def test_invalid_checker_contract_cannot_be_treated_as_passed(label, value):
    request, paragraphs = inputs()
    before = deepcopy((request, paragraphs))
    client, calls = client_for(value)
    with pytest.raises(DomainError):
        assess_procedure_scope(client, "test-model", request, paragraphs)
    assert len(calls) == 1 and (request, paragraphs) == before


@pytest.mark.parametrize("count", [0, 1, 2, 30])
def test_remote_schema_requires_exact_paragraph_fields_without_generated_row_indexes(count):
    model = _assessment_model(count)
    schema = model.model_json_schema()
    expected = {f"paragraph_{i}" for i in range(count)}
    assert model is _assessment_model(count) and model.__name__ == "_Assessment"
    assert set(schema["properties"]) == expected
    assert set(schema.get("required", [])) == expected
    assert schema["additionalProperties"] is False
    if count:
        reading_schema = schema["$defs"]["_ParagraphReading"]
        assert set(reading_schema["properties"]) == {
            "status",
            "effect_readings",
            "no_effect_reason",
        }
        assert set(reading_schema["required"]) == set(reading_schema["properties"])
        assert reading_schema["additionalProperties"] is False


@pytest.mark.parametrize("defect", ["missing", "extra", "row_index", "range_mismatch"])
def test_exact_field_contract_rejects_missing_extra_rows_and_mismatched_effects(defect):
    request, paragraphs = inputs()
    proposal = encode_scope_response(ambiguous(), _payload(request, paragraphs))
    if defect == "missing":
        del proposal["paragraph_1"]
    elif defect == "extra":
        proposal["paragraph_2"] = deepcopy(proposal["paragraph_1"])
    elif defect == "row_index":
        proposal["paragraph_1"]["paragraph_index"] = 2
    else:
        proposal["paragraph_0"], proposal["paragraph_1"] = (
            proposal["paragraph_1"],
            proposal["paragraph_0"],
        )
    client, calls = client_for(proposal)
    with pytest.raises(DomainError):
        assess_procedure_scope(client, "test-model", request, paragraphs)
    assert len(calls) == 1


def test_matching_dynamic_model_restores_canonical_order_and_mismatched_model_is_rejected():
    request, paragraphs = inputs()
    payload = _payload(request, paragraphs)
    proposal = encode_scope_response(clear(), payload)
    reversed_fields = dict(reversed(list(proposal.items())))
    parsed = _assessment_model(2).model_validate(reversed_fields)
    assert _validated_rows(parsed, payload) == clear()["paragraph_checks"]
    partial = _assessment_model(1).model_validate({"paragraph_0": proposal["paragraph_0"]})
    with pytest.raises(DomainError):
        _validated_rows(partial, payload)


@pytest.mark.parametrize("duplicate_level", ["paragraph", "reading"])
def test_duplicate_lexical_json_fields_are_rejected_even_if_sdk_dict_collapsed_them(
    duplicate_level,
):
    request, paragraphs = inputs()
    proposal = encode_scope_response(clear(), _payload(request, paragraphs))
    text = json.dumps(proposal)
    if duplicate_level == "paragraph":
        text = text[:-1] + ', "paragraph_0": ' + json.dumps(proposal["paragraph_0"]) + "}"
    else:
        text = text.replace('"status": "clear"', '"status": "clear", "status": "clear"', 1)
    assert json.loads(text) == proposal
    before = deepcopy((request, paragraphs))
    client, calls = client_for(proposal, output_text=text)
    with pytest.raises(DomainError, match="duplicados"):
        assess_procedure_scope(client, "test-model", request, paragraphs)
    assert len(calls) == 1 and (request, paragraphs) == before


@pytest.mark.parametrize("response,status", [(clear(), "incomplete"), (None, "completed")])
def test_incomplete_provider_response_blocks_without_rewriting(response, status):
    request, paragraphs = inputs()
    before = deepcopy((request, paragraphs))
    client, _ = client_for(response, status=status)
    with pytest.raises(DomainError, match="no terminó"):
        assess_procedure_scope(client, "test-model", request, paragraphs)
    assert (request, paragraphs) == before


def test_provider_failure_preserves_original_text_and_pending():
    import httpx

    request, paragraphs = inputs()
    before = deepcopy((request, paragraphs))
    client, calls = client_for(
        APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    )
    with pytest.raises(DomainError, match="se conservan"):
        assess_procedure_scope(client, "test-model", request, paragraphs)
    assert len(calls) == 1 and (request, paragraphs) == before


def test_empty_body_does_not_call_api_or_resolve_pending():
    request, _ = inputs()
    before = deepcopy(request)
    client, calls = client_for(clear())
    result = assess_procedure_scope(client, "test-model", request, [])
    assert calls == [] and result["issues"] == [] and result["local_checks"] == []
    assert request == before


def test_fingerprint_tracks_text_order_scope_and_policy_but_not_hidden_citations():
    request, paragraphs = inputs()
    before = procedure_scope_input_hash(request, paragraphs)
    paragraphs[0]["cited_chunk_ids"] = ["replacement:hidden"]
    assert procedure_scope_input_hash(request, paragraphs) == before
    request["supports"] = []
    assert procedure_scope_input_hash(request, paragraphs) == before
    assert procedure_scope_input_hash(request, paragraphs[::-1]) != before
    paragraphs[0]["text"] += " \n"
    assert procedure_scope_input_hash(request, paragraphs) != before
    paragraphs[0]["text"] = paragraphs[0]["text"][:-2]
    request["description"] += " Con otro alcance."
    assert procedure_scope_input_hash(request, paragraphs) != before


def test_inflight_text_change_invalidates_result_instead_of_reusing_old_hash():
    request, paragraphs = inputs()
    client, _ = client_for(clear(), callback=lambda: paragraphs[0].update(text="Texto editado."))
    with pytest.raises(DomainError, match="cambió"):
        assess_procedure_scope(client, "test-model", request, paragraphs)


@pytest.mark.parametrize(
    "paragraphs",
    [[{"text": " "}], [{"text": 42}], [{"text": "x" * 6001}], [{"text": "Texto."}] * 31, "invalid"],
)
def test_invalid_input_is_rejected_before_api(paragraphs):
    request, _ = inputs()
    client, calls = client_for(clear())
    with pytest.raises(DomainError):
        assess_procedure_scope(client, "test-model", request, paragraphs)
    assert calls == []


@pytest.mark.parametrize("count", [21, 30])
def test_shared_checker_accepts_all_paragraphs_allowed_by_human_review(count):
    request, _ = inputs()
    paragraphs = [
        {"text": f"El párrafo {index} describe el mismo trámite."} for index in range(count)
    ]
    client, calls = client_for(
        {
            "paragraph_checks": [
                {
                    "paragraph_index": index,
                    "status": "clear",
                    "effect_readings": [],
                    "no_effect_reason": "Sólo identifica el párrafo de descripción.",
                }
                for index in range(count)
            ]
        }
    )
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert len(calls) == 1 and result["issues"] == []
    assert len(result["paragraph_checks"]) == count
    assert len(json.loads(calls[0]["input"])["paragraphs"]) == count


@pytest.mark.parametrize("length", [5001, 6000])
def test_shared_checker_accepts_long_paragraphs_allowed_by_human_review(length):
    request, _ = inputs()
    paragraphs = [{"text": "x" * length}]
    client, calls = client_for(
        {
            "paragraph_checks": [
                {
                    "paragraph_index": 0,
                    "status": "clear",
                    "effect_readings": [],
                    "no_effect_reason": "No contiene una oración con consecuencias.",
                }
            ]
        }
    )
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["issues"] == []
    assert paragraph_text(json.loads(calls[0]["input"])["paragraphs"][0]) == paragraphs[0]["text"]


def test_longest_allowed_issue_fits_existing_engine_description_contract():
    request, _ = inputs()
    effect = "E" * 1500
    paragraphs = [{"text": "Primera revisión. Segunda evaluación. " + effect}]
    client, _ = client_for(
        {
            "paragraph_checks": [
                {
                    "paragraph_index": 0,
                    "status": "ambiguous",
                    "no_effect_reason": "",
                    "effect_readings": [
                        {
                            "effect_quote": effect,
                            "explanation": "X" * 1200,
                            "explicit_anchor": None,
                            "antecedents": [
                                {"paragraph_index": 0, "quote": "Primera revisión."},
                                {"paragraph_index": 0, "quote": "Segunda evaluación."},
                            ],
                        }
                    ],
                }
            ]
        }
    )
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    checked = reconcile_procedure_scope_checks(
        result["readings"],
        [{"reading_id": "L1", "status": "ambiguous", "cited_chunk_ids": [], "reason": "X" * 1200}],
        [],
    )
    assert effect in checked["issues"][0]["description"]
    assert len(checked["issues"][0]["description"]) <= 3000


def test_numbered_selection_materializes_unicode_crlf_tabs_and_spaces_exactly():
    request, _ = inputs()
    text = "  Revisión ágil 🧪.\r\n\tLa decisión\u00a0de revisión  sustituye\r\nla inicial.  "
    paragraphs = [{"text": text}]
    payload = _payload(request, paragraphs)
    assert paragraph_text(payload["paragraphs"][0]) == text
    numbered = payload["paragraphs"][0]["numbered_words"]
    assert [w[0] for w in numbered] == list(range(1, len(numbered) + 1))
    effect = "La decisión\u00a0de revisión  sustituye\r\nla inicial."
    proposal = {
        "paragraph_checks": [
            {
                "paragraph_index": 0,
                "status": "clear",
                "no_effect_reason": "",
                "effect_readings": [
                    {
                        "effect_quote": effect,
                        "antecedents": [{"paragraph_index": 0, "quote": "Revisión ágil 🧪."}],
                        "explicit_anchor": {"paragraph_index": 0, "quote": "de revisión"},
                        "explanation": "La consecuencia identifica explícitamente la revisión.",
                    }
                ],
            }
        ]
    }
    client, calls = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    reading = result["paragraph_checks"][0]["effect_readings"][0]
    assert reading["effect_quote"] == effect
    assert reading["antecedents"][0]["quote"] == "Revisión ágil 🧪."
    assert reading["explicit_anchor"]["quote"] == "de revisión"
    assert len(calls) == 1


def test_numbering_overhead_does_not_reject_largest_existing_review_input():
    request, _ = inputs()
    paragraphs = [{"text": "a " * 3000} for _ in range(30)]
    proposal = {
        "paragraph_checks": [
            {
                "paragraph_index": i,
                "status": "clear",
                "effect_readings": [],
                "no_effect_reason": "Repite una palabra sin atribuir ninguna consecuencia.",
            }
            for i in range(30)
        ]
    }
    client, calls = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["issues"] == [] and len(calls) == 1
    payload = json.loads(calls[0]["input"])
    assert len(payload["paragraphs"]) == 30
    assert all(paragraph_text(p) == "a " * 3000 for p in payload["paragraphs"])
    assert all(len(p["numbered_words"]) == 3000 for p in payload["paragraphs"])


def test_long_materialized_effect_keeps_full_qa_text_but_bounds_display_issue():
    request, _ = inputs()
    effect = "efecto " * 400 + "final."
    paragraphs = [{"text": "Primera revisión. Segunda evaluación. " + effect}]
    client, _ = client_for(
        {
            "paragraph_checks": [
                {
                    "paragraph_index": 0,
                    "status": "ambiguous",
                    "no_effect_reason": "",
                    "effect_readings": [
                        {
                            "effect_quote": effect,
                            "antecedents": [
                                {"paragraph_index": 0, "quote": "Primera revisión."},
                                {"paragraph_index": 0, "quote": "Segunda evaluación."},
                            ],
                            "explicit_anchor": None,
                            "explanation": "X" * 1200,
                        }
                    ],
                }
            ]
        }
    )
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["paragraph_checks"][0]["effect_readings"][0]["effect_quote"] == effect
    checked = reconcile_procedure_scope_checks(
        result["readings"],
        [{"reading_id": "L1", "status": "ambiguous", "cited_chunk_ids": [], "reason": "X" * 1200}],
        [],
    )
    assert len(checked["issues"][0]["description"]) <= 3000
    assert "…" in checked["issues"][0]["description"]


def test_operation_is_recorded_by_existing_provider_metrics(monkeypatch):
    import pqrs_claro.procedure_scope as module

    request, paragraphs = inputs()
    client, _ = client_for(clear())
    operations = []

    def track(name, function, **kwargs):
        operations.append(name)
        return function(**kwargs)

    monkeypatch.setattr(module, "provider_call", track)
    assess_procedure_scope(
        client, "test-model", request, paragraphs, operation="review.procedure_scope"
    )
    assert operations == ["review.procedure_scope"]


@pytest.mark.parametrize("antecedent_count", [1, 2])
def test_ambiguous_reading_with_literal_anchor_remains_information_for_source_checker(
    antecedent_count,
):
    request, paragraphs = inputs()
    proposal = ambiguous()
    reading = proposal["paragraph_checks"][1]["effect_readings"][0]
    reading["antecedents"] = reading["antecedents"][:antecedent_count]
    reading["explicit_anchor"] = {"paragraph_index": 1, "quote": reading["effect_quote"]}
    client, calls = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    assert result["readings"][0]["blind_status"] == "ambiguous"
    assert result["readings"][0]["explicit_anchor"] is not None
    assert result["issues"] == [] and result["local_checks"] == [] and len(calls) == 1


def contrast_inputs():
    request, paragraphs = inputs()
    proposal = ambiguous()
    proposal["paragraph_checks"][1]["status"] = "clear"
    client, calls = client_for(proposal)
    result = assess_procedure_scope(client, "test-model", request, paragraphs)
    judgment = {
        "reading_id": "L1",
        "status": "supported",
        "cited_chunk_ids": ["private:2"],
        "reason": "El doble del checker contrasta la lectura con la evidencia del párrafo.",
    }
    return request, paragraphs, result["readings"], judgment, calls


@pytest.mark.parametrize(
    "status,citations,expected_code",
    [
        ("supported", ["private:2"], None),
        ("misattributed", ["private:1"], "procedure_scope_misattributed"),
        ("ambiguous", [], "procedure_scope_ambiguous"),
        ("not_procedural", [], None),
    ],
)
def test_source_judgment_decides_instead_of_blind_status_or_antecedent_count(
    status, citations, expected_code
):
    request, paragraphs, readings, judgment, calls = contrast_inputs()
    before = deepcopy((request, paragraphs, readings))
    assert readings[0]["blind_status"] == "clear" and len(readings[0]["antecedents"]) == 2
    judgment.update(status=status, cited_chunk_ids=citations)
    checked = reconcile_procedure_scope_checks(
        readings, [judgment], {"private:1", "private:2"}, paragraphs=paragraphs
    )
    if expected_code:
        assert len(checked["issues"]) == 1
        assert checked["issues"][0]["code"] == expected_code
        assert checked["issues"][0]["paragraph_index"] == 1
        assert readings[0]["effect_quote"] in checked["issues"][0]["description"]
        assert checked["local_checks"][0]["passed"] is False
    else:
        assert checked["issues"] == [] and checked["local_checks"][0]["passed"]
    assert (request, paragraphs, readings) == before and len(calls) == 1


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "extra",
        "wrong_id",
        "requirement_id",
        "extra_field",
        "invalid_status",
    ],
)
def test_source_contrast_requires_one_complete_judgment_per_current_reading(defect):
    _, paragraphs, readings, judgment, _ = contrast_inputs()
    checks = [deepcopy(judgment)]
    if defect == "missing":
        checks = []
    elif defect == "duplicate":
        checks.append(deepcopy(judgment))
    elif defect == "extra":
        checks.append({**judgment, "reading_id": "L2"})
    elif defect == "wrong_id":
        checks[0]["reading_id"] = "L2"
    elif defect == "requirement_id":
        checks[0]["reading_id"] = "R1"
    elif defect == "extra_field":
        checks[0]["pending"] = []
    else:
        checks[0]["status"] = "approved"
    with pytest.raises(DomainError):
        reconcile_procedure_scope_checks(
            readings, checks, {"private:1", "private:2"}, paragraphs=paragraphs
        )


@pytest.mark.parametrize(
    "status,citations,reason",
    [
        ("supported", [], "Explicación concreta."),
        ("misattributed", [], "Explicación concreta."),
        ("supported", ["unknown:9"], "Explicación concreta."),
        ("misattributed", ["unknown:9"], "Explicación concreta."),
        ("not_procedural", ["unknown:9"], "Explicación concreta."),
        ("ambiguous", ["private:2", "private:2"], "Explicación concreta."),
        ("not_procedural", [], " "),
        ("supported", ["private:2"], ""),
    ],
)
def test_contrast_rejects_unjustified_or_unauthorized_source_verdicts(status, citations, reason):
    _, paragraphs, readings, judgment, _ = contrast_inputs()
    judgment.update(status=status, cited_chunk_ids=citations, reason=reason)
    with pytest.raises(DomainError):
        reconcile_procedure_scope_checks(
            readings, [judgment], {"private:1", "private:2"}, paragraphs=paragraphs
        )


def test_supported_cannot_borrow_a_citation_from_another_paragraph():
    _, paragraphs, readings, judgment, _ = contrast_inputs()
    judgment["cited_chunk_ids"] = ["private:1"]
    with pytest.raises(DomainError, match="propio párrafo"):
        reconcile_procedure_scope_checks(
            readings, [judgment], {"private:1", "private:2"}, paragraphs=paragraphs
        )


def test_review_can_reference_authorized_cited_facts_without_authorizing_pending_aliases():
    _, paragraphs, readings, judgment, _ = contrast_inputs()
    paragraphs[1]["cited_fact_ids"] = ["F1"]
    judgment["cited_chunk_ids"] = ["F1"]
    checked = reconcile_procedure_scope_checks(
        readings, [judgment], {"private:1", "private:2", "F1"}, paragraphs=paragraphs
    )
    assert checked["issues"] == [] and checked["local_checks"][0]["passed"]
    judgment["cited_chunk_ids"] = ["M1"]
    with pytest.raises(DomainError, match="no autorizadas"):
        reconcile_procedure_scope_checks(
            readings, [judgment], {"private:1", "private:2", "F1"}, paragraphs=paragraphs
        )


@pytest.mark.parametrize("defect", ["duplicate", "negative_index", "outside_index", "blank_effect"])
def test_contrast_cannot_approve_malformed_reading_identity_or_paragraph(defect):
    _, paragraphs, readings, judgment, _ = contrast_inputs()
    if defect == "duplicate":
        readings.append(deepcopy(readings[0]))
    elif defect == "negative_index":
        readings[0]["paragraph_index"] = -1
    elif defect == "outside_index":
        readings[0]["paragraph_index"] = 2
    else:
        readings[0]["effect_quote"] = " "
    with pytest.raises(DomainError):
        reconcile_procedure_scope_checks(
            readings, [judgment], {"private:1", "private:2"}, paragraphs=paragraphs
        )


def test_no_readings_does_not_claim_a_source_contrast_and_rejects_invented_judgments():
    assert reconcile_procedure_scope_checks([], [], set()) == {"issues": [], "local_checks": []}
    with pytest.raises(DomainError):
        reconcile_procedure_scope_checks(
            [],
            [
                {
                    "reading_id": "L1",
                    "status": "not_procedural",
                    "cited_chunk_ids": [],
                    "reason": "Ninguno.",
                }
            ],
            set(),
        )


@pytest.mark.parametrize("literal", ["S1", "F1"])
def test_reason_rendering_never_changes_literal_effect_text(literal):
    effect = f"El identificador {literal} permanece en la frase original."
    readings = [{"reading_id": "L1", "paragraph_index": 0, "effect_quote": effect}]
    checks = [
        {
            "reading_id": "L1",
            "status": "misattributed",
            "cited_chunk_ids": [literal],
            "reason": f"La evidencia {literal} atribuye la consecuencia a otra actuación.",
        }
    ]
    calls = []

    def render(reason):
        calls.append(reason)
        return reason.replace(literal, "Documento con nombre materializado")

    checked = reconcile_procedure_scope_checks(readings, checks, {literal}, render_reason=render)
    assert calls == [checks[0]["reason"]]
    assert f"«{effect}»" in checked["issues"][0]["description"]
    assert "La evidencia Documento con nombre materializado" in checked["issues"][0]["description"]


def test_reason_rendering_bounds_long_source_names_without_truncating_the_qa_reading():
    effect = "E" * 1500
    readings = [{"reading_id": "L1", "paragraph_index": 0, "effect_quote": effect}]
    checks = [{"reading_id": "L1", "status": "ambiguous", "cited_chunk_ids": [], "reason": "S1"}]
    checked = reconcile_procedure_scope_checks(
        readings, checks, set(), render_reason=lambda _: "Documento " * 1000
    )
    description = checked["issues"][0]["description"]
    assert effect in description and len(description) <= 3000 and description.endswith("…")
    assert readings[0]["effect_quote"] == effect and checks[0]["reason"] == "S1"


@pytest.mark.parametrize("rendered", [None, " ", 42])
def test_reason_rendering_cannot_erase_the_required_explanation(rendered):
    _, _, readings, judgment, _ = contrast_inputs()
    judgment.update(status="ambiguous", cited_chunk_ids=[])
    with pytest.raises(DomainError, match="explicación válida"):
        reconcile_procedure_scope_checks(
            readings, [judgment], set(), render_reason=lambda _: rendered
        )
