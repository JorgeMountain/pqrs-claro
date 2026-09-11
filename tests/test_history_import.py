"""Importación histórica aislada: binarios ficticios, sin fuentes reales ni red."""

import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError
from pqrs_claro.source_import import HistoryImporter
from pqrs_claro.source_library import SourceLibrary


def collection(identifier="historia-a"):
    return {
        "id": identifier,
        "title": "Trámites anteriores ficticios",
        "summary": {"unique_documents": 3, "occurrences": 5, "unsupported": 1},
    }


def metadata(**changes):
    return {
        "filename": "oficio_0123.txt",
        "title": "Oficio 0123 sobre el comité de prácticas",
        "category": "historical_response",
        "origin": "Entrega ficticia para probar la importación local.",
        "historical_group": "PQRS-FICTICIA-123",
        "radicados": ["FICTICIO-123"],
        "document_status": "issued",
        "aliases": [{"path": "entrega/oficio_0123.txt", "kind": "file"}],
        **changes,
    }


def extraction(status="ready", text="El comité de prácticas decidió sobre la plaza."):
    return {
        "pages": [
            {
                "number": 1,
                "text": text,
                "method": "native",
                "needs_review": status == "partial",
            }
        ]
        if status in {"ready", "partial"}
        else [],
        "location_kind": "section",
        "extraction_status": status,
        "extraction_note": "Extracción ficticia para pruebas, sin OCR ni llamadas externas.",
    }


def add(importer, data=b"Oficio ficticio del comite de practicas.", *, meta=None, read=None):
    return importer.add(
        data,
        meta or metadata(),
        read or extraction(),
        expected_sha256=hashlib.sha256(data).hexdigest(),
    )


@pytest.fixture
def library(tmp_path):
    library = SourceLibrary(tmp_path / "data", PDFExtractor())
    library.save_collection(collection())
    return library


def test_requires_existing_collection_and_hash_match_before_writing(library):
    with pytest.raises(DomainError, match="Crea la colección"):
        HistoryImporter(library, "inexistente")
    importer = HistoryImporter(library, "historia-a")
    with pytest.raises(DomainError, match="cambió desde el inventario"):
        importer.add(b"Cambio posterior", metadata(), extraction(), expected_sha256="0" * 64)
    assert library.list() == []
    assert list(library.root.iterdir()) == []


def test_import_never_turns_general_verification_claim_into_reviewed_document(library):
    importer = HistoryImporter(library, "historia-a")
    source, created = add(
        importer,
        meta=metadata(
            review_status="reviewed",
            reviewed_by="No confirmado",
            verification_status="documented",
            verification_note="Afirmación no comprobada",
        ),
    )
    assert created is True
    assert source["review_status"] == "pending"
    assert source["verification_status"] == "pending"
    assert source["reviewed_by"] is None
    assert "algunas respuestas" in source["verification_note"]
    assert "No se ha identificado el alcance" in source["verification_note"]
    assert library.get(source["id"])["source"]["review_status"] == "pending"


def test_indexed_history_is_ineligible_until_case_explicitly_links_collection(library):
    importer = HistoryImporter(library, "historia-a")
    ready, _ = add(importer)
    partial, _ = add(importer, b"Anexo parcialmente legible", read=extraction("partial"))
    unsupported, _ = add(
        importer,
        b"\x00\x01binary",
        meta=metadata(filename="anexo.xlsx"),
        read=extraction("unsupported"),
    )
    archive, _ = add(
        importer,
        b"Archivo catalogado sin uso probatorio",
        meta=metadata(category="archive_only"),
    )
    assert library.linked_collections("caso-a") == []
    assert library.eligible("caso-a") == []
    assert library.snapshot("caso-a") == ([], [])
    library.link_collections("caso-a", ["historia-a"])
    sources, chunks = library.snapshot("caso-a")
    assert {source["id"] for source in sources} == {ready["id"], partial["id"]}
    assert {chunk["source_id"] for chunk in chunks} == {ready["id"], partial["id"]}
    assert all(chunk["needs_review"] for chunk in chunks if chunk["source_id"] == partial["id"])
    assert library.snapshot("caso-b") == ([], [])
    assert library.original(unsupported["id"]).read_bytes() == b"\x00\x01binary"
    assert library.original(archive["id"]).read_bytes() == b"Archivo catalogado sin uso probatorio"


def test_dedup_preserves_bytes_and_aliases_and_survives_importer_restart(library):
    data = b"Original ficticio inmutable"
    aliases = [
        {"path": "carpeta/oficio.txt", "kind": "file"},
        {"path": "anexos.zip/oficio.txt", "kind": "zip"},
    ]
    source, created = add(
        HistoryImporter(library, "historia-a"), data, meta=metadata(aliases=aliases)
    )
    again, created_again = add(
        HistoryImporter(library, "historia-a"),
        data,
        meta=metadata(aliases=aliases, title="Un duplicado no reemplaza el título original"),
    )
    assert created is True and created_again is False
    assert again["id"] == source["id"]
    assert len(library.list()) == 1
    assert library.get(source["id"])["source"]["aliases"] == aliases
    assert library.get(source["id"])["source"]["title"] == source["title"]
    assert library.original(source["id"]).read_bytes() == data


