"""Catalog validity is independent of attributing literal text to an old regulation."""

import pytest

from pqrs_claro.source_context import build_source_requests
from pqrs_claro.source_sufficiency import _normative_description_only, metadata_check_required

INTRO = "Consulta informativa sobre el contenido del Estatuto de Estímulos."
DISCLAIMER = "No solicito certificar su vigencia hoy."
QUESTION = "¿Cuántos jurados deliberaban y quién levantaba el acta?"


def request_with_scope(introduction, target, sibling="¿Qué requisitos tenía el archivo?"):
    lines = [introduction, target, sibling]
    requests = [
        {"id": f"P{n - 1}", "label": str(n - 1), "title": line, "description": line,
         "parent_id": None, "source_refs": [{"page": 1, "line_start": n, "line_end": n,
                                            "quote": line}]}
        for n, line in enumerate(lines[1:], 2)
    ]
    case = {
        "id": "consulta-estimulos",
        "identification": {"subject": "Estatuto de Estímulos", "requests": requests},
        "pages": [{"number": 1, "text": "\n".join(lines), "method": "native",
                   "needs_review": False}],
    }
    return build_source_requests(case)[0]


@pytest.mark.parametrize("scope", [DISCLAIMER, "Sin certificación de vigencia actual.", ""])
def test_informational_original_scope_waives_only_catalog_validity(scope):
    request = request_with_scope(f"{INTRO} {scope}", QUESTION, "¿Esa norma rige actualmente?")
    assert _normative_description_only(request)
    source = {"source_id": "estatuto", "category": "institutional_norm"}
    coverage = {"source_uses": {"estatuto": ["attributed_content"]},
                "normative_description_only": True, "attribution_only_allowed": True}
    assert not metadata_check_required(source, coverage, "validity")
    assert metadata_check_required(source, coverage, "transcription")
    assert metadata_check_required(source, coverage, "source_identity")
    assert metadata_check_required(source, {
        **coverage, "source_applications": {"estatuto": ["unresolved"]},
    }, "validity")


@pytest.mark.parametrize("target", [
    "¿La norma continúa en vigor?",
    "¿Qué norma se aplicaba a mi reclamación en ese semestre?",
    "¿Tengo derecho a la bonificación?",
    "Resuelvan mi admisión al programa.",
    "Certifiquen la autenticidad de la resolución.",
    "¿Cuál de ambos acuerdos prevalece si prevén requisitos distintos?",
])
def test_individual_decision_or_legal_effect_prevails_over_documentary_introduction(target):
    assert not _normative_description_only(request_with_scope(f"{INTRO} {DISCLAIMER}", target))


def test_independent_or_incomplete_scope_cannot_waive_validity():
    assert not _normative_description_only(
        request_with_scope("Peticiones sobre estímulos.", QUESTION, f"{INTRO} {DISCLAIMER}")
    )
    only_second = "Para el segundo punto, la consulta es sobre el contenido del Estatuto."
    assert not _normative_description_only(request_with_scope(only_second, QUESTION))
    request = request_with_scope(f"{INTRO} {DISCLAIMER}", QUESTION)
    request["context"]["document_context"]["truncated"] = True
    assert not _normative_description_only(request)


@pytest.mark.parametrize("change", ["wrong_target", "unaligned_target", "invalid_range"])
def test_inherited_scope_belongs_to_the_current_question(change):
    request = request_with_scope(INTRO, QUESTION)
    context = request["context"]
    if change == "wrong_target":
        context["target_request_id"] = "P2"
    elif change == "unaligned_target":
        context["document_context"]["unverified_request_reference_count"] = 1
    else:
        context["document_context"]["question_ranges"] = [{"request_id": request["id"]}]
    assert not _normative_description_only(request)


def test_regular_as_a_procedure_adjective_does_not_ask_to_apply_a_rule():
    req = request_with_scope(INTRO, "¿Quién tramitaba una candidatura regular y qué se adjuntaba?")
    assert _normative_description_only(req)


@pytest.mark.parametrize("mandate", ["parent", "shared"])
def test_separate_positive_mandate_governing_the_question_preserves_validity(mandate):
    extra = "Además, determinen si la regla aplica al caso que planteo."
    intro = f"{INTRO} {DISCLAIMER}"
    request = request_with_scope(f"{intro} {extra}" if mandate == "shared" else intro, QUESTION)
    if mandate == "parent":
        request["context"]["ancestors"] = [{"description": extra}]
    assert not _normative_description_only(request)
