"""Closed locations, exact source text and safe diagnostics; no real provider calls."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_source_analysis import api_document_coverage, chunk, request, selection

from pqrs_claro.source_assessment import OpenAISourceAssessor, _LocatedSourceSelection
from pqrs_claro.source_passages import PassageRange, SourceAnalysisError, numbered_lines


def located(original, start=1, end=1, alias="C1", **changes):
    data = selection(coverage_complete=True,
                     coverage=[api_document_coverage("C1", original)]).model_dump()
    data["supports"][0]["chunk_id"] = "C1"
    data["coverage"][0]["citations"] = [dict(chunk_id=alias, line_start=start, line_end=end)]
    data.update(changes)
    return _LocatedSourceSelection.model_validate(data)


def assessor_with(*outputs):
    calls = []
    items = iter(outputs)
    assessor = OpenAISourceAssessor("test-not-real", "test-model")

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=next(items))

    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    return assessor, calls


def test_remote_schema_uses_locations_and_program_copies_exact_unicode_crlf():
    source = chunk(quote=("ACTA DEL COMITÉ DE PRÁCTICAS 14\r\n"
                          "  Acción aprobada: A\u0301.\r\n\r\nCierre."),
                   line_start=70, line_end=73)
    assessor, calls = assessor_with(located(source, 2, 3))
    result = assessor.assess(request(), [source])
    citation = result["sufficiency"]["coverage"][0]["citations"][0]
    assert citation == {"chunk_id": source["chunk_id"],
                        "quote": "  Acción aprobada: A\u0301.\r\n\r\n"}
    sent = json.loads(calls[0]["input"])["candidates"][0]
    assert "quote" not in sent
    assert sent["numbered_lines"] == numbered_lines(source["quote"])
    assert calls[0]["text_format"] is _LocatedSourceSelection
    schema = calls[0]["text_format"].model_json_schema()
    assert '"quote"' not in json.dumps(schema)
    assert '"declaration_quote"' not in json.dumps(schema)
    location = result["citation_locations"][0]
    assert location["passage_line_start"] == 2 and location["chunk_line_start"] == 70
    assert result["supports"][0]["quote"] == source["quote"]
    assert result["analysis_diagnostic"]["attempts"] == 1


@pytest.mark.parametrize("start,end,alias,reason", [
    (2, 1, "C1", "invalid_passage_range"),
    (1, 50, "C1", "invalid_passage_range"),
    (1, 1, "C99", "unknown_candidate"),
    (1, 1, "C2", "candidate_not_selected_in_supports"),
    (2, 2, "C1", "empty_passage"),
])
def test_invalid_locations_are_repaired_once_then_rejected_without_fake_missing(
    start, end, alias, reason
):
    source = chunk(quote="Encabezado\n\nTexto privado que no pertenece al diagnóstico.")
    second = chunk("second", source_id="second-source")
    invalid = located(source, start, end, alias)
    assessor, calls = assessor_with(invalid, invalid)
    with pytest.raises(SourceAnalysisError) as caught:
        assessor.assess(request(), [source, second])
    d = caught.value.diagnostic
    assert d["attempts"] == 2 and d["errors"][0]["reason"] == reason
    assert len(d["attempt_history"]) == 2
    assert "Texto privado" not in json.dumps(d)
    assert len(calls) == 2
    assert "line_start" in json.loads(calls[1]["input"])["citation_repair"]["instruction"]


def test_location_repair_records_history_and_copies_corrected_range():
    source = chunk()
    assessor, calls = assessor_with(located(source, 3, 2), located(source, 1, 1))
    result = assessor.assess(request(), [source])
    assert result["analysis_diagnostic"]["code"] == "validated_after_repair"
    assert result["analysis_diagnostic"]["attempts"] == 2
    assert result["sufficiency"]["coverage"][0]["citations"][0]["quote"] == (
        source["quote"].splitlines(True)[0])
    assert '"quote"' not in json.dumps(
        json.loads(calls[1]["input"])["citation_repair"]["previous_selection"])


def test_located_citation_does_not_relax_allowed_evidence_use():
    source = chunk(category="historical_response", collection_id="history")
    proposed = located(source)
    proposed.supports[0].role = "antecedent"
    proposed.coverage[0].use = "verified_fact"
    assessor, _ = assessor_with(proposed, proposed)
    with pytest.raises(SourceAnalysisError) as caught:
        assessor.assess(request(allowed_collection_ids=["history"]), [source])
    assert any(e["reason"] == "incompatible_coverage_use"
               for e in caught.value.diagnostic["errors"])


@pytest.mark.parametrize("start", [0, -1, True, "2", 1.5])
def test_line_numbers_are_strict_positive_integers(start):
    with pytest.raises(ValidationError):
        PassageRange(chunk_id="C1", line_start=start, line_end=2)


def test_declaration_is_also_copied_from_selected_location():
    source = chunk(category="historical_response", collection_id="history",
                   quote="Se cotejó el acta y se comprobó la asignación.\nOtro párrafo.")
    proposed = located(source, declared_checks=[dict(
        chunk_id="C1", line_start=1, line_end=1, fact="Se comprobó la asignación.",
        basis="El acta mencionada en el oficio.")])
    proposed.supports[0].role = "antecedent"
    proposed.coverage[0].use = "attributed_content"
    assessor, _ = assessor_with(proposed)
    result = assessor.assess(request(allowed_collection_ids=["history"]), [source])
    assert any(loc["kind"] == "declaration" for loc in result["citation_locations"])
    assert result["analysis_diagnostic"]["code"] == "validated"


def test_provider_error_diagnostic_does_not_include_request_secrets():
    import httpx
    from openai import APITimeoutError

    assessor = OpenAISourceAssessor("test-not-real", "test-model")

    def parse(**kwargs):
        raise APITimeoutError(request=httpx.Request(
            "POST", "https://example.invalid/private", headers={"Authorization": "secret-value"}))

    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(SourceAnalysisError) as caught:
        assessor.assess(request(), [chunk()])
    assert caught.value.diagnostic["code"] == "provider_timeout"
    assert "secret-value" not in json.dumps(caught.value.diagnostic)
