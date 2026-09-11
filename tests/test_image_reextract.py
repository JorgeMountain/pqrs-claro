"""Image migration: exactly one traceable section, original and reviews preserved."""

import copy
import hashlib
import json
import sqlite3
from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.image_ocr import normalized_image_png
from pqrs_claro.models import DomainError
from pqrs_claro.source_import import HistoryImporter
from pqrs_claro.source_library import SourceLibrary, digest
from pqrs_claro.source_reextract import PLAN_VERSION, apply_plan, prepare_source, read_rows


class FakeOCR:
    def __init__(self, text="Constancia de matrícula. Semestre 2020-1."):
        self.text = text

    def probe(self):
        return dict(engine="fake-test", max_dimension=3200)

    def __call__(self, png):
        with Image.open(BytesIO(png)) as image:
            assert image.format == "PNG"
            assert max(image.size) <= 3200
        return self.text


@pytest.fixture
def archive_image(tmp_path):
    def make(suffix=".png", binary=None, pages=None):
        data_dir = tmp_path / "data"
        library = SourceLibrary(data_dir, PDFExtractor())
        library.save_collection(dict(id="test-history", title="Archivo ficticio"))
        if binary is None:
            stream = BytesIO()
            with Image.new("RGB", (120, 80), "white") as image:
                image.save(stream, format="PNG" if suffix == ".png" else "JPEG")
            binary = stream.getvalue()
        source, _ = HistoryImporter(library, "test-history").add(
            binary,
            dict(
                filename="anexo" + suffix,
                title="Anexo de prueba",
                category="historical_attachment",
                origin="Prueba aislada",
            ),
            dict(pages=pages or [], extraction_status="pending", location_kind="section"),
            expected_sha256=hashlib.sha256(binary).hexdigest(),
        )
        return data_dir, library, source["id"], binary

    return make


def prepare(archived, text="Constancia de matrícula. Semestre 2020-1."):
    data_dir, _, sid, _ = archived
    source, pages = read_rows(data_dir, ["test-history"], [sid], file_kind="images")[0]
    entry = prepare_source(data_dir, source, pages, FakeOCR(text))
    plan = dict(
        plan_version=PLAN_VERSION,
        data_dir=str(data_dir.resolve()),
        collections=["test-history"],
        file_kind="images",
        status="prepared",
        sources=[entry],
    )
    return plan, source, pages


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg"])
def test_image_gains_one_section_with_original_review_and_backup_intact(
    archive_image, tmp_path, suffix
):
    archived = archive_image(suffix)
    data_dir, library, sid, binary = archived
    library.review(
        sid,
        reviewed_by="Persona revisora",
        review_note="Antecedente comprobado",
        validity="not_applicable",
    )
    library.link_collections("test-case", ["test-history"])
    before = library.get(sid)
    fingerprint = digest(library.snapshot("test-case"))
    plan, source, pages = prepare(archived)
    assert pages == []
    assert library.get(sid) == before
    assert plan["sources"][0]["updates"]["extraction_status"] == "ready"
    backup = tmp_path / "backup.sqlite"
    apply_plan(data_dir, plan, backup)
    after = library.get(sid)
    assert after["source"]["location_kind"] == "section"
    assert after["source"]["page_count"] == 1
    assert after["pages"] == [dict(number=1, text=FakeOCR().text, method="ocr", needs_review=True)]
    for field in [
        "sha256",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "verification_status",
        "verification_note",
        "document_status",
        "version",
    ]:
        assert after["source"].get(field) == source.get(field)
    assert library.original(sid).read_bytes() == binary
    assert digest(library.snapshot("test-case")) != fingerprint
    with sqlite3.connect(backup) as conn:
        saved, saved_pages = map(
            json.loads, conn.execute("SELECT body,pages FROM sources WHERE id=?", (sid,)).fetchone()
        )
        assert saved["page_count"] == 0 and saved_pages == []
        assert (
            conn.execute("SELECT COUNT(*) FROM source_reviews WHERE id=?", (sid,)).fetchone()[0]
            == 1
        )


def test_images_selection_excludes_pdf_and_default_does_not_include_images(archive_image):
    data_dir, _, sid, _ = archive_image()
    assert read_rows(data_dir, ["test-history"]) == []
    assert len(read_rows(data_dir, ["test-history"], file_kind="images")) == 1
    assert read_rows(data_dir, ["other"], file_kind="images") == []
    with pytest.raises(DomainError, match="alcance elegido"):
        read_rows(data_dir, ["test-history"], [sid])


def test_empty_ocr_image_is_pending_and_still_has_traceable_section(archive_image, tmp_path):
    archived = archive_image()
    data_dir, library, sid, _ = archived
    plan, _, _ = prepare(archived, "")
    assert plan["sources"][0]["updates"]["extraction_report"]["pending_pages"] == [1]
    apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
    result = library.get(sid)
    assert result["source"]["extraction_status"] == "pending"
    assert result["source"]["page_count"] == 1
    assert result["pages"] == [dict(number=1, text="", method="ocr", needs_review=True)]


def test_pdf_disguised_as_image_is_rejected_before_ocr(archive_image):
    with pymupdf.open() as doc:
        doc.new_page()
        binary = doc.tobytes()
    archived = archive_image(".jpg", binary)
    with pytest.raises(DomainError, match="decodificar"):
        prepare(archived)


