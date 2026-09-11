"""OCR aislado: originales, estados de lectura y revisión humana no se confunden."""

import copy
import hashlib
import json
import sqlite3

import pymupdf
import pytest

from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError
from pqrs_claro.source_import import HistoryImporter
from pqrs_claro.source_library import SourceLibrary, digest
from pqrs_claro.source_reextract import (
    PLAN_VERSION,
    add_ocr_text,
    apply_plan,
    prepare_source,
    read_rows,
)


class FakeOCR:
    def __init__(
        self, result="Documento escaneado de prueba. Asignatura 2503354, semestre 2015-1."
    ):
        self.result = result
        self.calls = 0

    def probe(self):
        return {"engine": "fake-local-test", "language": "es-ES", "max_dimension": 3200}

    def __call__(self, png):
        assert png.startswith(b"\x89PNG")
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def archived(tmp_path):
    data_dir = tmp_path / "data"
    library = SourceLibrary(data_dir, PDFExtractor())
    library.save_collection({"id": "test-history", "title": "Archivo ficticio"})
    with pymupdf.open() as image_doc:
        image_doc.new_page().insert_text((70, 70), "Documento escaneado de prueba 2015")
        image = image_doc[0].get_pixmap().tobytes("png")
    with pymupdf.open() as doc:
        first = doc.new_page()
        first.insert_text((70, 70), "Texto nativo completo que debe conservarse exactamente.")
        native = first.get_text().strip("\n")
        second = doc.new_page()
        second.insert_image(second.rect, stream=image)
        binary = doc.tobytes()
    pages = [
        dict(number=1, text=native, method="native", needs_review=False),
        dict(number=2, text="", method="native", needs_review=True),
    ]
    source, _ = HistoryImporter(library, "test-history").add(
        binary,
        dict(
            filename="archivo.pdf",
            title="Fuente de prueba",
            category="historical_attachment",
            origin="Prueba aislada",
        ),
        dict(pages=pages, extraction_status="partial", location_kind="page"),
        expected_sha256=hashlib.sha256(binary).hexdigest(),
    )
    return data_dir, library, source["id"], binary


def prepare(archived, ocr=None):
    data_dir, _, sid, _ = archived
    source, pages = read_rows(data_dir, ["test-history"], [sid])[0]
    entry = prepare_source(data_dir, source, pages, ocr or FakeOCR())
    plan = dict(
        plan_version=PLAN_VERSION,
        data_dir=str(data_dir.resolve()),
        collections=["test-history"],
        status="prepared",
        sources=[entry],
    )
    return plan, source, pages


def test_prepare_is_read_only_preserves_native_and_marks_ocr_for_review(archived):
    data_dir, library, sid, binary = archived
    before = library.get(sid)
    ocr = FakeOCR()
    plan, _, old_pages = prepare(archived, ocr)
    entry = plan["sources"][0]
    assert ocr.calls == 1
    assert entry["pages"][0] == old_pages[0]
    assert entry["pages"][1]["method"] == "ocr"
    assert entry["pages"][1]["needs_review"] is True
    assert entry["updates"]["extraction_status"] == "ready"
    assert entry["updates"]["extraction_report"]["pending_pages"] == []
    assert library.get(sid) == before
    assert library.original(sid).read_bytes() == binary


def test_failed_page_remains_partial_without_losing_native(archived):
    plan, _, pages = prepare(archived, FakeOCR(DomainError("Fallo local simulado")))
    entry = plan["sources"][0]
    assert entry["pages"] == pages
    assert entry["updates"]["extraction_status"] == "partial"
    assert entry["updates"]["extraction_report"]["pending_pages"] == [2]
    assert "Fallo local" in entry["page_events"][0]["error"]


def test_ocr_additions_preserve_existing_native_prefix_and_avoid_exact_duplicate_lines():
    native = "Encabezado nativo\nCódigo 2503354"
    text, action = add_ocr_text(native, "Encabezado nativo\nCódigo 2503354\nActa de 2015")
    assert text == native + "\n\nActa de 2015"
    assert action == "ocr_augmented"
    assert add_ocr_text(native, native) == (native, "preserved_native")


def test_apply_keeps_original_and_human_review_with_backup(archived, tmp_path):
    data_dir, library, sid, binary = archived
    library.review(
        sid,
        reviewed_by="Revisor ficticio",
        review_note="Comprobación previa concreta",
        validity="not_applicable",
    )
    plan, before, _ = prepare(archived)
    library.link_collections("fictitious-case", ["test-history"])
    before_fingerprint = digest(library.snapshot("fictitious-case"))
    result = apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
    assert result["updated_sources"] == 1
    assert (tmp_path / "backup.sqlite").is_file()
    after = library.get(sid)["source"]
    for field in [
        "sha256",
        "reviewed_by",
        "review_note",
        "reviewed_at",
        "review_status",
        "verification_status",
        "verification_note",
        "document_status",
        "version",
    ]:
        assert after.get(field) == before.get(field)
    assert after["extraction_revision"] == 1
    assert after["extraction_status"] == "ready"
    assert library.original(sid).read_bytes() == binary
    assert digest(library.snapshot("fictitious-case")) != before_fingerprint
    with sqlite3.connect(tmp_path / "backup.sqlite") as conn:
        saved_source, saved_pages = map(
            json.loads, conn.execute("SELECT body,pages FROM sources WHERE id=?", (sid,)).fetchone()
        )
        assert saved_source == before
        assert saved_pages[1]["text"] == ""
        assert (
            conn.execute("SELECT COUNT(*) FROM source_reviews WHERE id=?", (sid,)).fetchone()[0]
            == 1
        )
    with library.connect() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM source_reviews WHERE id=?", (sid,)).fetchone()[0]
            == 1
        )


