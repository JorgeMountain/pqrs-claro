"""Certified copies retain authentication without inventing legal-effect questions.

New fictional originals in temporary libraries, with deterministic reader selections.
No network calls or live cases are involved.
"""

from copy import deepcopy

import pytest

from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.request_requirements import build_requirements
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.source_library import SourceLibrary

DOCUMENTS = [
    ("Circular 147 de 2024", "CIRCULAR 147 DE 2024", "institutional_norm",
     "Préstamo de juegos de mesa. Los préstamos se registran en recepción."),
    ("Resolución 965 de 2022", "RESOLUCIÓN 965 DE 2022", "institutional_norm",
     "Acceso al vivero municipal. Las visitas requieren reserva de grupo."),
    ("Decreto 286 de 2021", "DECRETO 286 DE 2021", "national_norm",
     "Uso del archivo de mapas. La reproducción se solicita mediante formulario."),
]


def new_document(tmp_path, document):
    name, header, category, body = document
    library = SourceLibrary(tmp_path / "new-certified-copy-library", PDFExtractor())
    library.save_collection({"id": "certified-copy-sources", "title": "Corpus ficticio nuevo"})
    library.link_collections("certified-copy-case", ["certified-copy-sources"])
    saved = library.add(
        name + ".txt", (header + "\n" + body).encode(), title=name,
        category=category, origin="Fuente enteramente ficticia para pruebas de software",
        collection_id="certified-copy-sources",
    )
    _, chunks = library.snapshot("certified-copy-case")
    source = next(item for item in chunks if item["source_id"] == saved["id"])
    assert source["validity"] == "unknown"
    return name, source


@pytest.fixture(params=DOCUMENTS, ids=[row[0] for row in DOCUMENTS])
def normative_document(tmp_path, request):
    return new_document(tmp_path, request.param)


def question(name, suffix="", *, certified=True):
    qualifier = " certificada" if certified else ""
    return {
        "id": "CERT-P1", "case_id": "certified-copy-case", "title": "Consulta sobre una copia",
        "description": f"Adjunte copia{qualifier} de {name}. {suffix}".strip(),
        "allowed_collection_ids": ["certified-copy-sources"], "context": {},
    }


def selection(source, request, *, application="not_requested", legal_use=False,
              missing=()):
    uncertainty = []
    if application == "unresolved":
        uncertainty = [{
            "requirement_ids": [build_requirements(request)[0]["id"]],
            "coverage_indexes": [0], "basis": "content_gap",
            "affected_claim": (
                "La norma rige para el periodo consultado."
                if legal_use else "El ejemplar corresponde a una copia certificada auténtica."
            ),
            "why_unresolved": (
                "No consta si la norma fue derogada o modificada en el periodo consultado."
                if legal_use else "El archivo no contiene constancia del cotejo de autenticidad."
            ),
            "required_check": (
                "Cotejar la vigencia y aplicación de la norma en el periodo consultado."
                if legal_use else
                "Cotejar el ejemplar y la certificación con el registro del archivo."
            ),
        }]
    return _SourceSelection.model_validate({
        "status": "references_found", "summary": "El ejemplar solicitado está localizado.",
        "supports": [{"chunk_id": source["chunk_id"], "role": "document",
                      "reason": "El encabezado identifica el ejemplar solicitado."}],
        "missing": list(missing), "warnings": [], "coverage_complete": True,
        "coverage": [{
            "aspect": "Contenido normativo aplicable" if legal_use else "Copia del archivo",
            "claim": ("La norma regula el procedimiento consultado." if legal_use
                      else "Se conserva el archivo cuya copia se solicita."),
            "use": "rule" if legal_use else "document_delivery",
            "application": {
                "status": application,
                "explanation": (
                    "Se evalúa la aplicación jurídica de la norma al supuesto consultado."
                    if legal_use else
                    "Se evalúa la autenticidad de la copia, no su vigencia jurídica."
                ),
                "uncertainty_indexes": [0] if uncertainty else [],
            },
            "citations": [{"chunk_id": source["chunk_id"], "quote": source["quote"]}],
            "explanation": "La identidad del archivo no acredita autenticidad ni envío.",
        }],
        "uncertainties": uncertainty,
    })


def materialize(name, source, suffix="", *, request=None, **kwargs):
    request = request or question(name, suffix)
    return OpenAISourceAssessor._materialize(
        selection(source, request, **kwargs), request, [source])


def validity_checks(result):
    return [gap for gap in result["missing"] if gap["reason_code"] == "validity"]


def assert_authentication_and_delivery_remain(result, source):
    assert result["supports"][0]["quote"] == source["quote"]
    assert result["supports"][0]["sha256"] == source["sha256"]
    assert any(gap["reason_code"] in {"provenance", "issued_version"}
               and gap["resolution"]["status"] == "open" for gap in result["missing"])
    delivery = [item for item in result["actions"] if item["reason_code"] == "document_delivery"]
    assert len(delivery) == 1 and delivery[0]["resolution"]["status"] == "open"
    assert not delivery[0]["blocks_approval"]
    assert result["verifications"] == []


def test_certified_copy_does_not_request_current_legal_effect(normative_document):
    name, source = normative_document
    before = deepcopy(source)
    result = materialize(name, source)
    assert validity_checks(result) == []
    assert_authentication_and_delivery_remain(result, source)
    assert any(item["original"]["reason_code"] == "validity"
               for item in result["gap_decisions"])
    assert source == before