def test_pdf_cannot_introduce_a_section_like_an_image(archive_image, tmp_path):
    archived = archive_image()
    data_dir, library, sid, _ = archived
    plan, source, _ = prepare(archived)
    with pymupdf.open() as doc:
        doc.new_page()
        binary = doc.tobytes()
    source.update(
        filename="archivo.pdf", location_kind="page", sha256=hashlib.sha256(binary).hexdigest()
    )
    (library.original(sid).parent / "original.pdf").write_bytes(binary)
    with library.connect() as conn:
        conn.execute("UPDATE sources SET body=? WHERE id=?", (json.dumps(source), sid))
    from pqrs_claro.source_reextract import state_digest

    entry = plan["sources"][0]
    entry["original_sha256"] = source["sha256"]
    entry["expected_state_sha256"] = state_digest(source, [])
    with pytest.raises(DomainError, match="número de páginas"):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")


@pytest.mark.parametrize(
    "mutation", ["second_section", "page_count", "location", "native", "blank"]
)
def test_modified_image_plan_cannot_change_structure_or_clear_ocr_review(
    archive_image, tmp_path, mutation
):
    archived = archive_image()
    data_dir, library, sid, _ = archived
    plan, _, _ = prepare(archived)
    before = copy.deepcopy(library.get(sid))
    entry = plan["sources"][0]
    if mutation == "second_section":
        entry["pages"].append(
            dict(number=2, text="Texto inventado", method="ocr", needs_review=True)
        )
    elif mutation == "page_count":
        entry["updates"]["page_count"] = 2
    elif mutation == "location":
        entry["updates"]["location_kind"] = "page"
    elif mutation == "native":
        entry["pages"][0].update(method="native", needs_review=False)
    else:
        entry["pages"][0].update(text="", method="native", needs_review=False)
        entry["page_events"][0]["action"] = "blank_native_page"
    with pytest.raises(DomainError):
        apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
    assert library.get(sid) == before


def test_raster_caps_size_and_honors_exif_orientation():
    stream = BytesIO()
    with Image.new("RGB", (200, 100), "white") as image:
        exif = image.getexif()
        exif[274] = 6
        image.save(stream, "JPEG", exif=exif)
    png, metadata = normalized_image_png(stream.getvalue(), ".jpg", max_dimension=80)
    with Image.open(BytesIO(png)) as raster:
        assert raster.size == (40, 80)
    assert metadata["original_size"] == [200, 100]
    assert metadata["exif_orientation"] == 6


def test_transparent_image_is_composited_on_white_for_ocr():
    stream = BytesIO()
    with Image.new("RGBA", (4, 4), (0, 0, 0, 0)) as image:
        image.save(stream, "PNG")
    png, _ = normalized_image_png(stream.getvalue(), ".png")
    with Image.open(BytesIO(png)) as raster:
        assert raster.mode == "RGB"
        assert raster.getpixel((0, 0)) == (255, 255, 255)


def test_animated_png_cannot_be_silently_reduced_to_one_section():
    stream = BytesIO()
    with Image.new("RGB", (4, 4), "white") as first, Image.new("RGB", (4, 4), "black") as second:
        first.save(stream, "PNG", save_all=True, append_images=[second], duration=100)
    with pytest.raises(DomainError, match="varios fotogramas"):
        normalized_image_png(stream.getvalue(), ".png")


def test_existing_image_text_is_preserved_literally_on_reextraction(archive_image, tmp_path):
    old = dict(number=1, text="Texto de sección previo.", method="ocr", needs_review=True)
    archived = archive_image(pages=[old])
    data_dir, library, sid, _ = archived
    plan, _, _ = prepare(archived)
    apply_plan(data_dir, plan, tmp_path / "backup.sqlite")
    assert library.get(sid)["pages"][0]["text"].startswith(old["text"])
    assert library.get(sid)["source"]["page_count"] == 1


def test_image_plan_reapply_is_stale(archive_image, tmp_path):
    archived = archive_image()
    plan, _, _ = prepare(archived)
    apply_plan(archived[0], plan, tmp_path / "first.sqlite")
    with pytest.raises(DomainError, match="cambió desde la propuesta"):
        apply_plan(archived[0], plan, tmp_path / "second.sqlite")


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg"])
def test_new_image_upload_uses_same_ocr_normalization_and_keeps_original(tmp_path, suffix):
    stream = BytesIO()
    with Image.new("RGB", (2200, 1800), "white") as image:
        image.save(stream, "PNG" if suffix == ".png" else "JPEG")
    binary = stream.getvalue()
    library = SourceLibrary(tmp_path / "data", PDFExtractor(FakeOCR()))
    source = library.add(
        "captura" + suffix,
        binary,
        title="Captura",
        category="previous_response",
        origin="Prueba de carga local",
    )
    stored = library.get(source["id"])
    assert stored["pages"] == [dict(number=1, text=FakeOCR().text, method="ocr", needs_review=True)]
    assert source["location_kind"] == "section"
    assert source["page_count"] == 1
    assert source["review_status"] == "pending"
    assert source["extraction_status"] == "ready"
    assert source["extraction_engine"]["engine"] == "fake-test"
    assert library.original(source["id"]).read_bytes() == binary


@pytest.mark.parametrize("provider", [None, FakeOCR(""), FakeOCR("?")])
def test_failed_image_upload_reports_problem_without_saving_false_text(tmp_path, provider):
    stream = BytesIO()
    with Image.new("RGB", (120, 80), "white") as image:
        image.save(stream, "PNG")
    library = SourceLibrary(tmp_path / "data", PDFExtractor(provider))
    with pytest.raises(DomainError, match="imagen"):
        library.add(
            "captura.png",
            stream.getvalue(),
            title="Captura",
            category="previous_response",
            origin="Prueba local",
        )
    assert library.list() == []
    assert list(library.root.iterdir()) == []
