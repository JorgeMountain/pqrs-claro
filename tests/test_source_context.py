"""Contexto acotado, pertenencia al escrito y paso intacto por LangGraph/HTTP."""

from copy import deepcopy

import pymupdf
import pytest
from fastapi.testclient import TestClient
from test_source_service_api import (
    FakeSourceAssessor,
    make_case,
    start_search,
    upload_source,
    wait_search,
)

from pqrs_claro import source_context, source_service
from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError, Identification, Request, SourceRef, source_quote
from pqrs_claro.source_context import build_source_requests
from pqrs_claro.source_library import digest


def item(identifier, label, description, parent_id=None):
    return {"id": identifier, "label": label, "title": f"Solicitud {label}",
            "description": description, "parent_id": parent_id,
            "source_refs": [{"page": 1, "line_start": 1, "line_end": 1,
                             "quote": description}]}


@pytest.fixture
def hierarchical_case():
    return {"id": "case-context", "allowed_collection_ids": ["archive-a"],
            "identification": {"subject": "Asignación docente de la asignatura ficticia",
                               "document_date": "2026-01-01", "requests": [
        item("P1", "PRIMERO", "Atender las peticiones Cuarta, Quinta y Sexta."),
        item("P2", "CUARTO", "Solicita a la profesora Elena Lagos aclarar su asignación docente."),
        item("P3", "1", "La profesora Elena Lagos debe responder sobre el semestre 2015-1.", "P2"),
        item("P4", "1(a)", "¿Figuró usted como titular en ese semestre?", "P3"),
        item("P5", "2", "Solicita anexar los siguientes documentos.", "P2"),
        item("P6", "2(a)", "Copia del Plan de Trabajo de 2015-1.", "P5"),
        item("P7", "2(b)", "Copia del acta de aprobación 150.", "P5"),
        item("P8", "QUINTO", "Entregar documentos de respaldo de la Cuarta petición."),
        item("P9", "SEXTO", "Certificar la autenticidad de los documentos del numeral CUARTO."),
        item("P10", "SÉPTIMO", "Revisar las respuestas a la Cuarta petición."),
        item("P11", "OCTAVO", "Firmar conforme al artículo cuarto de la norma citada."),
    ]}}


def indexed(case):
    return {r["id"]: r for r in build_source_requests(case)}


def test_child_gets_named_ancestors_without_expanding_its_atomic_question(hierarchical_case):
    before = deepcopy(hierarchical_case)
    request = indexed(hierarchical_case)["P4"]
    original = hierarchical_case["identification"]["requests"][3]
    assert all(request[key] == value for key, value in original.items())
    assert [r["id"] for r in request["context"]["ancestors"]] == ["P3", "P2"]
    assert "Elena Lagos" in request["retrieval_context"]
    assert "2015-1" in request["retrieval_context"]
    assert request["context"]["target_request_id"] == "P4"
    assert request["context"]["children"] == request["context"]["referenced_requests"] == []
    assert "acta de aprobación" not in request["retrieval_context"]
    assert "missing" not in request and "supports" not in request
    request["allowed_collection_ids"].append("not-authorized")
    request["context"]["ancestors"][0]["description"] = "edited only in returned context"
    assert hierarchical_case == before


def test_parent_includes_its_actual_list_and_keeps_original_citations(hierarchical_case):
    request = indexed(hierarchical_case)["P5"]
    assert [r["id"] for r in request["context"]["children"]] == ["P6", "P7"]
    assert request["description"] == "Solicita anexar los siguientes documentos."
    assert request["context"]["children"][0]["source_refs"][0]["quote"] == (
        "Copia del Plan de Trabajo de 2015-1."
    )
    assert request["context"]["origin"] == "same_petition"
    assert request["context"]["truncated"] is False


def test_references_resolve_confirmed_labels_not_request_id_numbers(hierarchical_case):
    requests = indexed(hierarchical_case)
    targets = requests["P1"]["context"]["referenced_requests"]
    assert [r["id"] for r in targets[:3]] == ["P2", "P8", "P9"]
    assert {r["id"] for r in targets} == {"P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"}
    assert requests["P10"]["context"]["referenced_requests"][0]["id"] == "P2"
    assert requests["P11"]["context"]["referenced_requests"] == []
    assert requests["P11"]["context"]["unresolved_references"] == []


@pytest.mark.parametrize("description", [
    "Revisar la Cuarta petición.", "Consultar el numeral CUARTO.",
    "Atender los apartados cuarto, quinto y sexto.", "Responder las peticiones 4, 5 y 6.",
])
def test_reference_word_order_plural_and_numbers(hierarchical_case, description):
    request = hierarchical_case["identification"]["requests"][0]
    request["description"] = description
    request["source_refs"] = []
    context = indexed(hierarchical_case)["P1"]["context"]
    assert context["referenced_requests"][0]["id"] == "P2"
    assert context["unresolved_references"] == []


def test_unresolved_or_ambiguous_reference_does_not_guess_or_create_missing(hierarchical_case):
    hierarchical_case["identification"]["requests"].append(item("P12", "CUARTO", "Otro apartado."))
    hierarchical_case["identification"]["requests"][0] = item(
        "P1", "PRIMERO", "Consultar la petición cuarta y la novena petición."
    )
    request = indexed(hierarchical_case)["P1"]
    assert request["context"]["referenced_requests"] == []
    assert request["context"]["unresolved_references"] == [
        {"label_number": "4", "reason": "ambiguous", "candidate_request_ids": ["P2", "P12"]},
        {"label_number": "9", "reason": "not_identified", "candidate_request_ids": []},
    ]
    assert "missing" not in request


