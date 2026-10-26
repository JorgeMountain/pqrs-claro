"""Identification must never load or search the source library."""

import hashlib
from types import SimpleNamespace

import pytest

from pqrs_claro.intake_service import IntakeService


@pytest.mark.parametrize("count", [1, 10, 25])
def test_classification_uses_original_without_loading_the_library(tmp_path, count):
    requests = [{"id": f"P{i}", "title": f"Petición {i}", "description": ""}
                for i in range(count)]
    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(b"ficticio")
    case = {"identification": {"requests": requests},
            "pages": [{"text": "Documento completo"}],
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}

    def forbidden(*args, **kwargs):
        pytest.fail("Identification attempted to read the library")

    service = IntakeService.__new__(IntakeService)
    service.cases = SimpleNamespace(get=lambda _: case, original=lambda _: pdf)
    service.library = SimpleNamespace(snapshot=forbidden, linked_collections=forbidden)
    service.sources = SimpleNamespace(catalog=forbidden)
    service.preanalysis = lambda _: {"checks": {}, "approval": {"actor_id": "test"}}
    payload = service.payload("case")
    assert payload["identification"] == case["identification"]
    assert payload["pages"] == case["pages"]
    assert payload["preanalysis"]["approval"] == {"actor_id": "test"}
    assert payload["candidates"] == []
    assert payload["scope"]["library_search"] == "not_requested"
    assert not payload["scope"]["history_available"]

    pdf.write_bytes(b"original replaced")
    with pytest.raises(ValueError, match="original"):
        service.payload("case")
