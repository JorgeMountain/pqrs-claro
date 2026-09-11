"""El contexto distingue las citas precisas del objeto preguntado y de los candidatos."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pqrs_claro.draft_engine import OpenAIDraftEngine, _api_context, citation_context
from pqrs_claro.models import DomainError


def source(chunk="paper:1", **changes):
    return {
        "chunk_id": chunk,
        "source_id": "paper-pdf",
        "document_id": "paper",
        "version": 1,
        "title": "Oficio 0412-2025",
        "filename": "oficio0412.pdf",
        "category": "historical_response",
        "role": "antecedent",
        "document_status": "issued",
        "verification_status": "reported_by_user",
        "collection_id": "test-history",
        "case_id": None,
        "page": 1,
        "line_start": 1,
        "line_end": 3,
        "location_kind": "page",
        "quote": "En 2017 el comité aprobó la plaza.",
        **changes,
    }


def inquiry():
    return {
        "id": "P1",
        "case_id": "case",
        "title": "Consulta sobre el período 2021",
        "description": "Confirme el registro de calificaciones finales de 2021.",
        "allowed_collection_ids": ["test-history"],
    }


def finding(supports):
    return {"request_id": "P1", "status": "ready", "supports": supports, "missing": []}


def test_request_years_and_source_title_do_not_become_years_of_the_cited_fact():
    selected = source()
    context, aliases = _api_context(inquiry(), finding([selected]), {"paper:1": selected})
    guide = context["citation_context"]
    assert guide["years_in_request"] == ["2021"]
    assert guide["passages"][0]["years_in_quote"] == ["2017"]
    assert guide["passages"][0]["office_reference_from_title"] == "0412-2025"
    assert "2025" not in guide["passages"][0]["years_in_quote"]
    assert guide["passages"][0]["alias"] == aliases["paper:1"]
    assert guide["limits"]["years_are_literal_mentions_not_verified_periods"]
    assert guide["limits"]["request_scope_is_not_evidence"]
    assert context["request"]["description"] == inquiry()["description"]
    assert context["finding"]["supports"][0]["quote"] == selected["quote"]


def test_neighbor_passages_resolve_references_only_within_same_document_version_and_units():
    first = source("paper:136", page=136, location_kind="section", quote="En 2017 se revisó.")
    second = source("paper:137", page=137, location_kind="section", quote="Durante ese período.")
    distant = source("paper:200", page=200, location_kind="section")
    other_version = source("paper:v2", page=137, location_kind="section", version=2)
    other_units = source("paper:page", page=137, location_kind="page")
    selected = [first, second, distant, other_version, other_units]
    guide = citation_context(inquiry(), {item["chunk_id"]: item for item in selected})
    assert guide["passages"][0]["neighbor_aliases"] == ["S2"]
    assert guide["passages"][1]["neighbor_aliases"] == ["S1"]
    assert guide["passages"][2]["neighbor_aliases"] == []
    assert guide["passages"][3]["neighbor_aliases"] == []
    assert guide["passages"][4]["neighbor_aliases"] == []
    assert guide["document_groups"][0]["aliases"] == ["S1", "S2", "S3", "S5"]
    assert guide["document_groups"][1]["version"] == 2


def test_pdf_and_docx_with_same_office_title_are_related_without_merging_their_evidence():
    pdf = source(title="06_Oficio_0412-2025_Respuesta.pdf")
    docx = source(
        "word:1", source_id="word", document_id="word", title="Oficio 0412-2025 Respuesta",
        filename="oficio.docx", document_status="unknown", office_numbers=["0412-2025", "7-2019"],
    )
    other = source(
        "old:1", document_id="old", title="Oficio 7-2019", source_id="old",
        quote="Fue citado en el oficio posterior.",
    )
    guide = citation_context(inquiry(), {s["chunk_id"]: s for s in [pdf, docx, other]})
    assert len(guide["document_groups"]) == 3
    assert guide["same_office_references"] == [{
        "office_reference": "0412-2025", "document_groups": ["D1", "D2"],
        "content_equivalence_verified": False,
    }]
    assert guide["passages"][1]["document_status"] == "unknown"
    assert guide["passages"][0]["neighbor_aliases"] == []


@pytest.mark.parametrize("title, expected", [
    ("Oficio 0012 de 2024", "0012-2024"),
    ("Oficio No. 21360001-0034-2024", "21360001-0034-2024"),
    ("Oficio XXXX-2026 Respuesta", "XXXX-2026"),
    ("Acta 0012-2024", None),
    ("Oficio 0012 sin año", None),
])
def test_office_relations_use_title_identifiers_without_inventing_years(title, expected):
    selected = source(title=title)
    guide = citation_context(inquiry(), {selected["chunk_id"]: selected})
    assert guide["passages"][0]["office_reference_from_title"] == expected


def test_verified_placeholder_office_stays_draft_in_citation_context():
    selected = source(title="Oficio XXXX-2025", document_status="issued")
    guide = citation_context(inquiry(), {selected["chunk_id"]: selected})
    assert guide["passages"][0]["document_status"] == "draft"
    assert selected["document_status"] == "issued"


def test_non_citable_candidate_is_excluded_from_guide_and_cannot_be_cited():
    selected = source()
    found = finding([selected])
    found["candidate_documents"] = [{
        "source_id": "candidate", "document_id": "candidate", "version": 1,
        "title": "Oficio 0412-2025", "filename": "candidate.pdf",
        "category": "historical_response", "location_status": "candidate_located",
        "selected_as_support": False,
        "chunks": [{"chunk_id": "candidate:1", "page": 2, "line_start": 1, "line_end": 2,
                    "quote": "En 2021 se registraron las calificaciones finales."}],
    }]
    before = deepcopy(found)
    context, aliases = _api_context(inquiry(), found, {selected["chunk_id"]: selected})
    assert aliases == {"paper:1": "S1"}
    assert len(context["citation_context"]["passages"]) == 1
    assert context["citation_context"]["same_office_references"] == []
    assert context["finding"]["candidate_documents"][0]["citable"] is False
    assert found == before
    worker = OpenAIDraftEngine("fictitious", "test-model")
    worker._call = lambda *_: {
        "objective": "Explicar la respuesta histórica.",
        "points": [{"description": "Afirmar el año de un candidato.", "cited_chunk_ids": ["S2"]}],
    }
    with pytest.raises(DomainError, match="desconocido"):
        worker.plan(inquiry(), found)


def test_custom_aliases_are_preserved_without_adding_human_fact_aliases():
    selected = source()
    guide = citation_context(
        inquiry(), {selected["chunk_id"]: selected}, {"paper:1": "S8", "fact:1": "F1"}
    )
    assert guide["document_groups"][0]["aliases"] == ["S8"]
    assert guide["passages"][0]["alias"] == "S8"
    assert guide["limits"]["group_ids_are_not_citation_aliases"]


def test_three_remote_stages_receive_identical_citation_scope_and_original_passages():
    selected = source()
    request, found = inquiry(), finding([selected])
    calls = []
    responses = iter([
        {"objective": "Describir el antecedente.", "points": [{
            "description": "Atribuir la conclusión al oficio de 2025 para el período 2017.",
            "cited_chunk_ids": ["S1"],
        }]},
        {"paragraphs": [{
            "text": "Según el Oficio 0412-2025, en 2017 el comité aprobó la plaza.",
            "cited_chunk_ids": ["S1"],
        }], "pending": []},
        {"status": "passed", "issues": []},
    ])

    def parse(**kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(
            status="completed", output_parsed=kwargs["text_format"].model_validate(next(responses))
        )

    worker = OpenAIDraftEngine("fictitious", "test-model")
    worker.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    plan = worker.plan(request, found)
    draft = worker.write(request, found, plan)
    worker.check(request, found, plan, draft)
    assert len(calls) == 3
    for context in calls:
        assert context["citation_context"] == calls[0]["citation_context"]
        assert context["finding"]["supports"][0]["quote"] == selected["quote"]
        assert context["finding"]["supports"][0]["chunk_id"] == "S1"
        assert context["citation_context"]["passages"][0]["title"] == selected["title"]


def test_direct_prose_keeps_original_components_and_each_paragraphs_own_support():
    """El estilo no cambia texto/numerales ni permite heredar citas de otro párrafo."""
    request = {
        **inquiry(),
        "title": "QUINTO. Contenido de la respuesta anterior",
        "description": "Según el oficio indicado: a) ¿Se aprobó la plaza en 2017? "
        "b) ¿Se aprobó en 2021?",
        "context": {"parent_text": "Resumir únicamente lo informado en el Oficio 0412-2025."},
    }
    selected = [
        source("paper:1", quote="En 2017 el comité no aprobó la plaza."),
        source("paper:2", page=2, quote="En 2021 el comité aprobó la plaza."),
    ]
    found = finding(selected)
    texts = [
        "Para el literal a), el Oficio 0412-2025 indicó que en 2017 el comité no aprobó "
        "la plaza. Esta contestación describe lo informado en ese antecedente.",
        "Para el literal b), el Oficio 0412-2025 señaló que en 2021 el comité sí aprobó "
        "la plaza. El resultado corresponde al periodo indicado en esa respuesta histórica.",
    ]
    responses = iter([
        {"objective": "Responder ambos literales con el antecedente citado.", "points": [
            {"description": text, "cited_chunk_ids": [f"S{number}"]}
            for number, text in enumerate(texts, 1)
        ]},
        {"paragraphs": [
            {"text": text, "cited_chunk_ids": [f"S{number}"]}
            for number, text in enumerate(texts, 1)
        ], "pending": []},
        {"status": "passed", "issues": []},
        {"status": "passed", "issues": []},
    ])
    calls = []

    def parse(**kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(
            status="completed", output_parsed=kwargs["text_format"].model_validate(next(responses))
        )

    worker = OpenAIDraftEngine("fictitious", "test-model")
    worker.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    before = deepcopy((request, found))
    plan = worker.plan(request, found)
    draft = worker.write(request, found, plan)
    checks = worker.check(request, found, plan, draft)
    assert checks["status"] == "passed"
    assert draft["status"] == "needs_review"
    assert draft["pending"] == []
    assert [item["text"] for item in draft["paragraphs"]] == texts
    assert [item["cited_chunk_ids"] for item in draft["paragraphs"]] == [["paper:1"], ["paper:2"]]
    assert all(context["request"] == request for context in calls)
    assert (request, found) == before

    wrong_citation = deepcopy(draft)
    wrong_citation["paragraphs"][1]["cited_chunk_ids"] = ["paper:1"]
    rejected = worker.check(request, found, plan, wrong_citation)
    assert rejected["status"] == "needs_changes"
    assert any(item["code"] == "period_grounded" and item["paragraph_index"] == 1
               for item in rejected["issues"])
