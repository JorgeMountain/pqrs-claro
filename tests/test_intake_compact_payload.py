import copy

from pqrs_claro.intake_engine import numbered_payload


def test_provider_payload_preserves_evidence_but_omits_internal_graph():
    candidate = dict(
        chunk_id="chunk1",
        source_id="chosen",
        document_id="document1",
        title="Fuente",
        quote="Cita literal",
        page=2,
        line_start=4,
        line_end=5,
        needs_review=True,
        verification_note="No autenticado",
        validity="unknown",
        extraction_note="Revisar OCR",
        related_source_ids=["other"] * 1000,
        sha256="internal hash",
    )
    payload = dict(
        pages=[dict(number=2, text="uno\ndos")],
        identification={"requests": [{"id": "P1"}]},
        candidates=[candidate],
        scope={
            "catalog": [
                {"id": "chosen", "extraction_status": "ready"},
                {"id": "omitted", "extraction_status": "ready"},
                {"id": "unread", "extraction_status": "pending"},
                {"id": "partial", "extraction_status": "partial"},
            ]
        },
    )
    before = copy.deepcopy(payload)
    compact = numbered_payload(payload)
    assert payload == before
    assert compact["identification"] == payload["identification"]
    assert compact["candidates"][0]["quote"] == "Cita literal"
    assert compact["candidates"][0]["verification_note"] == "No autenticado"
    assert compact["candidates"][0]["needs_review"]
    assert compact["candidates"][0]["line_start"] == 4
    assert "related_source_ids" not in compact["candidates"][0]
    assert "sha256" not in compact["candidates"][0]
    assert {s["id"] for s in compact["scope"]["catalog"]} == {"chosen", "unread", "partial"}
    assert compact["scope"]["catalog_omitted_readable_sources"] == 1
    assert not compact["scope"]["catalog_complete"]
