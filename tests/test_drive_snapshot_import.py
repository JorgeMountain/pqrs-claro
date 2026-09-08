"""Copias ficticias: el inventario agrega fuentes sin borrar revisiones previas."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pymupdf
import pytest

from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError
from pqrs_claro.source_library import SourceLibrary

spec = importlib.util.spec_from_file_location(
    "drive_import", Path(__file__).parents[1] / "scripts/import_drive_snapshot.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def manifest(tmp_path, number=1):
    originals = tmp_path / "originals"
    originals.mkdir(exist_ok=True)
    pdf = originals / f"norma-{number}.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text(
            (72, 100),
            f"Fuente ficticia {number}. Texto sobre una solicitud academica y su resolucion.",
        )
        pdf.write_bytes(doc.tobytes())
    item = dict(
        local_original=str(pdf),
        sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        title=f"Norma ficticia {number}",
        drive_url=f"https://drive.google.com/file/d/ficticio{number}/view",
        drive_id=f"ficticio{number}",
        drive_folder="Normas",
        category="national_norm",
        verification_note="Copia conservada; vigencia pendiente de comprobar.",
    )
    body = dict(
        collection=dict(id="drive-ficticio", title="Drive ficticio", description="Prueba"),
        scope=[str(originals)],
        files=[item],
        verification_note=item["verification_note"],
    )
    path = tmp_path / f"inventory-{number}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path, body


def test_repeated_and_incremental_import_preserves_review_ids_and_collection_note(tmp_path):
    path, _ = manifest(tmp_path)
    data = tmp_path / "data"
    first = module.run(path, data)
    library = SourceLibrary(data, PDFExtractor())
    source_id = first["sources"][0]["source_id"]
    library.review(
        source_id,
        reviewed_by="Responsable ficticio",
        review_note="Verificado en este ensayo aislado.",
        validity="current",
    )
    source_before = library.get(source_id)
    collection = library.collections()[0]
    collection["verification_note"] = "Nota individual conservada de la colección."
    library.save_collection(collection)
    repeated = module.run(path, data)
    assert repeated["created"] == 0
    assert repeated["sources"][0]["source_id"] == source_id
    assert library.get(source_id) == source_before
    second, _ = manifest(tmp_path, 2)
    assert module.run(second, data)["total_sources"] == 2
    assert library.get(source_id) == source_before
    collection = library.collections()[0]
    assert collection["verification_note"] == "Nota individual conservada de la colección."
    assert collection["provenance_count"] == 2
    assert collection["indexed_count"] == 2
    fresh = next(s for s in library.list() if s["id"] != source_id)
    assert fresh["verification_status"] == "pending"
    assert fresh["validity"] == "unknown"
    assert fresh["aliases"][0]["drive_url"].startswith("https://drive.google.com/")


@pytest.mark.parametrize("change", ["sha", "scope", "url", "category"])
def test_invalid_inventory_fails_before_creating_library(tmp_path, change):
    path, body = manifest(tmp_path)
    if change == "sha":
        body["files"][0]["sha256"] = "0" * 64
    elif change == "scope":
        body["scope"] = [str(tmp_path / "inventory-1.json")]
    elif change == "url":
        body["files"][0]["drive_url"] = "https://unrelated.invalid/file"
    else:
        body["files"][0]["category"] = "invalid"
    path.write_text(json.dumps(body))
    with pytest.raises(DomainError):
        module.run(path, tmp_path / "data")
    assert not (tmp_path / "data").exists()


def test_same_bytes_in_another_collection_require_reconciliation(tmp_path):
    path, body = manifest(tmp_path)
    data = tmp_path / "data"
    module.run(path, data)
    body["collection"]["id"] = "another-collection"
    path.write_text(json.dumps(body))
    with pytest.raises(DomainError, match="otra colección"):
        module.run(path, data)
    library = SourceLibrary(data, PDFExtractor())
    assert len(library.list()) == len(library.collections()) == 1


def test_hash_dedup_also_includes_sources_private_to_other_cases(tmp_path):
    path, body = manifest(tmp_path)
    data = tmp_path / "data"
    library = SourceLibrary(data, PDFExtractor())
    item = body["files"][0]
    library.add(
        "soporte.pdf",
        Path(item["local_original"]).read_bytes(),
        title="Soporte ficticio de otro expediente",
        category="case_evidence",
        origin="Prueba",
        case_id="otro-expediente",
    )
    with pytest.raises(DomainError, match="otra colección"):
        module.run(path, data)
    with library.connect() as conn:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1


def test_extraction_uses_hashed_bytes_even_if_origin_changes_during_reading(tmp_path, monkeypatch):
    path, body = manifest(tmp_path)
    original = Path(body["files"][0]["local_original"])
    _, replacement_body = manifest(tmp_path, 2)
    replacement = Path(replacement_body["files"][0]["local_original"]).read_bytes()
    read = module.read_source

    def change_origin(snapshot, extractor):
        original.write_bytes(replacement)
        return read(snapshot, extractor)

    monkeypatch.setattr(module, "read_source", change_origin)
    data = tmp_path / "data"
    result = module.run(path, data)
    library = SourceLibrary(data, PDFExtractor())
    source_id = result["sources"][0]["source_id"]
    saved = library.get(source_id)
    assert "Fuente ficticia 1." in saved["pages"][0]["text"]
    assert "Fuente ficticia 2." not in saved["pages"][0]["text"]
    assert (
        hashlib.sha256(library.original(source_id).read_bytes()).hexdigest()
        == body["files"][0]["sha256"]
    )
