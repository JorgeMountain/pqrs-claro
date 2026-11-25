"""Pruebas locales con dobles explícitos: no hacen llamadas ni consumen OpenAI."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pymupdf
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from pqrs_claro.extraction import OpenAIOCR, PDFExtractor
from pqrs_claro.identification import OpenAIIdentifier, _IdentificationSelection
from pqrs_claro.models import (
    MAX_PDF_BYTES,
    DomainError,
    Identification,
    Page,
    Request,
    SourceRef,
    source_quote,
    validate_identification,
    validate_pages,
)
from pqrs_claro.workflow import build_graph


@pytest.fixture
def pages():
    return [
        Page(
            number=1,
            text=(
                "7 de septiembre de 2026\nSolicito información del trámite.\n"
                "  a) Indique los requisitos.\nb) Adjunte copia del acta."
            ),
            method="native",
            needs_review=False,
        )
    ]


def make_identification(pages):
    return Identification(
        subject="Información del trámite",
        requests=[
            Request(
                id="P1",
                label="1",
                title="Informar el trámite",
                description="Informar el trámite solicitado.",
                parent_id=None,
                source_refs=[
                    SourceRef(
                        page=1,
                        line_start=2,
                        line_end=2,
                        quote=source_quote(pages, 1, 2, 2),
                    )
                ],
            )
        ],
    )


def make_pdf(
    path,
    text="Solicito que se informe el procedimiento y los requisitos para el trámite institucional.",
):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 80), text)
        document.save(path)
    return path


def test_source_quotes_preserve_original_whitespace(pages):
    assert (
        source_quote(pages, 1, 2, 3)
        == "Solicito información del trámite.\n  a) Indique los requisitos."
    )
    result = make_identification(pages)
    validate_identification(result, pages)
    result.requests[0].source_refs[0].quote = "Solicito información del tramite."
    with pytest.raises(DomainError, match="no coincide"):
        validate_identification(result, pages)


@pytest.mark.parametrize("page,start,end", [(2, 1, 1), (1, 0, 1), (1, 3, 2), (1, 1, 99)])
def test_out_of_bounds_references_fail(pages, page, start, end):
    with pytest.raises(DomainError):
        source_quote(pages, page, start, end)


def test_missing_and_duplicate_request_ids_fail(pages):
    result = make_identification(pages)
    result.requests.append(result.requests[0].model_copy(deep=True))
    with pytest.raises(DomainError, match="único"):
        validate_identification(result, pages)
    result.requests = result.requests[:1]
    result.requests[0].parent_id = "P8"
    with pytest.raises(DomainError, match="padre.*no existe"):
        validate_identification(result, pages)


def test_hierarchy_cycles_and_order_fail(pages):
    result = make_identification(pages)
    child = result.requests[0].model_copy(deep=True)
    child.id, child.parent_id = "P2", "P1"
    result.requests.append(child)
    validate_identification(result, pages)
    result.requests[0].parent_id = "P2"
    with pytest.raises(DomainError, match="ciclo"):
        validate_identification(result, pages)
    child.parent_id = None
    with pytest.raises(DomainError, match="antes"):
        validate_identification(result, pages)


def test_no_requests_or_whitespace_fields_cannot_be_confirmed(pages):
    with pytest.raises(ValidationError):
        Identification(subject="Prueba", requests=[])
    result = make_identification(pages)
    result.requests[0].description = "   "
    with pytest.raises(DomainError, match="Completa"):
        validate_identification(result, pages)


def test_pages_never_truncate_or_ignore_numbering():
    with pytest.raises(DomainError, match="120.000"):
        validate_pages([Page(number=1, text="a" * 120001, method="native", needs_review=False)])
    with pytest.raises(DomainError, match="orden"):
        validate_pages([Page(number=2, text="Documento", method="native", needs_review=False)])


def test_extracts_native_pdf_and_preserves_blank_page(tmp_path):
    pdf = make_pdf(tmp_path / "native.pdf")
    with pymupdf.open(pdf) as source:
        source.new_page()
        source.saveIncr()
    pages = PDFExtractor().extract(str(pdf))
    assert len(pages) == 2
    assert "requisitos" in pages[0].text
    assert pages[0].method == "native"
    assert not pages[0].needs_review
    assert pages[1].text == ""


def test_rejects_corrupt_encrypted_and_oversized_pdf(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(DomainError, match="PDF válido"):
        PDFExtractor().extract(str(bad))
    with bad.open("wb") as stream:
        stream.seek(MAX_PDF_BYTES)
        stream.write(b"x")
    with pytest.raises(DomainError, match="20 MB"):
        PDFExtractor().extract(str(bad))
    encrypted = tmp_path / "locked.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(
            encrypted,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="test-owner",
            user_pw="test-user",
        )
    with pytest.raises(DomainError, match="contraseña"):
        PDFExtractor().extract(str(encrypted))


def test_rejects_too_many_pages(tmp_path):
    pdf = tmp_path / "many.pdf"
    with pymupdf.open() as document:
        for _ in range(41):
            document.new_page()
        document.save(pdf)
    with pytest.raises(DomainError, match="40 páginas"):
        PDFExtractor().extract(str(pdf))


def test_image_page_requires_ocr_and_gets_review_flag(tmp_path):
    native = make_pdf(tmp_path / "source.pdf")
    with pymupdf.open(native) as source:
        png = source[0].get_pixmap().tobytes("png")
    pdf = tmp_path / "scan.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_image(page.rect, stream=png)
        page.insert_text(
            (40, 35), "Encabezado de texto seleccionable que no cubre la imagen completa."
        )
        document.save(pdf)
    with pytest.raises(DomainError, match="necesita OCR"):
        PDFExtractor().extract(str(pdf))
    calls = []

    def fake_ocr(image):
        calls.append(image)
        return "Solicito una copia del acta.\nNombre [ILEGIBLE]"

    pages = PDFExtractor(fake_ocr).extract(str(pdf))
    assert len(calls) == 1 and calls[0].startswith(b"\x89PNG")
    assert pages[0].method == "ocr" and pages[0].needs_review
    assert "[ILEGIBLE]" in pages[0].text
    with pytest.raises(DomainError, match="no pudo leerse"):
        PDFExtractor(lambda _: "[ILEGIBLE]").extract(str(pdf))


def test_native_text_over_watermark_and_separate_scanned_content(tmp_path):
    def raster(text, grey):
        with pymupdf.open() as art:
            p = art.new_page(width=550, height=280)
            p.insert_text((20, 144), text, fontsize=36, color=(grey,) * 3)
            return p.get_pixmap().tobytes("png")

    watermark = raster("MARCA DE AGUA", 0.85)
    scanned = raster("Datos del anexo", 0.0)
    pdf = tmp_path / "mixto.pdf"
    with pymupdf.open() as document:
        for index in range(5):
            page = document.new_page(width=600, height=800)
            image_box = page.rect if index == 4 else pymupdf.Rect(25, 80, 575, 360)
            image = scanned if index == 2 else watermark
            if index == 4:
                image = raster("Datos de una fotocopia tenue", 0.85)
            page.insert_image(image_box, stream=image, keep_proportion=False)
            lines = ["Solicitud de informacion", "Solicito copia del acta",
                     "Gracias por la respuesta"]
            if index == 3:
                lines = ["Remitente", "Firma", "Cierre"]
            for y, line in zip((112, 185, 275), lines, strict=True):
                page.insert_text((50, y), line)
            if index == 1:
                page.insert_image(pymupdf.Rect(25, 380, 575, 660), stream=scanned)
        document.save(pdf)

    calls = []

    def transcribe(image):
        calls.append(image)
        return "Solicitud de informacion. Datos del anexo."

    pages = PDFExtractor(transcribe).extract(str(pdf))
    assert [(p.method, p.needs_review) for p in pages] == [
        ("native", False), ("ocr", True), ("ocr", True), ("native", False), ("ocr", True)
    ]
    assert len(calls) == 3
    assert "Solicito copia del acta" in pages[0].text


def test_short_selectable_request_and_logo_stay_native(tmp_path):
    path = tmp_path / "nota.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((55, 100), "Solicito copia.")
        page.draw_line((55, 115), (150, 115))
        page = doc.new_page()
        page.insert_text((55, 80), "Firma")
        logo = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 30, 30), 0)
        logo.clear_with(128)
        page.insert_image(pymupdf.Rect(20, 20, 50, 50), pixmap=logo)
        blank = doc.new_page()
        white = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 32, 32), 0)
        white.clear_with(255)
        blank.insert_image(blank.rect, pixmap=white)
        doc.save(path)
    pages = PDFExtractor().extract(str(path))
    assert [p.method for p in pages] == ["native", "native", "native"]
    assert pages[0].text.strip() == "Solicito copia."
    assert pages[2].text == ""


def test_searchable_scan_only_reuses_text_when_it_covers_the_raster(tmp_path):
    path = tmp_path / "con-capa.pdf"
    lines = ["Solicito el informe de actividades.", "Se adjuntan los datos del contrato."]
    with pymupdf.open() as scan:
        source = scan.new_page(width=480, height=300)
        for i, text in enumerate(lines):
            source.insert_text((25, 80 + i * 40), text)
        scanned = source.get_pixmap()
        for x, y in ((3, 4), (15, 60), (110, 230), (58, 157), (350, 40), (434, 278)):
            scanned.set_pixel(x, y, (0, 0, 0))
        raster = scanned.tobytes("png")
    with pymupdf.open() as doc:
        for layer in (lines, lines[:1], []):
            page = doc.new_page(width=480, height=300)
            page.insert_image(page.rect, stream=raster)
            for i, text in enumerate(layer):
                page.insert_text((25, 80 + i * 40), text, render_mode=3)
            page.set_rotation(90)
        doc.save(path)
    pages = PDFExtractor(lambda _: "\n".join(lines)).extract(str(path))
    assert [p.method for p in pages] == ["native", "ocr", "ocr"]
    assert all(lines[-1] in p.text for p in pages)


def test_scanned_insert_detected_alongside_long_native_text(tmp_path):
    path = tmp_path / "anexo.pdf"
    with pymupdf.open() as source:
        annex = source.new_page(width=300, height=75)
        annex.insert_text((10, 24), "La solicitud incluye material en este anexo.")
        annex.insert_text((10, 49), "El numero de expediente consta en la carta.")
        raster = annex.get_pixmap().tobytes("png")
    with pymupdf.open() as doc:
        page = doc.new_page()
        for i in range(30):
            page.insert_text((30, 40 + i * 17), "Solicito el informe del departamento academico.")
        page.insert_image(pymupdf.Rect(25, 600, 370, 690), stream=raster)
        assert len("".join(page.get_text().split())) > 1200
        doc.save(path)
    pages = PDFExtractor(lambda _: "Transcripción de la página con su anexo.").extract(str(path))
    assert pages[0].method == "ocr" and pages[0].needs_review


def test_damaged_unicode_mapping_and_outline_only_page_need_recognition(tmp_path):
    path = tmp_path / "sin-unicode.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        font_xref = page.insert_font(fontname="Broken", fontbuffer=pymupdf.Font("helv").buffer)
        page.insert_text((40, 80), "Solicitud visible en el original.", fontname="Broken")
        cmap = int(doc.xref_get_key(font_xref, "ToUnicode")[1].split()[0])
        doc.update_stream(cmap, b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
                          b"/CMapType 2 def 1 begincodespacerange <0000> <ffff> endcodespacerange "
                          b"1 beginbfchar <0035> <fffd> endbfchar endcmap "
                          b"CMapName currentdict /CMap defineresource pop end end")
        outline = doc.new_page()
        outline.draw_polyline([(30, 80), (40, 55), (50, 80)])
        outline.draw_line((35, 68), (45, 68))
        doc.save(path)
    pages = PDFExtractor(lambda _: "Contenido recuperado.").extract(str(path))
    assert [(p.method, p.needs_review) for p in pages] == [("ocr", True), ("ocr", True)]


def selection():
    return _IdentificationSelection.model_validate(
        {
            "subject": "Información",
            "requester": None,
            "document_date": "7 de septiembre de 2026",
            "requests": [
                {
                    "label": "1",
                    "title": "Informar",
                    "description": "Informar el trámite.",
                    "parent_index": None,
                    "source_refs": [{"page": 1, "line_start": 2, "line_end": 2}],
                },
                {
                    "label": "a",
                    "title": "Requisitos",
                    "description": "Indicar los requisitos.",
                    "parent_index": 1,
                    "source_refs": [{"page": 1, "line_start": 3, "line_end": 3}],
                },
            ],
            "warnings": [],
        }
    )


def test_identifier_uses_structured_output_and_python_quotes(pages):
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_parsed=selection())

    identifier = OpenAIIdentifier(api_key="test-not-real", model="test-model")
    identifier.client = SimpleNamespace(responses=SimpleNamespace(parse=fake_parse))
    result = identifier.identify(pages)
    assert calls[0]["store"] is False
    assert json.loads(calls[0]["input"])["pages"][0]["lines"][2]["number"] == 3
    assert [request.id for request in result.requests] == ["P1", "P2"]
    assert result.requests[1].parent_id == "P1"
    assert result.requests[1].source_refs[0].quote == "  a) Indique los requisitos."


def test_identifier_rejects_invented_date_reference_and_partial_result(pages):
    raw = selection()
    raw.requester = "Nombre que no consta en el documento"
    with pytest.raises(DomainError, match="nombre"):
        OpenAIIdentifier._materialize(raw, pages)
    raw.requester = None
    raw.document_date = "2024-01-01"
    with pytest.raises(DomainError, match="fecha"):
        OpenAIIdentifier._materialize(raw, pages)
    raw.document_date = None
    raw.requests[0].source_refs[0].line_end = 80
    with pytest.raises(DomainError, match="líneas"):
        OpenAIIdentifier._materialize(raw, pages)
    identifier = OpenAIIdentifier(api_key="test-not-real", model="test-model")
    identifier.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(status="incomplete", output_parsed=selection()),
        )
    )
    with pytest.raises(DomainError, match="parcial"):
        identifier.identify(pages)


def test_ocr_does_not_accept_incomplete_transcription():
    ocr = OpenAIOCR(api_key="test-not-real", model="test-model")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="incomplete", output_text="Fragmento")

    ocr.client = SimpleNamespace(responses=SimpleNamespace(create=fake_create))
    with pytest.raises(DomainError, match="parcial"):
        ocr(b"fake-png")
    assert calls[0]["store"] is False


def test_graph_sqlite_restart_does_not_repeat_reading_or_ai(tmp_path, pages):
    counts = {"read": 0, "identify": 0}

    class FakeExtractor:
        def extract(self, path):
            counts["read"] += 1
            return pages

    class FakeIdentifier:
        def identify(self, source_pages):
            counts["identify"] += 1
            return make_identification(source_pages)

    checkpoint = str(tmp_path / "checkpoints.sqlite")
    config = {"configurable": {"thread_id": "case-test"}}
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        graph = build_graph(FakeExtractor(), FakeIdentifier(), saver)
        paused = graph.invoke({"case_id": "case-test", "pdf_path": "fixture.pdf"}, config)
        assert paused["__interrupt__"][0].value["case_id"] == "case-test"
        assert paused["confirmed"] is False
        review = paused["identification"]
        review["requests"][0]["title"] = "Título corregido por la persona"
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        graph = build_graph(FakeExtractor(), FakeIdentifier(), saver)
        assert graph.get_state(config).next == ("review_identification",)
        final = graph.invoke(Command(resume=review), config)
        assert final["confirmed"] is True
        assert final["identification"]["requests"][0]["title"] == "Título corregido por la persona"
        assert graph.get_state(config).next == ()
    assert counts == {"read": 1, "identify": 1}


def test_graph_retry_after_ai_failure_preserves_extracted_pages(tmp_path, pages):
    counts = {"read": 0, "identify": 0}

    class FakeExtractor:
        def extract(self, path):
            counts["read"] += 1
            return pages

    class FailsOnceIdentifier:
        def identify(self, source_pages):
            counts["identify"] += 1
            if counts["identify"] == 1:
                raise DomainError("Fallo de conexión simulado")
            return make_identification(source_pages)

    config = {"configurable": {"thread_id": "retry-test"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "retry.sqlite")) as saver:
        graph = build_graph(FakeExtractor(), FailsOnceIdentifier(), saver)
        with pytest.raises(DomainError, match="simulado"):
            graph.invoke({"case_id": "retry-test", "pdf_path": "fixture.pdf"}, config)
        paused = graph.invoke(None, config)
        assert paused["phase"] == "review"
        assert paused["__interrupt__"]
    assert counts == {"read": 1, "identify": 2}
