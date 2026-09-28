import hashlib
from types import SimpleNamespace

from pqrs_claro.intake_service import IntakeService


def test_large_intake_balances_context_without_losing_requests(monkeypatch, tmp_path):
    requests = [{"id": f"P{i}", "title": f"Petición {i}", "description": ""} for i in range(25)]
    original = {"identification": {"requests": requests}, "pages": [{"text": "Documento completo"}]}
    calls = []

    def retrieve(query, chunks, *, limit, index):
        calls.append(index)
        return [
            {"chunk_id": f"{query['id']}-{n}", "category": "national_norm"} for n in range(limit)
        ]

    monkeypatch.setattr("pqrs_claro.intake_service.retrieve", retrieve)
    service = IntakeService.__new__(IntakeService)
    service.cases = SimpleNamespace(get=lambda _: original)
    service.library = SimpleNamespace(snapshot=lambda _: ([], []), linked_collections=lambda _: [])
    service.sources = SimpleNamespace(catalog=lambda _: [])
    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(b"ficticio")
    service.cases.original = lambda _: pdf
    case = service.cases.get("case")
    case["sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    service.cases.get = lambda _: case
    payload = service.payload("case")
    assert payload["identification"] == original["identification"]
    assert payload["pages"] == original["pages"]
    assert len({id(index) for index in calls}) == 1
    assert len(payload["candidates"]) == 96
    assert len({c["chunk_id"] for c in payload["candidates"]}) == 96
    assert {f"{r['id']}-0" for r in requests} <= {c["chunk_id"] for c in payload["candidates"]}
    assert "INITIAL-0" in {c["chunk_id"] for c in payload["candidates"]}
    assert payload["scope"]["candidates_limited"]
    assert payload["scope"]["retrieved_candidates"] == 416


def test_small_intake_keeps_every_candidate_and_reports_no_limit(monkeypatch, tmp_path):
    chunks = [{"chunk_id": "same", "category": "historical_response"}]
    monkeypatch.setattr("pqrs_claro.intake_service.retrieve", lambda *a, **k: chunks)
    service = IntakeService.__new__(IntakeService)
    service.cases = SimpleNamespace(
        get=lambda _: {"identification": {"requests": [{"id": "P1"}]}, "pages": []}
    )
    service.library = SimpleNamespace(
        snapshot=lambda _: ([], chunks), linked_collections=lambda _: []
    )
    service.sources = SimpleNamespace(catalog=lambda _: [])
    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(b"ficticio")
    service.cases.original = lambda _: pdf
    case = service.cases.get("case")
    case["sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    service.cases.get = lambda _: case
    payload = service.payload("case")
    assert payload["candidates"] == chunks
    assert not payload["scope"]["candidates_limited"]
    assert payload["scope"]["history_available"]