def test_context_is_bounded_and_omissions_are_visible(hierarchical_case, monkeypatch):
    monkeypatch.setattr(source_context, "MAX_CONTEXT_REQUESTS", 2)
    request = indexed(hierarchical_case)["P1"]
    assert len(request["context"]["referenced_requests"]) == 2
    assert request["context"]["truncated"] is True
    assert "P9" in request["context"]["omitted_request_ids"]
    assert "missing" not in request
    assert len(request["retrieval_context"]) <= 10000


def test_back_reference_adds_preceding_question_section_without_inventing_parentage():
    case = {"id": "case-context", "identification": {"requests": [
        item("P1", "CUARTO", "La profesora Elena Lagos responde la siguiente pregunta."),
        item("P2", "1", "¿Impartió la asignatura durante 2015-1?", "P1"),
        item("P3", "QUINTO", "Solicita las respuestas a las preguntas formuladas con respaldo."),
    ]}}
    current = indexed(case)["P3"]
    assert current["parent_id"] is None
    assert current["context"]["ancestors"] == current["context"]["referenced_requests"] == []
    assert current["context"]["preceding_section_basis"] == "document_order_for_back_reference"
    assert [r["id"] for r in current["context"]["preceding_section"]] == ["P1", "P2"]
    assert "2015-1" in current["retrieval_context"]


def test_back_reference_uses_original_quote_and_does_not_skip_intervening_sections():
    case = {"id": "case-context", "identification": {"requests": [
        item("P1", "CUARTO", "Preguntas a la profesora Elena Lagos."),
        item("P2", "1", "¿Impartió la asignatura durante 2015-1?", "P1"),
        item("P3", "QUINTO", "Pide entregar la respuesta y sus soportes."),
    ]}}
    case["identification"]["requests"][2]["source_refs"][0]["quote"] = (
        "Solicita respaldo de las preguntas anteriormente formuladas."
    )
    assert indexed(case)["P3"]["context"]["preceding_section"][0]["id"] == "P1"
    case["identification"]["requests"].insert(2, item("P4", "SEXTO", "Actualizar la dirección."))
    current = indexed(case)["P3"]
    assert current["context"]["preceding_section"] == []
    assert current["context"]["referenced_requests"] == []
    assert current["parent_id"] is None


@pytest.mark.parametrize("defect", ["missing_parent", "cycle", "duplicate"])
def test_malformed_hierarchy_is_rejected_without_guessing(hierarchical_case, defect):
    requests = hierarchical_case["identification"]["requests"]
    if defect == "missing_parent":
        requests[3]["parent_id"] = "P999"
    elif defect == "cycle":
        requests[1]["parent_id"] = "P4"
    else:
        requests.append(deepcopy(requests[0]))
    with pytest.raises(DomainError):
        build_source_requests(hierarchical_case)


class ContextIdentifier:
    def identify(self, pages):
        return Identification(subject="Docencia ficticia", requests=[
            Request(id="P1", label="CUARTO", title="Profesora y semestre",
                    description="Solicita a Elena Lagos responder sobre docencia en 2015-1.",
                    source_refs=[SourceRef(page=1, line_start=1, line_end=1,
                                           quote=source_quote(pages, 1, 1, 1))]),
            Request(id="P2", label="1(a)", parent_id="P1", title="Titularidad docente",
                    description="Informar si usted era titular de la asignatura.",
                    source_refs=[SourceRef(page=1, line_start=1, line_end=1,
                                           quote=source_quote(pages, 1, 1, 1))]),
        ])


class ContextAssessor(FakeSourceAssessor):
    def __init__(self):
        super().__init__()
        self.requests = []

    def assess(self, request, candidates):
        self.requests.append(deepcopy(request))
        return super().assess(request, candidates)


def test_http_search_passes_same_context_to_retrieval_and_assessment_and_invalidates_old_run(
    tmp_path, monkeypatch
):
    assessor = ContextAssessor()
    retrieved = []

    def recording_retrieve(request, chunks, **_options):
        retrieved.append(deepcopy(request))
        # This double tests the service/graph contract, independently of ranking.
        return chunks[:1]

    monkeypatch.setattr(source_service, "retrieve", recording_retrieve)
    settings = Settings(data_dir=tmp_path / "data", api_key="test-not-real", model="test-model")
    app = create_app(settings, extractor=PDFExtractor(), identifier=ContextIdentifier(),
                     source_assessor=assessor)
    with TestClient(app) as client:
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((50, 80), "Solicito a Elena Lagos informar si fue docente en 2015-1.")
            pdf_bytes = document.tobytes()
        case = make_case(client, pdf_bytes)
        original_identification = deepcopy(case["identification"])
        assert upload_source(client).status_code == 201
        before, sources, _, fingerprint = app.state.sources.inputs(case["id"])
        previous_fingerprint = digest({
            "identification": before["identification"], "sources": sources,
            "model": settings.model, "analysis_version": 7,
            "collections": before["allowed_collection_ids"],
        })
        assert fingerprint != previous_fingerprint
        start_search(client, case)
        current = wait_search(app, client, case["id"])
        assert current["status"] == "ready", current
        assert retrieved == assessor.requests
        child = next(r for r in retrieved if r["id"] == "P2")
        assert child["description"] == "Informar si usted era titular de la asignatura."
        assert child["context"]["ancestors"][0]["id"] == "P1"
        assert "Elena Lagos" in child["retrieval_context"]
        persisted = client.get(f"/api/cases/{case['id']}").json()
        assert persisted["identification"] == original_identification
        # A stored v7 run remains readable but cannot reuse old graph results as current.
        old = {**app.state.library.latest_run(case["id"]), "fingerprint": previous_fingerprint}
        app.state.library.save_run(old)
        stale = client.get(f"/api/cases/{case['id']}/sources").json()
        assert stale["status"] == "stale" and stale["results"] == current["results"]
