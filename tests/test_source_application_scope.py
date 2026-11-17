"""General command scope for metadata validity; no model or external calls."""

from copy import deepcopy

import pytest

from pqrs_claro.source_assessment import OpenAISourceAssessor, _Missing
from pqrs_claro.source_sufficiency import (
    _requests_current_application,
    metadata_check_required,
)
from tests.test_normative_document_requests import norm, request, selection


@pytest.mark.parametrize("text", [
    "Comparen lo escrito. No determinen cuál se aplica hoy. Faciliten copia del archivo.",
    "Resuma el texto sin decidir qué regla está vigente.",
    "No solicito que determinen la aplicación para mi caso; describan sólo el antecedente.",
    "No pido establecer qué puedo hacer hoy. Sólo indiquen qué dice el texto.",
    "No resuelvan qué corresponde actualmente; transcriban ambos plazos.",
    "Comparen ambos textos sin establecer cuál está vigente para mi caso.",
])
def test_excluded_application_decision_is_not_an_affirmative_demand(text):
    assert not _requests_current_application({"description": text})


@pytest.mark.parametrize("text", [
    "¿Por qué no me aplica hoy el descuento?",
    "Explique por qué no se determina actualmente mi derecho.",
    "No determinen la historia; confirmen si tengo derecho hoy.",
    "No determinen cuál se aplica hoy, pero indiquen si puedo pedir la ayuda.",
    "No decidan cuál era la regla anterior y confirmen qué debo hacer hoy.",
    "No decidan cuál era la regla anterior, aclaren qué norma está vigente hoy.",
    "No determinen cuál era la regla anterior aunque necesito saber qué debo hacer.",
    "No solicito que determinen qué regía antes. Además quiero saber si puedo inscribirme.",
    "No sólo determinen qué regla rige hoy; faciliten también su copia.",
    "Determinen cuál se aplica hoy y no revisen el trámite anterior.",
    "No determinen qué aplicaba antes, certifiquen la autenticidad del archivo.",
    "Explique el texto sin resolver el caso anterior; entregue copia oficial.",
])
def test_positive_scope_and_questions_about_negative_facts_are_preserved(text):
    assert _requests_current_application({"description": text})


def _copy_comparison(description=None, *, application="not_requested", use="attributed_content"):
    first = norm(review_status="pending", validity="unknown")
    second = norm(
        chunk_id="circular-otros:1", source_id="otros", document_id="otros-doc",
        title="Circular 77 de 2024", filename="circular77.pdf", review_status="reviewed",
        validity="unknown", quote="CIRCULAR 77 DE 2024\nEl plazo descrito es de seis días.",
    )
    query = request(description=description or (
        "Comparen únicamente lo escrito en la Circular 402 de 2025 y la Circular 77 de 2024. "
        "No determinen cuál se aplica hoy. Faciliten copia íntegra de la Circular 402 de 2025."
    ))
    result = selection(first)
    result.supports.append(result.supports[0].model_copy(update={
        "chunk_id": second["chunk_id"], "role": "rule"}))
    result.coverage.append(result.coverage[0].model_copy(deep=True, update={
        "use": use,
        "citations": [result.coverage[0].citations[0].model_copy(update={
            "chunk_id": second["chunk_id"], "quote": second["quote"]})],
    }))
    result.coverage[-1].application.status = application
    return query, [first, second], result


def test_descriptive_comparison_and_copy_do_not_require_generic_authentication():
    query, sources, proposed = _copy_comparison()
    before = deepcopy((query, sources, proposed.model_dump()))
    result = OpenAISourceAssessor._materialize(proposed, query, sources)
    assert result["missing"] == []
    assert any(d["original"]["reason_code"] == "provenance" for d in result["gap_decisions"])
    assert result["sufficiency"]["copy_without_current_application"] is True
    assert result["supports"][0]["quote"] == sources[0]["quote"]
    assert any(x["reason_code"] == "document_delivery" for x in result["actions"])
    assert (query, sources, proposed.model_dump()) == before


@pytest.mark.parametrize("description", [
    "Explique qué dice la Circular 402 de 2025 y entregue copia. Determine cuál rige hoy.",
    "Faciliten copia de la Circular 402 de 2025 y expliquen por qué no me aplica hoy.",
    "Faciliten copia de la Circular 402 de 2025 y certifiquen mi derecho.",
    "Faciliten copia de la Circular 402 de 2025 y verifiquen la ejecución del trámite.",
])
def test_mislabelled_attribution_never_bypasses_positive_application_or_action(description):
    query, sources, proposed = _copy_comparison(description)
    result = OpenAISourceAssessor._materialize(proposed, query, sources)
    assert {item["source_id"] for item in sources} == {
        sid for gap in result["missing"] if gap["reason_code"] == "validity"
        for sid in gap["linked_source_ids"]}
    assert any(item["reason_code"] == "provenance" for item in result["missing"])


def test_official_copy_keeps_authentication_without_requiring_legal_effect():
    query, sources, proposed = _copy_comparison(
        "Faciliten copia oficial de la Circular 402 de 2025.")
    result = OpenAISourceAssessor._materialize(proposed, query, sources)
    target_id = sources[0]["source_id"]
    assert not any(gap["reason_code"] == "validity"
                   and target_id in gap["linked_source_ids"] for gap in result["missing"])
    assert any(gap["reason_code"] == "provenance"
               and target_id in gap["linked_source_ids"] for gap in result["missing"])
    assert result["actions"][0]["resolution"]["status"] == "open"


@pytest.mark.parametrize("application,use", [
    ("supported", "attributed_content"), ("not_requested", "rule"),
])
def test_source_actually_used_for_application_still_requires_validity(application, use):
    query, sources, proposed = _copy_comparison(application=application, use=use)
    result = OpenAISourceAssessor._materialize(proposed, query, sources)
    validity = [item for item in result["missing"] if item["reason_code"] == "validity"]
    assert [item["linked_source_ids"] for item in validity] == [["otros"]]


@pytest.mark.parametrize("state", ["supported", "unresolved"])
def test_each_source_application_status_blocks_metadata_demotion(state):
    source = {"source_id": "A", "category": "institutional_norm"}
    sufficiency = {"source_uses": {"A": ["attributed_content"]},
                   "source_applications": {"A": ["not_requested", state]},
                   "copy_without_current_application": True}
    assert metadata_check_required(source, sufficiency, "validity")


@pytest.mark.parametrize("reason,basis", [
    ("validity", "contradiction"), ("validity", "content_gap"),
    ("issued_version", "content_gap"), ("transcription", "metadata_only"),
    ("provenance", "content_gap"),
])
def test_descriptive_copy_keeps_material_gaps_and_transcription(reason, basis):
    query, sources, proposed = _copy_comparison()
    proposed.missing.append(_Missing.model_validate({
        "kind": "clarification", "description": "Comprobar el pasaje afectado.",
        "reason_code": reason, "basis": basis,
        "source_chunk_ids": [sources[0]["chunk_id"]],
        "affected_claim": "Correspondencia del pasaje con el original.",
        "why_unresolved": "El original y la transcripción no coinciden.",
    }))
    result = OpenAISourceAssessor._materialize(proposed, query, sources)
    assert any(x["description"] == "Comprobar el pasaje afectado." for x in result["missing"])