def test_later_duplicate_retains_new_provenance_without_replacing_original(library):
    importer = HistoryImporter(library, "historia-a")
    data = b"Mismo original por dos vias"
    first_alias = {"path": "carpeta/oficio.txt", "kind": "file"}
    second_alias = {"path": "anexos.zip/oficio.txt", "kind": "zip"}
    first, _ = add(importer, data, meta=metadata(aliases=[first_alias]))
    second, created = add(importer, data, meta=metadata(aliases=[second_alias]))
    assert created is False and second["id"] == first["id"]
    assert library.get(first["id"])["source"]["aliases"] == [first_alias, second_alias]
    assert library.original(first["id"]).read_bytes() == data


def test_same_binary_in_two_collections_does_not_cross_their_scope(library):
    library.save_collection(collection("historia-b"))
    first, _ = add(HistoryImporter(library, "historia-a"))
    second, created = add(HistoryImporter(library, "historia-b"))
    assert created is True and first["id"] != second["id"]
    assert first["sha256"] == second["sha256"]
    library.link_collections("caso-a", ["historia-a"])
    assert {source["id"] for source in library.eligible("caso-a")} == {first["id"]}


def test_changed_binary_with_same_filename_keeps_both_originals(library):
    importer = HistoryImporter(library, "historia-a")
    first, _ = add(importer, b"Primera copia recibida")
    second, created = add(importer, b"Otra copia con contenido diferente")
    assert created is True and first["id"] != second["id"]
    assert first["sha256"] != second["sha256"]
    assert library.original(first["id"]).read_bytes() == b"Primera copia recibida"
    assert library.original(second["id"]).read_bytes() == b"Otra copia con contenido diferente"


def test_tampering_blocks_even_duplicate_import_and_keeps_catalog_record(library):
    importer = HistoryImporter(library, "historia-a")
    source, _ = add(importer)
    library.original(source["id"]).write_bytes(b"Modificacion externa no autorizada")
    with pytest.raises(DomainError, match="original cambió"):
        add(importer)
    assert len(library.list()) == 1


def test_relationships_keep_exact_source_ids_without_claiming_verification(library):
    importer = HistoryImporter(library, "historia-a")
    response, _ = add(importer)
    attachment, _ = add(importer, b"Acta ficticia", meta=metadata(category="historical_attachment"))
    result = importer.relate(
        response["id"],
        [attachment["id"], response["id"], attachment["id"]],
        basis="Agrupación por carpeta, no comprobación de contenido.",
    )
    assert result["related_source_ids"] == [attachment["id"]]
    assert result["verification_status"] == "pending"
    library.save_collection(collection("historia-b"))
    other, _ = add(HistoryImporter(library, "historia-b"))
    with pytest.raises(DomainError, match="mezclar colecciones"):
        importer.relate(response["id"], [other["id"]], basis="Relación inválida")


class HistoryAssessor:
    """Doble explícito que registra el alcance transmitido por SourceService."""

    def __init__(self):
        self.requests = []

    def assess(self, request, candidates):
        self.requests.append(request)
        return {
            "request_id": request["id"],
            "status": "needs_evidence",
            "summary": "Resultado ficticio para comprobar persistencia y alcance.",
            "supports": [
                {**candidate, "reason": "Antecedente ficticio", "role": "antecedent"}
                for candidate in candidates[:1]
            ],
            "missing": [{"kind": "clarification", "description": "Contrastar aplicabilidad."}],
            "warnings": [],
        }


@pytest.fixture
def history_app(tmp_path):
    assessor = HistoryAssessor()
    app = create_app(
        Settings(data_dir=tmp_path / "app-data", model="test-model"), source_assessor=assessor
    )
    with TestClient(app) as client:
        app.state.library.save_collection(collection())
        yield app, client, assessor


def confirmed_case(app):
    # Estado de identificación ya confirmado; esta prueba cubre la fase de fuentes.
    case = app.state.store.create("peticion-ficticia.pdf", b"PDF ficticio no procesado")
    return app.state.store.update(
        case["id"],
        status="confirmed",
        request_count=1,
        identification={
            "subject": "Comité de prácticas",
            "requests": [
                {
                    "id": "P1",
                    "title": "Decisión de prácticas",
                    "description": "Indique la decisión del comité de prácticas.",
                }
            ],
        },
    )