def test_changed_review_after_prepare_prevents_stale_apply(archived, tmp_path):
    data_dir, library, sid, _ = archived
    plan, _, old_pages = prepare(archived)
    library.review(
        sid, reviewed_by="Nueva revisión", review_note="Cambio posterior", validity="not_applicable"
    )
    with pytest.raises(DomainError, match="cambió desde la propuesta"):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
    assert library.get(sid)["pages"] == old_pages
    assert library.get(sid)["source"]["reviewed_by"] == "Nueva revisión"


@pytest.mark.parametrize("field", ["pages", "updates", "collections", "original_sha256"])
def test_modified_proposals_cannot_change_other_data(archived, tmp_path, field):
    data_dir, library, sid, _ = archived
    plan, _, _ = prepare(archived)
    before = copy.deepcopy(library.get(sid))
    if field == "pages":
        plan["sources"][0]["pages"][0]["text"] = "Texto reemplazado"
    elif field == "updates":
        plan["sources"][0]["updates"]["review_status"] = "reviewed"
    elif field == "collections":
        plan["collections"] = ["otra-coleccion"]
    else:
        plan["sources"][0][field] = "0" * 64
    with pytest.raises(DomainError):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
    assert library.get(sid) == before


def test_original_modified_outside_library_stops_read(archived):
    data_dir, library, sid, _ = archived
    library.original(sid).write_bytes(b"Original alterado fuera de la aplicacion")
    with pytest.raises(DomainError, match="original cambió"):
        prepare(archived)


def test_scope_requires_pending_pdf_from_requested_collection(archived):
    data_dir, _, sid, _ = archived
    assert read_rows(data_dir, ["otra-coleccion"]) == []
    with pytest.raises(DomainError, match="alcance elegido"):
        read_rows(data_dir, ["otra-coleccion"], [sid])


def test_backup_does_not_overwrite_existing_file(archived, tmp_path):
    data_dir, _, _, _ = archived
    plan, _, _ = prepare(archived)
    backup = tmp_path / "backup.sqlite"
    backup.write_text("Conservar respaldo anterior", encoding="utf-8")
    with pytest.raises(DomainError, match="ya existe"):
        apply_plan(data_dir, plan, backup)
    assert backup.read_text(encoding="utf-8") == "Conservar respaldo anterior"


def test_late_invalid_entry_rolls_back_all_source_updates(archived, tmp_path):
    data_dir, library, sid, binary = archived
    first = library.get(sid)
    with pymupdf.open(stream=binary, filetype="pdf") as doc:
        doc.set_metadata({"title": "Segundo original ficticio"})
        other_binary = doc.tobytes()
    other, _ = HistoryImporter(library, "test-history").add(
        other_binary,
        dict(
            filename="otro.pdf",
            title="Otra fuente",
            category="historical_attachment",
            origin="Prueba aislada",
        ),
        dict(pages=first["pages"], extraction_status="partial", location_kind="page"),
        expected_sha256=hashlib.sha256(other_binary).hexdigest(),
    )
    plan, _, _ = prepare(archived)
    source, pages = read_rows(data_dir, ["test-history"], [other["id"]])[0]
    second = prepare_source(data_dir, source, pages, FakeOCR())
    second["updates"]["review_status"] = "reviewed"
    plan["sources"].append(second)
    with pytest.raises(DomainError, match="campos ajenos"):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
    assert library.get(sid) == first
    assert library.get(other["id"])["source"]["extraction_status"] == "partial"


def test_no_recognized_text_is_pending_instead_of_a_false_success(archived):
    data_dir, _, sid, _ = archived
    source, pages = read_rows(data_dir, ["test-history"], [sid])[0]
    for page in pages:
        page.update(text="", needs_review=True)
    source["extraction_status"] = "pending"
    entry = prepare_source(data_dir, source, pages, FakeOCR(" \n "))
    assert entry["updates"]["extraction_status"] == "pending"
    assert entry["updates"]["extraction_report"]["pending_pages"] == [1, 2]
    assert entry["pages"] == pages


@pytest.mark.parametrize("revision", [0, -1, 2, True, "1"])
def test_apply_rejects_invalid_extraction_revision(archived, tmp_path, revision):
    data_dir, _, _, _ = archived
    plan, _, _ = prepare(archived)
    plan["sources"][0]["updates"]["extraction_revision"] = revision
    with pytest.raises(DomainError, match="incrementar exactamente"):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")


def test_ocr_cannot_be_relabelled_as_unreviewed_native_text(archived, tmp_path):
    data_dir, _, _, _ = archived
    plan, _, _ = prepare(archived)
    plan["sources"][0]["pages"][1].update(method="native", needs_review=False)
    with pytest.raises(DomainError, match="OCR debe conservar"):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")


def test_failed_scan_cannot_be_relabelled_as_a_blank_native_page(archived, tmp_path):
    data_dir, _, _, _ = archived
    plan, _, _ = prepare(archived)
    entry = plan["sources"][0]
    entry["pages"][1] = dict(number=2, text="", method="native", needs_review=False)
    entry["page_events"][0]["action"] = "blank_native_page"
    with pytest.raises(DomainError, match="no es una página nativa vacía"):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")


def test_report_cannot_hide_failed_pages(archived, tmp_path):
    data_dir, _, _, _ = archived
    plan, _, _ = prepare(archived, FakeOCR(""))
    plan["sources"][0]["updates"]["extraction_report"]["pending_pages"] = []
    with pytest.raises(DomainError, match="informe de extracción"):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
