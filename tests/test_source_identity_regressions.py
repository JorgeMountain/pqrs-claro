"""Independent fictitious copy-identity regressions; no provider calls."""

import pytest
from test_normative_document_requests import norm, request, selection

from pqrs_claro.models import DomainError
from pqrs_claro.source_assessment import OpenAISourceAssessor, _allowed_roles
from pqrs_claro.source_documents import delivery_document_target, normative_copy_matches


@pytest.mark.parametrize("description,title,quote", [
    (
        "Solicito copia de la Circular 2025 de 2026.",
        "Circular 2025 de 2024",
        "CIRCULAR 2025 DE 2024\nContenido del acto.",
    ),
    (
        "Solicito copia de la Circular 402 de 2025.",
        "Circular 402 de 2024",
        "CIRCULAR 402 DE 2024\nModifica el Acuerdo 5 de 2025.\nContenido del acto.",
    ),
])
def test_copy_year_belongs_to_its_identity_not_number_or_nearby_document(description, title, quote):
    item = request(title="", description=description)
    source = norm(title=title, filename="archivo.pdf", quote=quote)
    assert not normative_copy_matches(item, source, "circular")
    assert _allowed_roles(source["category"], "circular", request=item, source=source) == ("rule",)
    with pytest.raises(DomainError):
        OpenAISourceAssessor._materialize(selection(source), item, [source])


@pytest.mark.parametrize("kind", ["Circular", "Protocolo"])
def test_split_document_header_cannot_match_a_different_numeric_suffix(kind):
    item = request(title="", description=f"Solicito copia del {kind} 615.")
    source = norm(title=f"{kind} 615-2", filename="archivo.pdf",
                  quote=f"{kind.upper()}\n615-2\nContenido del acto.")
    target = delivery_document_target(item)
    assert target["kind"] == kind.lower()
    assert not normative_copy_matches(item, source, target["kind"])
    assert _allowed_roles(source["category"], target["kind"],
                          request=item, source=source) == ("rule",)
    with pytest.raises(DomainError):
        OpenAISourceAssessor._materialize(selection(source), item, [source])


def test_one_copy_command_with_two_named_objects_never_resolves_only_the_first():
    item = request(title="", description=(
        "Adjunte copia de la Circular 402 de 2025 y del Manual 881 de 2026."
    ))
    target = delivery_document_target(item)
    assert target["status"] == "ambiguous"
    assert set(target["references"]) == {"circular 402 de 2025", "manual 881 de 2026"}
    source = norm()
    assert not normative_copy_matches(item, source, "circular")
    assert _allowed_roles(source["category"], "circular", request=item, source=source) == ("rule",)