def test_api_keeps_unsupported_original_downloadable_and_uses_collection_summary(history_app):
    app, client, _ = history_app
    data = b"\x00\xff\x01Formato sin lector, conservado literalmente"
    source, _ = add(
        HistoryImporter(app.state.library, "historia-a"),
        data,
        meta=metadata(filename="tabla-original.xlsx"),
        read=extraction("unsupported"),
    )
    response = client.get(f"/api/sources/{source['id']}/original")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "tabla-original.xlsx" in response.headers["content-disposition"]
    detail = client.get(f"/api/sources/{source['id']}").json()
    assert detail["pages"] == []
    assert detail["source"]["extraction_status"] == "unsupported"
    result = client.get("/api/source-collections").json()
    assert result["collections"] == [
        {**collection(), "extraction_counts": {"unsupported": 1}}
    ]
    assert result["linked_collection_ids"] == []


def test_api_link_unlink_updates_eligibility_and_invalidates_ready_search(history_app):
    app, client, assessor = history_app
    source, _ = add(HistoryImporter(app.state.library, "historia-a"))
    case = confirmed_case(app)
    other_case = confirmed_case(app)
    link_path = f"/api/cases/{case['id']}/source-collections"
    _, _, _, initial_fingerprint = app.state.sources.inputs(case["id"])
    assert client.get(f"/api/cases/{case['id']}/sources").json()["source_count"] == 0
    invalid = client.put(link_path, json={"collection_ids": ["missing"]})
    assert invalid.status_code == 422
    duplicate = client.put(link_path, json={"collection_ids": ["historia-a", "historia-a"]})
    assert duplicate.status_code == 422
    response = client.put(link_path, json={"collection_ids": ["historia-a"]})
    assert response.status_code == 200
    assert response.json()["collection_ids"] == ["historia-a"]
    _, _, _, linked_fingerprint = app.state.sources.inputs(case["id"])
    assert initial_fingerprint != linked_fingerprint
    assert app.state.library.eligible(other_case["id"]) == []
    search = client.post(
        f"/api/cases/{case['id']}/sources/search", json={"version": case["version"]}
    )
    assert search.status_code == 202, search.text
    deadline = time.monotonic() + 10
    while case["id"] in app.state.sources.active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert case["id"] not in app.state.sources.active
    ready = client.get(f"/api/cases/{case['id']}/sources").json()
    assert ready["status"] == "ready", ready
    assert ready["results"][0]["supports"][0]["source_id"] == source["id"]
    assert assessor.requests[0]["allowed_collection_ids"] == ["historia-a"]
    assert client.put(link_path, json={"collection_ids": []}).status_code == 200
    stale = client.get(f"/api/cases/{case['id']}/sources").json()
    assert stale["status"] == "stale" and stale["stale"] is True
    assert stale["source_count"] == 0
    assert stale["results"] == ready["results"]
    assert app.state.library.original(source["id"]).is_file()


def test_collection_routes_reject_unknown_case_without_linking(history_app):
    app, client, _ = history_app
    assert client.get("/api/source-collections", params={"case_id": "missing"}).status_code == 404
    response = client.put(
        "/api/cases/missing/source-collections", json={"collection_ids": ["historia-a"]}
    )
    assert response.status_code == 404
    assert app.state.library.linked_collections("missing") == []


def test_uploaded_case_defaults_to_all_collections_and_keeps_manual_selection(history_app):
    app, client, _ = history_app
    library = app.state.library
    library.save_collection(collection("historia-b"))
    source, _ = add(HistoryImporter(library, "historia-a"))
    pdf = client.get("/api/demo.pdf").content

    result = client.post("/api/cases", files={"file": ("nueva.pdf", pdf, "application/pdf")})
    assert result.status_code == 201
    case_id = result.json()["id"]
    groups = client.get("/api/source-collections", params={"case_id": case_id}).json()
    assert groups["linked_collection_ids"] == ["historia-a", "historia-b"]
    assert source["id"] in [s["id"] for s in library.eligible(case_id)]

    path = f"/api/cases/{case_id}/source-collections"
    assert client.put(path, json={"collection_ids": []}).status_code == 200
    assert client.get("/api/source-collections", params={"case_id": case_id}).json()["linked_collection_ids"] == []
    assert library.eligible(case_id) == []

    # Newly available collections apply to the next upload, without resetting a saved choice.
    library.save_collection(collection("historia-c"))
    newer = client.post("/api/cases", files={"file": ("otra.pdf", pdf, "application/pdf")})
    assert newer.status_code == 201
    assert library.linked_collections(newer.json()["id"]) == ["historia-a", "historia-b", "historia-c"]
    assert library.linked_collections(case_id) == []


def test_human_review_documents_its_scope_without_declaring_the_file_issued(library):
    source, _ = add(
        HistoryImporter(library, "historia-a"), meta=metadata(document_status="unknown")
    )
    assert source["verification_status"] == "pending"
    reviewed = library.review(
        source["id"],
        reviewed_by="Responsable ficticio",
        review_note="Cotejé esta copia con el archivo conservado en secretaría.",
        validity="not_applicable",
    )
    assert reviewed["verification_status"] == "documented"
    assert reviewed["verification_note"] == reviewed["review_note"]
    assert reviewed["reviewed_by"] == "Responsable ficticio"
    assert reviewed["document_status"] == "unknown"
    assert library.get(source["id"])["source"]["verification_status"] == "documented"
