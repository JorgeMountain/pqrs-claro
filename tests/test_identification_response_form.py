"""Global citation instructions stay literal context without becoming another search."""

from copy import deepcopy

import pytest

from pqrs_claro.identification import OpenAIIdentifier, _IdentificationSelection
from pqrs_claro.models import Page
from pqrs_claro.source_context import build_source_requests


def fixture(closing, *, method="native", needs_review=False):
    pages = [Page(number=1, method=method, needs_review=needs_review,
                  text="¿Qué requisitos exige la reserva de laboratorio?\n" + closing)]
    selection = _IdentificationSelection.model_validate({
        "subject": "Reserva de laboratorio ficticia", "requester": None,
        "document_date": None, "warnings": [], "requests": [{
            "label": str(i), "title": title, "description": text, "parent_index": None,
            "source_refs": [{"page": 1, "line_start": i, "line_end": i}],
        } for i, (title, text) in enumerate([
            ("Requisitos", "Informar los requisitos de reserva."),
            ("Documentos", closing),
        ], 1)],
    })
    return pages, selection


@pytest.mark.parametrize("closing", [
    "Agradezco responder cada punto e indicar los documentos que sustentan la información.",
    "Por favor, respondan cada numeral citando las fuentes utilizadas.",
    "Solicito que la respuesta a los puntos anteriores incluya las fuentes utilizadas.",
    "En esta respuesta, indiquen los documentos que respaldan la respuesta.",
])
def test_pure_global_citation_clause_stays_in_actual_context_without_extra_search(closing):
    pages, selected = fixture(closing)
    original = deepcopy((pages, selected))
    result = OpenAIIdentifier._materialize(selected, pages)
    assert [r.id for r in result.requests] == ["P1"]
    requests = build_source_requests({"id": "fictitious-reservation",
        "pages": [p.model_dump() for p in pages], "identification": result.model_dump()})
    assert len(requests) == 1
    excerpts = requests[0]["context"]["document_context"]["excerpts"]
    assert any(closing in e["quote"] for e in excerpts)
    assert (pages, selected) == original


@pytest.mark.parametrize("closing", [
    "Solicito copia de los documentos que sustentan la respuesta.",
    "Indiquen los documentos que sustentan la decisión de cancelar mi reserva.",
    "Relacionen los documentos del expediente y sus fechas.",
    "Agradezco responder cada punto e indicar los documentos que sustentan la información. "
    "Solicito además copia del Acta 82.",
    "En la respuesta, indiquen las fuentes utilizadas y entreguen copia de ellas.",
    "En esta respuesta, indiquen los documentos que respaldan la respuesta del 8 de abril.",
    "Solicito que la respuesta incluya las fuentes del expediente técnico 281.",
    "Solicito que motiven la decisión adoptada sobre mi solicitud.",
    "Agradezco responder cada punto e indicar los documentos que sustentan la información médica.",
])
def test_substantive_deliveries_inventories_and_specific_decisions_remain_requests(closing):
    pages, selection = fixture(closing)
    result = OpenAIIdentifier._materialize(selection, pages)
    assert len(result.requests) == 2
    assert result.requests[1].source_refs[0].quote == closing


@pytest.mark.parametrize("condition", ["ocr", "mixed_range", "parent", "budget", "sole_request"])
def test_uncertain_scope_or_context_is_never_silently_removed(condition):
    closing = "Por favor, respondan cada numeral citando las fuentes utilizadas."
    pages, selection = fixture(closing)
    if condition == "ocr":
        pages[0].method = "ocr"
        pages[0].needs_review = True
    elif condition == "mixed_range":
        selection.requests[1].source_refs[0].line_start = 1
    elif condition == "parent":
        selection.requests[0], selection.requests[1] = selection.requests[1], selection.requests[0]
        selection.requests[1].parent_index = 1
    elif condition == "budget":
        filler = "\n".join(["Contexto ficticio sin otra solicitud. " * 20] * 24)
        pages[0].text = pages[0].text.splitlines()[0] + "\n" + filler + "\n" + closing
        selection.requests[1].source_refs[0].line_start = 26
        selection.requests[1].source_refs[0].line_end = 26
    elif condition == "sole_request":
        selection.requests = selection.requests[1:]
    result = OpenAIIdentifier._materialize(selection, pages)
    assert len(result.requests) == len(selection.requests)


def test_remapped_hierarchy_keeps_original_numbering_and_quotes():
    pages, selection = fixture("En la respuesta, citen las fuentes utilizadas.")
    pages[0].text += "\n¿Cuál es el plazo de respuesta?\n¿Existe una excepción al plazo?"
    for line, parent in [(3, None), (4, 3)]:
        raw = selection.requests[0].model_dump()
        raw.update(label=f"apartado {line}", title="Plazo", description="Indicar el plazo.",
                   parent_index=parent, source_refs=[{"page": 1, "line_start": line,
                                                     "line_end": line}])
        selection.requests.append(type(selection.requests[0]).model_validate(raw))
    result = OpenAIIdentifier._materialize(selection, pages)
    assert [r.id for r in result.requests] == ["P1", "P2", "P3"]
    assert result.requests[-1].parent_id == "P2"
    assert result.requests[-1].label == "apartado 4"
    assert result.requests[-1].source_refs[0].quote == "¿Existe una excepción al plazo?"
