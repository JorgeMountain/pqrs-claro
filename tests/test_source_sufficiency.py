"""Suficiencia documental atribuida, sin atajos por palabras o identidad de demo."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from pqrs_claro.models import DomainError
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection


@pytest.mark.parametrize("failure", ["unselected", "nonliteral", "unknown", "incompatible_use"])
def test_citation_contract_repairs_once_with_same_candidates(failure):
    original = source()
    good = selection()
    good.supports[0].chunk_id = "C1"
    good.coverage[0].citations[0].chunk_id = "C1"
    bad = good.model_copy(deep=True)
    if failure == "unselected":
        bad.supports = []
    elif failure == "nonliteral":
        bad.coverage[0].citations[0].quote = "Una conclusión inventada."
    elif failure == "incompatible_use":
        bad.coverage[0].use = "verified_fact"
    else:
        bad.coverage[0].citations[0].chunk_id = "C99"
    calls = []

    def parse(**kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(status="completed", output_parsed=bad if len(calls) == 1 else good)

    assessor = OpenAISourceAssessor("test-not-real", "test")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = assessor.assess(request(), [original])
    assert len(calls) == 2
    assert calls[0]["candidates"] == calls[1]["candidates"]
    assert calls[1]["citation_repair"]["errors"]
    error = calls[1]["citation_repair"]["errors"][0]
    if failure == "nonliteral":
        assert error["submitted_quote"] == "Una conclusión inventada."
        assert error["candidate_quote"] == original["quote"]
    if failure == "incompatible_use":
        assert error["chunk_id"] == "C1"
        assert error["aspect_index"] == 0
        assert error["allowed_uses"] == ["attributed_content"]
    assert result["citation_validation"]["repair_attempts"] == 1
    assert result["supports"][0]["quote"] == original["quote"]
    assert result["status"] == "references_found"


def test_persistent_invalid_citation_is_rejected_after_one_repair():
    bad = selection()
    bad.supports[0].chunk_id = "C1"
    bad.coverage[0].citations[0].chunk_id = "C1"
    bad.coverage[0].citations[0].quote = "Texto inventado."
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=bad)

    assessor = OpenAISourceAssessor("test-not-real", "test")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(DomainError, match="no coincide literalmente"):
        assessor.assess(request(), [source()])
    assert len(calls) == 2


def request(description=None, *, demo=False):
    return {
        "id": "P1",
        "case_id": "demo-ficticia" if demo else "expediente-ordinario",
        "title": "Consulta documental sobre requisitos",
        "description": description
        or (
            "Indique, según el documento conservado, los requisitos que describió "
            "el Oficio 0456-2022 para inscribirse en el periodo 2021."
        ),
        "context": {},
        "allowed_collection_ids": ["historia-ficticia"],
        "is_demo": demo,
    }


def source(**changes):
    return {
        "source_id": "respuesta-v1",
        "document_id": "respuesta",
        "chunk_id": "respuesta:1",
        "version": 1,
        "sha256": "a" * 64,
        "extraction_revision": 1,
        "title": "Oficio 0456-2022",
        "filename": "Oficio_0456-2022.pdf",
        "category": "historical_response",
        "case_id": None,
        "collection_id": "historia-ficticia",
        "document_status": "unknown",
        "review_status": "pending",
        "verification_status": "pending",
        "verification_note": "",
        "validity": "not_applicable",
        "extraction_status": "ready",
        "method": "native",
        "needs_review": False,
        "page": 1,
        "line_start": 1,
        "line_end": 3,
        "quote": (
            "OFICIO 0456-2022\n"
            "Requisitos de inscripción para el periodo 2021.\n"
            "a) Se requiere presentar el formulario y la constancia de matrícula."
        ),
        **changes,
    }


def coverage(item=None, **changes):
    item = item or source()
    return {
        "aspect": "Requisitos de inscripción descritos para el periodo 2021.",
        "claim": "El documento señala que se requiere formulario y constancia de matrícula.",
        "use": "attributed_content",
        "citations": [{"chunk_id": item["chunk_id"], "quote": item["quote"]}],
        "explanation": (
            "El pasaje identifica el oficio, el periodo y los dos requisitos pedidos. "
            "Se informa lo que expresa el documento, sin afirmar que haya sido expedido."
        ),
        **changes,
    }


def missing(reason="provenance", basis="metadata_only", **changes):
    return {
        "kind": "clarification",
        "description": "Revisar la procedencia y el contenido del archivo conservado.",
        "reason_code": reason,
        "source_chunk_ids": ["respuesta:1"],
        "affected_claim": "El documento describe requisitos de inscripción para 2021.",
        "why_unresolved": "El catálogo conserva review_status pending.",
        "basis": basis,
        **changes,
    }


def selection(sources=None, **changes):
    sources = sources or [source()]
    return _SourceSelection.model_validate(
        {
            "status": "references_found",
            "summary": "Se localizó el contenido documental pedido con atribución al antecedente.",
            "supports": [
                {
                    "chunk_id": item["chunk_id"],
                    "role": "antecedent",
                    "reason": "Contiene el pasaje pertinente al documento y periodo consultados.",
                }
                for item in sources
            ],
            "missing": [],
            "warnings": [],
            "coverage_complete": True,
            "coverage": [coverage(item) for item in sources],
            **changes,
        }
    )


def materialize(inquiry=None, sources=None, proposed=None):
    sources = sources or [source()]
    return OpenAISourceAssessor._materialize(
        proposed or selection(sources), inquiry or request(), sources
    )


def assert_blocked_or_rejected(inquiry, sources, proposed):
    try:
        result = materialize(inquiry, sources, proposed)
    except DomainError:
        return None
    assert result["status"] in {"needs_evidence", "no_matches"}
    assert result["missing"], "La etiqueta attributed_content no debe ocultar una brecha."
    assert all(item["resolution"]["status"] == "open" for item in result["missing"])
    return result


@pytest.mark.parametrize("demo", [False, True], ids=["ordinary", "demo"])
@pytest.mark.parametrize(
    "description",
    [
        None,
        "¿Qué dice el oficio 0456-2022 sobre los requisitos de inscripción de 2021?",
        "Resuma los requisitos de inscripción de 2021 que figuran en el documento 0456-2022.",
    ],
)
def test_complete_attributed_content_advances_without_promoting_metadata(description, demo):
    item = source()
    before = deepcopy(item)
    result = materialize(request(description, demo=demo), [item])
    assert result["status"] == "references_found"
    assert result["missing"] == []
    assert result["evidence_states"] == ["support_found"]
    assert result["supports"][0]["quote"] == before["quote"]
    assert result["supports"][0]["role"] == "antecedent"
    for field in ("document_status", "review_status", "verification_status", "sha256"):
        assert result["supports"][0][field] == before[field]
    assert result["verifications"] == []
    assert result["warnings"], "Los límites de atribución deben seguir visibles."
    assert item == before


@pytest.mark.parametrize("reason", ["provenance", "issued_version"])
def test_only_explicit_metadata_only_checks_can_be_removed_for_attributed_content(reason):
    proposed = selection(missing=[missing(reason=reason)], status="needs_evidence")
    result = materialize(proposed=proposed)
    assert result["missing"] == []
    assert result["status"] == "references_found"
    assert result["supports"][0]["document_status"] == "unknown"


@pytest.mark.parametrize("basis", ["unspecified", "content_gap", "contradiction"])
def test_non_metadata_pending_is_preserved_even_when_reason_is_provenance(basis):
    pending = missing(
        basis=basis,
        description="Distinguir si el pasaje se refiere a Luis Mora o a Lucas Mora.",
        affected_claim="La identidad de la persona a quien corresponde el requisito.",
        why_unresolved="El encabezado y el cuerpo atribuyen el requisito a personas diferentes.",
    )
    result = materialize(proposed=selection(missing=[pending]))
    assert result["status"] == "needs_evidence"
    assert any(item["description"] == pending["description"] for item in result["missing"])


@pytest.mark.parametrize("demo", [False, True], ids=["ordinary", "demo-with-trigger-phrase"])
@pytest.mark.parametrize(
    "description,pending",
    [
        (
            "Transcriba el literal b del Oficio 0456-2022.",
            missing(
                "specific_gap",
                "content_gap",
                description="Localizar el literal b; el pasaje solo incluye el literal a.",
                affected_claim="Contenido del literal b.",
                why_unresolved="No se conserva el literal pedido entre los pasajes seleccionados.",
            ),
        ),
        (
            "Identifique a cuál de los dos funcionarios llamados Luis Mora se refiere el oficio.",
            missing(
                "source_identity",
                "content_gap",
                description="Precisar cuál funcionario Luis Mora aparece en el documento.",
                affected_claim="Identidad del funcionario citado.",
                why_unresolved="El nombre corresponde a dos funcionarios y no se indica cargo.",
            ),
        ),
        (
            "Explique el requisito de 2021 ante los dos pasajes discordantes del oficio.",
            missing(
                "fact_confirmation",
                "contradiction",
                description="Resolver si el formulario es obligatorio u opcional.",
                affected_claim="Carácter obligatorio del formulario.",
                why_unresolved="Los pasajes dan respuestas incompatibles para el mismo periodo.",
            ),
        ),
        (
            "Confirme quién ocupa actualmente la plaza mencionada en el oficio.",
            missing(
                "fact_confirmation",
                "content_gap",
                kind="fact",
                description="Identificar a la persona que ocupa la plaza actualmente.",
                affected_claim="Titular actual de la plaza.",
                why_unresolved="El antecedente solo describe 2021; no informa la situación actual.",
            ),
        ),
    ],
)
def test_concrete_gaps_survive_complete_coverage_label_and_demo_words(description, pending, demo):
    if demo:
        description = "Para esta demo, indique qué dice el oficio. " + description
    result = assert_blocked_or_rejected(
        request(description, demo=demo), [source()], selection(missing=[pending])
    )
    if result is not None:
        assert any(item["description"] == pending["description"] for item in result["missing"])


@pytest.mark.parametrize("demo", [False, True])
def test_mention_of_requested_acta_never_substitutes_its_file(demo):
    description = "Entregue copia del acta 17 del comité mencionada en el oficio 0456-2022."
    if demo:
        description = "Explique qué dice el oficio para esta demo. " + description
    item = source(quote="OFICIO 0456-2022\nEl comité examinó el acta 17 de 2021.")
    result = assert_blocked_or_rejected(
        request(description, demo=demo),
        [item],
        selection([item], coverage=[coverage(item, aspect="Archivo del acta 17.")]),
    )
    if result is not None:
        assert all(support["role"] != "document" for support in result["supports"])


@pytest.mark.parametrize("extraction_status", ["error", "failed", "pending", "unsupported"])
def test_unreadable_source_cannot_advance_from_a_complete_coverage_label(extraction_status):
    item = source(extraction_status=extraction_status)
    result = assert_blocked_or_rejected(request(), [item], selection([item]))
    if result is not None:
        assert "analysis_error" in result["evidence_states"]


@pytest.mark.parametrize(
    "description",
    [
        "Confirme quién ocupa actualmente la plaza, tomando como referencia el oficio 0456-2022.",
        "Indique qué dice el oficio y confirme quién ocupa actualmente la plaza.",
        "Entregue la versión oficial expedida del Oficio 0456-2022.",
        "Para una demo, indique qué dice el oficio y entregue su versión oficial firmada.",
    ],
)
def test_wrong_attributed_content_label_does_not_close_current_fact_or_official_demand(description):
    assert_blocked_or_rejected(request(description), [source()], selection())


def test_mixed_uses_for_one_source_keep_its_fact_verification_controls():
    item = source()
    proposed = selection(
        coverage=[
            coverage(item),
            coverage(
                item,
                aspect="Comprobación del cumplimiento del requisito.",
                claim="La persona cumplió efectivamente el requisito.",
                use="verified_fact",
            ),
        ]
    )
    assert_blocked_or_rejected(request(), [item], proposed)


def test_rule_coverage_does_not_remove_unknown_validity_or_pending_review():
    item = source(category="institutional_norm", validity="unknown")
    proposed = selection(
        [item],
        supports=[
            {"chunk_id": item["chunk_id"], "role": "rule", "reason": "Regula la inscripción."}
        ],
        coverage=[coverage(item, use="rule")],
    )
    result = materialize(request("Indique los requisitos normativos aplicables."), [item], proposed)
    assert result["status"] == "needs_evidence"
    assert any(item["reason_code"] == "validity" for item in result["missing"])


@pytest.mark.parametrize(
    "coverage_changes",
    [
        {
            "citations": [
                {"chunk_id": "respuesta:1", "quote": "Un requisito que no aparece en el original."}
            ]
        },
        {"citations": [{"chunk_id": "no-seleccionado:1", "quote": "No elegido como soporte."}]},
    ],
)
def test_complete_coverage_requires_literal_citations_from_selected_supports(coverage_changes):
    extra = source(
        chunk_id="no-seleccionado:1", source_id="otro-v1", quote="No elegido como soporte."
    )
    proposed = selection(coverage=[coverage(**coverage_changes)])
    assert_blocked_or_rejected(request(), [source(), extra], proposed)


def test_coverage_without_citations_is_rejected_by_the_input_contract():
    with pytest.raises(ValidationError):
        selection(coverage=[coverage(citations=[])])


@pytest.mark.parametrize(
    "changes",
    [
        {"coverage_complete": False, "coverage": []},
        {"coverage_complete": True, "coverage": []},
    ],
)
def test_incomplete_or_missing_coverage_never_implicitly_clears_metadata_checks(changes):
    assert_blocked_or_rejected(request(), [source()], selection(**changes))


def test_legacy_selection_without_coverage_keeps_existing_controls():
    raw = selection().model_dump()
    raw.pop("coverage")
    raw.pop("coverage_complete")
    proposed = _SourceSelection.model_validate(raw)
    result = materialize(proposed=proposed)
    assert result["status"] == "needs_evidence"
    assert {item["reason_code"] for item in result["missing"]} >= {"provenance", "issued_version"}


def test_metadata_only_label_does_not_remove_unrelated_fact_gap():
    pending = missing(
        reason="fact_confirmation",
        description="Precisar si la persona cumplió el requisito en el periodo consultado.",
        affected_claim="Cumplimiento del requisito por una persona concreta.",
        why_unresolved="El pasaje solo describe la regla, no el cumplimiento particular.",
    )
    result = materialize(proposed=selection(missing=[pending]))
    assert result["status"] == "needs_evidence"
    assert any(item["description"] == pending["description"] for item in result["missing"])


def test_coverage_for_one_source_does_not_clear_metadata_check_of_another_candidate():
    extra = source(
        chunk_id="otro:1",
        source_id="otro-v1",
        document_id="otro",
        title="Otro documento",
        filename="otro.pdf",
    )
    pending = missing(source_chunk_ids=[extra["chunk_id"]])
    result = materialize(sources=[source(), extra], proposed=selection(missing=[pending]))
    assert result["status"] == "needs_evidence"
    assert any(extra["source_id"] in item["linked_source_ids"] for item in result["missing"])


def test_persistent_incompatible_coverage_use_is_rejected_after_one_repair():
    bad = selection()
    bad.supports[0].chunk_id = "C1"
    bad.coverage[0].citations[0].chunk_id = "C1"
    bad.coverage[0].use = "verified_fact"
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=bad)

    assessor = OpenAISourceAssessor("test-not-real", "test")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(DomainError, match="no permite el uso"):
        assessor.assess(request(), [source()])
    assert len(calls) == 2


def test_document_absence_is_repaired_as_gap_not_delivery_evidence():
    inquiry = request("Entregue copia del acta 17 mencionada en el oficio.")
    bad = selection()
    bad.supports[0].chunk_id = "C1"
    bad.coverage[0].citations[0].chunk_id = "C1"
    bad.coverage[0].use = "document_delivery"
    bad.coverage[0].claim = "No se localizó el acta solicitada."
    corrected = bad.model_copy(deep=True)
    corrected.coverage = []
    corrected.coverage_complete = False
    corrected.status = "needs_evidence"
    from pqrs_claro.source_assessment import _Missing

    corrected.missing = [
        _Missing.model_validate(
            missing(
                "document_search",
                "unavailable_document",
                kind="document",
                description="Localizar el acta 17 solicitada.",
                affected_claim="Disponibilidad de la copia del acta 17.",
                why_unresolved="Los candidatos contienen un oficio, no el acta pedida.",
                source_chunk_ids=["C1"],
            )
        )
    ]
    calls = []

    def parse(**kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(
            status="completed", output_parsed=bad if len(calls) == 1 else corrected
        )

    assessor = OpenAISourceAssessor("test-not-real", "test")
    assessor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = assessor.assess(inquiry, [source()])
    assert len(calls) == 2
    assert result["status"] == "needs_evidence"
    assert result["supports"][0]["role"] == "antecedent"
    assert any(
        gap["affected_claim"] == "Disponibilidad de la copia del acta 17."
        for gap in result["missing"]
    )