@pytest.mark.parametrize("suffix", [
    "Indique si la norma está vigente.",
    "Confirme si la norma fue derogada.",
    "Explique si la norma sigue aplicando.",
    "Indique si sus reglas aplican para mi caso.",
    "Determine si la norma regía en el año 2023.",
    "Confirme si la norma está en vigor.",
    "Explique si la norma está suspendida.",
    "Indique si la norma es válida.",
    "Informe si la circular sigue surtiendo efectos.",
    "No requiero certificación, pero sí confirme la vigencia de la norma.",
])
def test_explicit_legal_effect_is_kept_even_if_reader_labels_it_as_copy(
    normative_document, suffix,
):
    name, source = normative_document
    result = materialize(name, source, suffix)
    assert validity_checks(result), "La etiqueta del lector no puede borrar la pregunta jurídica."
    assert result["supports"]
    assert all(gap["resolution"]["status"] == "open" for gap in validity_checks(result))


@pytest.mark.parametrize("suffix", [
    "No determinen cuál se aplica hoy.",
    "No solicito determinar si la norma está vigente; solo necesito la copia certificada.",
])
def test_explicitly_excluded_legal_decision_does_not_add_validity(normative_document, suffix):
    name, source = normative_document
    result = materialize(name, source, suffix)
    assert validity_checks(result) == []
    assert_authentication_and_delivery_remain(result, source)


@pytest.mark.parametrize("scope", ["parent", "global", "sibling"])
def test_legal_scope_uses_parent_and_global_instruction_but_not_sibling(
    normative_document, scope,
):
    name, source = normative_document
    request = question(name)
    if scope == "parent":
        request["context"] = {"ancestors": [{
            "id": "parent", "description": "Confirme la vigencia de cada norma cuya copia se pide.",
        }]}
    else:
        intro = ("Confirme la vigencia de cada norma cuya copia se pide abajo."
                 if scope == "global" else "Peticiones documentales independientes.")
        request["context"] = {"document_context": {
            "origin": "original_petition", "truncated": False,
            "excerpts": [{
                "page": 1, "line_start": 1, "line_end": 3,
                "quote": intro + "\n" + request["description"]
                + "\nIndique si otra norma sigue vigente.",
            }],
            "question_ranges": [
                {"request_id": "CERT-P1", "page": 1, "line_start": 2, "line_end": 2},
                {"request_id": "CERT-P2", "page": 1, "line_start": 3, "line_end": 3},
            ],
        }}
    result = materialize(name, source, request=request)
    assert bool(validity_checks(result)) is (scope != "sibling")
    assert_authentication_and_delivery_remain(result, source)


@pytest.mark.parametrize("context", [
    {"ancestors": [{"id": "parent", "description": (
        "Todas las copias deben ser certificadas; confirme si la norma está vigente.")}]},
    {"truncated": True},
    {"document_context": {"truncated": True, "excerpts": []}},
])
def test_plain_copy_cannot_override_global_legal_scope_or_incomplete_context(
    normative_document, context,
):
    name, source = normative_document
    request = question(name)
    request["description"] = f"Adjunte copia de {name}."
    request["context"] = context
    result = materialize(name, source, request=request)
    assert result["sufficiency"]["copy_without_legal_application"] is False
    assert validity_checks(result)
    assert result["actions"][0]["resolution"]["status"] == "open"


@pytest.mark.parametrize("application", ["supported", "unresolved"])
def test_authentication_application_label_is_not_a_legal_effect_check(
    normative_document, application,
):
    name, source = normative_document
    result = materialize(name, source, application=application)
    assert validity_checks(result) == []
    assert_authentication_and_delivery_remain(result, source)
    if application == "unresolved":
        assert any(gap["reason_code"] == "applicability" and gap["basis"] == "content_gap"
                   for gap in result["missing"])


@pytest.mark.parametrize("application", ["supported", "unresolved"])
def test_legal_application_coverage_keeps_validity(normative_document, application):
    name, source = normative_document
    result = materialize(
        name, source, "Explique cómo se aplica la norma a la solicitud de acceso.",
        application=application, legal_use=True,
    )
    assert validity_checks(result)
    assert_authentication_and_delivery_remain(result, source)
    if application == "unresolved":
        assert any(gap["reason_code"] == "applicability" and gap["basis"] == "content_gap"
                   for gap in result["missing"])


@pytest.mark.parametrize("basis", ["content_gap", "contradiction"])
def test_material_validity_gap_is_never_waived(tmp_path, basis):
    name, source = new_document(tmp_path, DOCUMENTS[0])
    gap = {
        "kind": "norm", "reason_code": "validity", "basis": basis,
        "source_chunk_ids": [source["chunk_id"]],
        "description": "Cotejar el alcance de la derogación parcial señalada en el registro.",
        "affected_claim": "El régimen invocado está vigente para el periodo consultado.",
        "why_unresolved": "Existe una diferencia entre el texto y el registro de derogación.",
    }
    result = materialize(name, source, missing=[gap])
    assert any(item["description"] == gap["description"]
               and item["basis"] == basis and item["blocks_approval"]
               for item in validity_checks(result))
    assert_authentication_and_delivery_remain(result, source)
