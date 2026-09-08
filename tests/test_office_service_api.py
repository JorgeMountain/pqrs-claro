"""API, paquetes e integridad reales; renderizador doble explícito sin IA ni Word."""

import hashlib
import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient
from test_draft_service_api import FakeDraftEngine
from test_review_service_api import FakeReviewEngine, approve, assess, current, prepare, save

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.models import DomainError
from pqrs_claro.office_service import (
    LETTERHEAD_DEPARTMENT,
    LETTERHEAD_INSTITUTION,
    attachment_name,
)
from pqrs_claro.source_library import digest


class FakeOfficeRenderer:
    """Archivos reales con fidelidad simulada: esta suite no evalúa Word COM."""

    def __init__(self):
        self.calls = 0
        self.fail = False
        self.bad_fidelity = False
        self.bad_pdf = False
        self.block = False
        self.entered, self.release = threading.Event(), threading.Event()
        self.template_paths = []

    def __call__(self, document, output_dir, *, template_path=None):
        self.calls += 1
        self.template_paths.append(template_path)
        if self.block:
            self.block = False
            self.entered.set()
            assert self.release.wait(10)
        if self.fail:
            raise DomainError("Fallo ficticio de conversión.")
        word = Document()
        for request in document["requests"]:
            for paragraph in request["paragraphs"]:
                word.add_paragraph(paragraph["text"])
        word.save(output_dir / "oficio.docx")
        if self.bad_pdf:
            (output_dir / "oficio.pdf").write_bytes(b"Esto no es un PDF")
        else:
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((50, 80), "PDF ficticio para pruebas del servicio.")
                pdf.save(output_dir / "oficio.pdf")
        return dict(
            page_count=1,
            converter="test-double",
            verification={
                "docx_exact": not self.bad_fidelity,
                "pdf_text_match": not self.bad_fidelity,
                "request_count": len(document["requests"]),
                "paragraph_count": sum(
                    len(request["paragraphs"]) for request in document["requests"]
                ),
            },
        )


@pytest.fixture
def office_app(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pqrs_claro.office_service.pdf_capabilities",
        lambda: {
            "pdf_available": True,
            "pdf_engine": "test-double",
            "error": None,
        },
    )
    renderer = FakeOfficeRenderer()
    settings = Settings(data_dir=tmp_path / "data", model="test-model", api_key="")
    app = create_app(
        settings,
        draft_engine=FakeDraftEngine(),
        review_engine=FakeReviewEngine(),
        office_renderer=renderer,
    )
    with TestClient(app) as client:
        yield app, client, renderer, settings


def url(case, tail=""):
    return f"/api/cases/{case['id']}/office{tail}"


def approved_case(app, client, count=1):
    case, source, _ = prepare(app, client, count=count)
    for index in range(1, count + 1):
        row = assess(app, client, case, current(client, case, f"P{index}"))
        response = approve(client, case, row)
        assert response.status_code == 200, response.text
    return case, source


def metadata():
    return dict(
        institution="Institución ficticia",
        department="Unidad de prueba",
        city="Ciudad ficticia",
        issue_date="2026-09-08",
        office_number="",
        petition_number="",
        recipient="Destinatario ficticio",
        recipient_contact="",
        subject="Respuesta ficticia",
        signer_name="Firmante de prueba",
        signer_role="Cargo ficticio",
    )


def inputs(client, case, **changes):
    eligible = client.get(url(case)).json()
    assert eligible["eligible"], eligible
    body = dict(
        approval_snapshot_hash=eligible["approval_snapshot_hash"],
        metadata=metadata(),
        attachment_source_ids=[],
        prepared_by="Preparadora ficticia",
    )
    body.update(changes)
    return body


def preview(client, case, body):
    response = client.post(url(case, "/preview"), json=body)
    assert response.status_code == 200, response.text
    return response.json()


def generate(client, case, body):
    shown = preview(client, case, body)
    response = client.post(
        url(case, "/generate"), json={**body, "preview_hash": shown["preview_hash"]}
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait_office(app, client, case, run):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if case["id"] not in app.state.offices.active:
            return client.get(url(case, f"/runs/{run['id']}")).json()
        time.sleep(0.01)
    pytest.fail("La generación de prueba no terminó")


def test_ineligible_get_is_read_only_without_review_or_document_creation(office_app):
    app, client, renderer, settings = office_app
    from test_draft_service_api import prepared_case

    case, _ = prepared_case(app)
    response = client.get(url(case))
    assert response.status_code == 200
    result = response.json()
    assert not result["eligible"] and result["approval_snapshot_hash"] is None
    assert result["approved_count"] == 0 and len(result["blockers"]) == 2
    assert not app.state.reviews.store.list(case["id"]) and not app.state.offices.store.list(
        case["id"]
    )
    assert not (settings.data_dir / "oficios").exists() and renderer.calls == 0
    body = dict(approval_snapshot_hash="0" * 64, metadata=metadata(), prepared_by="Prueba")
    assert client.post(url(case, "/preview"), json=body).status_code == 409
    assert client.get("/api/cases/inexistente/office").status_code == 404


def test_preview_preserves_literal_text_and_is_not_generation(office_app):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client, count=2)
    before = app.state.reviews.approved(case["id"])
    body = inputs(client, case)
    shown = preview(client, case, body)
    assert shown["preview_hash"] == digest(shown["document"])
    assert shown["approval_snapshot_hash"] == before["snapshot_hash"]
    assert [r["request_id"] for r in shown["document"]["requests"]] == ["P1", "P2"]
    for snapshot, request in zip(before["requests"], shown["document"]["requests"], strict=True):
        assert [p["text"] for p in request["paragraphs"]] == [
            p["text"] for p in snapshot["review"]["paragraphs"]
        ]
    assert shown["document"]["metadata"]["signer_name"] == "Firmante de prueba"
    assert renderer.calls == 0 and not (settings.data_dir / "oficios").exists()
    assert app.state.reviews.approved(case["id"]) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("signer_name", " "),
        ("signer_role", ""),
        ("issue_date", "ayer"),
        ("institution", "Entidad\x00inválida"),
        ("approval_note", "dato interno"),
    ],
)
def test_metadata_requires_explicit_values_and_rejects_extra_or_xml_controls(
    office_app, field, value
):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    body["metadata"][field] = value
    assert client.post(url(case, "/preview"), json=body).status_code == 422
    assert not app.state.offices.store.list(case["id"]) and not renderer.calls


def test_generate_requires_current_preview_hash(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    shown = preview(client, case, body)
    body["metadata"]["subject"] = "Asunto cambiado"
    response = client.post(
        url(case, "/generate"), json={**body, "preview_hash": shown["preview_hash"]}
    )
    assert response.status_code == 409 and not renderer.calls


def test_actual_files_zip_selected_attachment_and_private_manifest(office_app):
    app, client, renderer, settings = office_app
    case, source = approved_case(app, client, count=2)
    before = app.state.reviews.approved(case["id"])
    body = inputs(client, case, attachment_source_ids=[source["id"]])
    run = wait_office(app, client, case, generate(client, case, body))
    assert run["status"] == "ready", run
    assert run["attachment_count"] == 1 and run["page_count"] == 1 and renderer.calls == 1
    assert run["converter"] == "test-double" and len(run["files"]) == 3
    assert not any(key.startswith("_") for key in run)
    responses = {}
    for kind in ("docx", "pdf", "zip"):
        response = client.get(url(case, f"/runs/{run['id']}/files/{kind}"))
        assert response.status_code == 200 and response.headers["content-disposition"].startswith(
            "attachment;"
        )
        item = next(f for f in run["files"] if f["kind"] == kind)
        assert (
            len(response.content) == item["size"]
            and hashlib.sha256(response.content).hexdigest() == item["sha256"]
        )
        responses[kind] = response.content
    with zipfile.ZipFile(BytesIO(responses["zip"])) as archive:
        assert len(archive.namelist()) == 3
        assert set(archive.namelist()) == {"oficio.docx", "oficio.pdf", "anexos/01_norma.txt"}
        assert (
            archive.read("anexos/01_norma.txt")
            == app.state.library.original(source["id"]).read_bytes()
        )
        assert archive.read("oficio.docx") == responses["docx"]
        assert archive.read("oficio.pdf") == responses["pdf"]
    folder = settings.data_dir / "oficios" / case["id"] / run["id"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["approved"] == before and manifest["preview_hash"] == run["preview_hash"]
    assert app.state.reviews.approved(case["id"]) == before
    page = client.get(url(case, f"/runs/{run['id']}/pages/1"))
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert page.headers["x-frame-options"] == "DENY"


def test_same_current_input_reuses_files_and_new_metadata_creates_version(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    before = app.state.reviews.approved(case["id"])
    body = inputs(client, case)
    first = wait_office(app, client, case, generate(client, case, body))
    assert generate(client, case, body)["id"] == first["id"] and renderer.calls == 1
    revised = deepcopy(body)
    revised["metadata"]["office_number"] = "QA-SEGUNDA-VERSION"
    second = wait_office(app, client, case, generate(client, case, revised))
    assert second["status"] == "ready" and second["id"] != first["id"] and renderer.calls == 2
    assert client.get(url(case, f"/runs/{first['id']}/files/pdf")).status_code == 200
    assert app.state.reviews.approved(case["id"]) == before
    result = client.get(url(case)).json()
    assert result["latest"]["id"] == second["id"] and len(result["history"]) == 2


def test_concurrent_generation_reuses_pending_attempt_and_rejects_different_input(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    shown = preview(client, case, body)
    posted = {**body, "preview_hash": shown["preview_hash"]}
    renderer.block = True
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(lambda _: client.post(url(case, "/generate"), json=posted), range(2))
            )
        assert all(r.status_code == 202 for r in responses)
        assert responses[0].json()["id"] == responses[1].json()["id"]
        assert renderer.entered.wait(5)
        changed = deepcopy(body)
        changed["metadata"]["subject"] = "Otro asunto"
        changed_preview = preview(client, case, changed)
        assert (
            client.post(
                url(case, "/generate"),
                json={**changed, "preview_hash": changed_preview["preview_hash"]},
            ).status_code
            == 409
        )
    finally:
        renderer.release.set()
    assert wait_office(app, client, case, responses[0].json())["status"] == "ready"
    assert renderer.calls == 1


@pytest.mark.parametrize("mode", ["fail", "bad_fidelity", "bad_pdf"])
def test_conversion_or_fidelity_failure_never_enables_download_and_can_retry(office_app, mode):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    setattr(renderer, mode, True)
    first = wait_office(app, client, case, generate(client, case, body))
    assert first["status"] == "failed" and first["error"], first
    assert client.get(url(case, f"/runs/{first['id']}/files/pdf")).status_code == 409
    setattr(renderer, mode, False)
    second = wait_office(app, client, case, generate(client, case, body))
    assert second["status"] == "ready" and second["id"] != first["id"]


@pytest.mark.parametrize("filename", ["oficio.docx", "oficio.pdf", "entrega.zip", "manifest.json"])
def test_tampered_artifact_blocks_all_downloads_and_staleness_does_not_revert(office_app, filename):
    app, client, _, settings = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    ready = wait_office(app, client, case, generate(client, case, body))
    path = settings.data_dir / "oficios" / case["id"] / ready["id"] / filename
    original = path.read_bytes()
    path.write_bytes(original + b"alterado")
    stale = client.get(url(case, f"/runs/{ready['id']}")).json()
    assert stale["status"] == "stale" and stale["stale"]
    assert client.get(url(case, f"/runs/{ready['id']}/files/pdf")).status_code == 409
    assert client.get(url(case, f"/runs/{ready['id']}/pages/1")).status_code == 409
    path.write_bytes(original)
    assert client.get(url(case, f"/runs/{ready['id']}")).json()["stale"]
    new = wait_office(app, client, case, generate(client, case, body))
    assert new["status"] == "ready" and new["id"] != ready["id"]


def test_new_edit_invalidates_office_preview_generation_and_download(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    shown = preview(client, case, body)
    ready = wait_office(app, client, case, generate(client, case, body))
    row = current(client, case)
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] += " Texto que requiere una nueva aprobación."
    assert save(client, case, row, paragraphs=paragraphs).status_code == 200
    assert client.get(url(case)).json()["eligible"] is False
    assert client.post(url(case, "/preview"), json=body).status_code == 409
    assert (
        client.post(
            url(case, "/generate"), json={**body, "preview_hash": shown["preview_hash"]}
        ).status_code
        == 409
    )
    assert client.get(url(case, f"/runs/{ready['id']}/files/zip")).status_code == 409
    assert renderer.calls == 1


def test_edit_during_render_never_publishes_old_approved_version(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    renderer.block = True
    try:
        running = generate(client, case, body)
        assert renderer.entered.wait(5)
        row = current(client, case)
        paragraphs = deepcopy(row["paragraphs"])
        paragraphs[0]["text"] += " Cambió durante la conversión."
        assert save(client, case, row, paragraphs=paragraphs).status_code == 200
    finally:
        renderer.release.set()
    finished = wait_office(app, client, case, running)
    assert finished["status"] == "stale" and not finished["files"]
    assert client.get(url(case, f"/runs/{running['id']}/files/docx")).status_code == 409


def test_original_corruption_blocks_before_or_after_generation(office_app):
    app, client, renderer, _ = office_app
    case, source = approved_case(app, client)
    body = inputs(client, case)
    ready = wait_office(app, client, case, generate(client, case, body))
    app.state.library.original(source["id"]).write_bytes(b"Original alterado fuera del catalogo")
    assert client.get(url(case)).json()["eligible"] is False
    assert client.post(url(case, "/preview"), json=body).status_code == 409
    assert client.get(url(case, f"/runs/{ready['id']}/files/pdf")).status_code == 409
    assert renderer.calls == 1


def test_cross_case_runs_unknown_types_and_page_bounds_are_rejected(office_app):
    app, client, _, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    run = wait_office(app, client, case, generate(client, case, body))
    from test_draft_service_api import prepared_case

    other, _ = prepared_case(app, with_map=False)
    for tail in (
        f"/runs/{run['id']}",
        f"/runs/{run['id']}/files/pdf",
        f"/runs/{run['id']}/pages/1",
    ):
        assert client.get(url(other, tail)).status_code == 404
    assert client.get(url(case, f"/runs/{run['id']}/files/manifest")).status_code == 404
    # Se usa otra creación de fuente global en el caso anterior: el oficio viejo ya
    # puede quedar obsoleto; comprueba límites sobre una nueva versión aprobada aislada.
    assert client.get(url(case, "/runs/no-existe/files/pdf")).status_code == 404


def test_png_bounds_and_no_client_path_access(office_app):
    app, client, _, _ = office_app
    case, _ = approved_case(app, client)
    run = wait_office(app, client, case, generate(client, case, inputs(client, case)))
    assert client.get(url(case, f"/runs/{run['id']}/pages/0")).status_code == 404
    assert client.get(url(case, f"/runs/{run['id']}/pages/2")).status_code == 404
    assert client.get(url(case, "/runs/%2e%2e%2f%2e%2e/files/pdf")).status_code in {404, 422}


def test_missing_pdf_capability_rejected_before_job_but_preview_available(office_app, monkeypatch):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    shown = preview(client, case, body)
    monkeypatch.setattr(
        "pqrs_claro.office_service.pdf_capabilities",
        lambda: {
            "pdf_available": False,
            "pdf_engine": None,
            "error": "Conversor no disponible en prueba.",
        },
    )
    assert preview(client, case, body)["preview_hash"] == shown["preview_hash"]
    response = client.post(
        url(case, "/generate"), json={**body, "preview_hash": shown["preview_hash"]}
    )
    assert response.status_code == 422 and "Conversor" in response.text
    assert not app.state.offices.store.list(case["id"]) and not renderer.calls


def test_restart_preserves_ready_downloads_reuses_input_and_recovers_interrupted(office_app):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    first = wait_office(app, client, case, generate(client, case, body))
    second_renderer = FakeOfficeRenderer()
    reopened = create_app(settings, office_renderer=second_renderer)
    with TestClient(reopened) as second_client:
        assert second_client.get(url(case, f"/runs/{first['id']}/files/pdf")).status_code == 200
        assert generate(second_client, case, body)["id"] == first["id"]
        assert second_renderer.calls == 0
        revised = deepcopy(body)
        revised["metadata"]["office_number"] = "SIMULA-CORTE"
        run = generate(second_client, case, revised)
        run = wait_office(reopened, second_client, case, run)
        reopened.state.offices.store.update(case["id"], run["id"], status="generating")
    third = create_app(settings, office_renderer=FakeOfficeRenderer())
    with TestClient(third) as third_client:
        recovered = third_client.get(url(case, f"/runs/{run['id']}")).json()
        assert recovered["status"] == "failed" and "interrumpió" in recovered["error"]
        retry = wait_office(third, third_client, case, generate(third_client, case, revised))
        assert retry["status"] == "ready" and retry["id"] != run["id"]


def test_attachment_must_be_cited_unique_and_within_total_size(office_app, monkeypatch):
    app, client, _, _ = office_app
    case, source = approved_case(app, client)
    body = inputs(client, case)
    body["attachment_source_ids"] = ["no-citado"]
    assert client.post(url(case, "/preview"), json=body).status_code == 422
    body["attachment_source_ids"] = [source["id"], source["id"]]
    assert client.post(url(case, "/preview"), json=body).status_code == 422
    body["attachment_source_ids"] = [source["id"]]
    monkeypatch.setattr("pqrs_claro.office_service.MAX_ATTACHMENTS_BYTES", 1)
    assert client.post(url(case, "/preview"), json=body).status_code == 422


def test_zip_names_are_safe_and_collision_free():
    inputs = ["../../norma.txt", "C:\\secret\\norma.txt", "..\\..\\norma.txt", "\x00nombre?.txt"]
    names = [attachment_name(i, name) for i, name in enumerate(inputs, 1)]
    assert len(set(names)) == 4
    assert all(
        name.startswith("anexos/")
        and len(name.split("/")) == 2
        and ".." not in name
        and "\\" not in name
        and "\x00" not in name
        for name in names
    )


def test_unexpected_renderer_error_does_not_expose_raw_data(office_app):
    app, client, _, _ = office_app
    case, _ = approved_case(app, client)

    def fail(*_):
        raise RuntimeError("secret-internal-payload")

    app.state.offices.renderer = fail
    failed = wait_office(app, client, case, generate(client, case, inputs(client, case)))
    assert failed["status"] == "failed" and "secret-internal" not in str(failed)


def test_renderer_cannot_mutate_canonical_preview_before_publication(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)

    def mutate(document, output_dir):
        result = renderer(document, output_dir)
        document["requests"][0]["paragraphs"][0]["text"] = "Texto sustituido durante la generación."
        return result

    app.state.offices.renderer = mutate
    run = wait_office(app, client, case, generate(client, case, inputs(client, case)))
    assert run["status"] == "failed" and "documento cambió" in run["error"]
    assert client.get(url(case, f"/runs/{run['id']}/files/docx")).status_code == 409


def test_reuse_finds_ready_version_older_than_twenty_history_rows(office_app):
    app, client, renderer, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    ready = wait_office(app, client, case, generate(client, case, body))
    original = app.state.offices.store.get(case["id"], ready["id"])
    for number in range(21):
        record = deepcopy(original)
        record.update(
            id=uuid4().hex,
            input_hash=digest({"test_later_attempt": number}),
            status="failed",
            files=[],
            error="Registro posterior simulado para historial.",
        )
        app.state.offices.store.create(record)
    history = client.get(url(case)).json()["history"]
    assert len(history) == 20 and ready["id"] not in {item["id"] for item in history}
    assert generate(client, case, body)["id"] == ready["id"] and renderer.calls == 1


def test_final_publication_serializes_against_review_edit_and_then_blocks_download(
    office_app, monkeypatch
):
    app, client, _, _ = office_app
    case, _ = approved_case(app, client)
    body = inputs(client, case)
    row = current(client, case)
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] += " Edición concurrente al publicar."
    start_writer, writer_attempted, writer_finished = (threading.Event() for _ in range(3))
    edit_result, publication = [], []
    original_check = app.state.offices._ensure_current
    original_update = app.state.offices.store.update
    checks = 0

    def writer():
        assert start_writer.wait(5)
        writer_attempted.set()
        edit_result.append(
            app.state.reviews.edit(
                case["id"],
                "P1",
                dict(
                    revision=row["revision"],
                    paragraphs=paragraphs,
                    pending_resolutions=[],
                    edited_by="Revisora concurrente ficticia",
                ),
            )
        )
        writer_finished.set()

    def check(run, sources):
        nonlocal checks
        original_check(run, sources)
        checks += 1
        if checks == 3:
            start_writer.set()
            assert writer_attempted.wait(5)
            # El escritor ya intenta guardar. Debe esperar mientras la aprobación
            # comprobada se publica dentro de la misma sección protegida.
            writer_finished.wait(0.2)

    def update(case_id, run_id, **changes):
        if changes.get("status") == "ready":
            publication.append(writer_finished.is_set())
        return original_update(case_id, run_id, **changes)

    monkeypatch.setattr(app.state.offices, "_ensure_current", check)
    monkeypatch.setattr(app.state.offices.store, "update", update)
    thread = threading.Thread(target=writer)
    thread.start()
    try:
        running = generate(client, case, body)
        assert writer_finished.wait(8)
        final = wait_office(app, client, case, running)
    finally:
        start_writer.set()
        thread.join(timeout=5)
    assert publication == [False] and edit_result[0]["status"] == "editing"
    assert final["status"] == "stale"
    assert client.get(url(case, f"/runs/{running['id']}/files/pdf")).status_code == 409


def activate_letterhead(settings, label="Primera versión"):
    folder = settings.data_dir / "templates"
    folder.mkdir(exist_ok=True)
    path = folder / "institucional.docx"
    document = Document()
    document.sections[0].header.paragraphs[0].text = label
    document.save(path)
    registry = dict(
        version=1,
        id="ingenieria-udea",
        name="Membrete de Ingeniería",
        filename=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_url="https://drive.google.com/file/d/plantilla-ficticia/view",
    )
    (folder / "active.json").write_text(json.dumps(registry), encoding="utf-8")
    return path, {k: v for k, v in registry.items() if k not in {"version", "filename"}}


def institutional_inputs(client, case):
    body = inputs(client, case)
    body["metadata"].update(institution=LETTERHEAD_INSTITUTION, department=LETTERHEAD_DEPARTMENT)
    return body


def assert_no_local_path(value, private_root):
    if isinstance(value, dict):
        for item in value.values():
            assert_no_local_path(item, private_root)
    elif isinstance(value, list):
        for item in value:
            assert_no_local_path(item, private_root)
    elif isinstance(value, str):
        assert str(private_root) not in value and private_root.as_posix() not in value


def test_active_letterhead_defaults_preview_and_manifest_keep_only_public_identity(office_app):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client)
    before = app.state.reviews.approved(case["id"])
    template_path, public = activate_letterhead(settings)
    available = client.get(url(case)).json()
    assert available["letterhead"] == public
    assert available["defaults"]["institution"] == LETTERHEAD_INSTITUTION
    assert available["defaults"]["department"] == LETTERHEAD_DEPARTMENT
    body = institutional_inputs(client, case)
    shown = preview(client, case, body)
    assert shown["document"]["letterhead"] == public
    assert (
        shown["document"]["requests"][0]["paragraphs"][0]["text"]
        == (before["requests"][0]["review"]["paragraphs"][0]["text"])
    )
    ready = wait_office(app, client, case, generate(client, case, body))
    assert ready["status"] == "ready" and ready["letterhead"] == public
    assert ready["office_version"] == 2
    assert renderer.template_paths == [template_path.resolve()]
    folder = settings.data_dir / "oficios" / case["id"] / ready["id"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["letterhead"] == public and manifest["document"]["letterhead"] == public
    assert manifest["office_version"] == 2
    assert_no_local_path([available, shown, ready, manifest["letterhead"]], settings.data_dir)
    assert generate(client, case, body)["id"] == ready["id"] and renderer.calls == 1
    assert app.state.reviews.approved(case["id"]) == before
    assert client.get(url(case)).json()["history"][0]["letterhead"] == public


@pytest.mark.parametrize("field", ["institution", "department"])
def test_incompatible_institution_is_rejected_with_active_letterhead(office_app, field):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client)
    activate_letterhead(settings)
    body = institutional_inputs(client, case)
    body["metadata"][field] = "Otra entidad"
    response = client.post(url(case, "/preview"), json=body)
    assert response.status_code == 422 and "Universidad de Antioquia" in response.text
    assert not renderer.calls and not app.state.offices.store.list(case["id"])


def test_letterhead_change_requires_new_preview_and_never_reuses_previous_files(office_app):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client)
    activate_letterhead(settings)
    body = institutional_inputs(client, case)
    old_preview = preview(client, case, body)
    first = wait_office(app, client, case, generate(client, case, body))
    _, updated = activate_letterhead(settings, "Segunda versión")
    response = client.post(
        url(case, "/generate"), json={**body, "preview_hash": old_preview["preview_hash"]}
    )
    assert response.status_code == 409 and renderer.calls == 1
    changed_preview = preview(client, case, body)
    assert changed_preview["preview_hash"] != old_preview["preview_hash"]
    second = wait_office(app, client, case, generate(client, case, body))
    assert second["status"] == "ready" and second["id"] != first["id"]
    assert second["letterhead"] == updated and renderer.calls == 2
    for tail in ("files/docx", "files/pdf", "files/zip", "pages/1"):
        assert client.get(url(case, f"/runs/{first['id']}/{tail}")).status_code == 409
    assert client.get(url(case, f"/runs/{second['id']}/files/pdf")).status_code == 200


@pytest.mark.parametrize("mode", ["activate", "remove"])
def test_switching_between_neutral_and_letterhead_stales_existing_versions(office_app, mode):
    app, client, _, settings = office_app
    case, _ = approved_case(app, client)
    if mode == "remove":
        activate_letterhead(settings)
        body = institutional_inputs(client, case)
    else:
        body = inputs(client, case)
        assert client.get(url(case)).json()["letterhead"] is None
    first = wait_office(app, client, case, generate(client, case, body))
    if mode == "remove":
        (settings.data_dir / "templates" / "active.json").unlink()
    else:
        activate_letterhead(settings)
    result = client.get(url(case)).json()
    assert result["latest"]["stale"] and result["latest"]["status"] == "stale"
    assert client.get(url(case, f"/runs/{first['id']}/files/pdf")).status_code == 409
    assert client.get(url(case, f"/runs/{first['id']}/pages/1")).status_code == 409


def test_letterhead_changed_during_background_render_never_publishes_downloads(office_app):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client)
    activate_letterhead(settings)
    body = institutional_inputs(client, case)
    renderer.block = True
    try:
        running = generate(client, case, body)
        assert renderer.entered.wait(5)
        activate_letterhead(settings, "Membrete cambiado durante la conversión")
    finally:
        renderer.release.set()
    result = wait_office(app, client, case, running)
    assert result["status"] == "stale" and not result["files"]
    assert client.get(url(case, f"/runs/{running['id']}/files/pdf")).status_code == 409


@pytest.mark.parametrize("mode", ["corrupt_bytes", "invalid_registry"])
def test_invalid_active_template_blocks_api_without_fallback_or_private_path(office_app, mode):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client)
    path, _ = activate_letterhead(settings)
    body = institutional_inputs(client, case)
    shown = preview(client, case, body)
    ready = wait_office(app, client, case, generate(client, case, body))
    if mode == "corrupt_bytes":
        path.write_bytes(path.read_bytes() + b"contenido cambiado")
    else:
        (path.parent / "active.json").write_text('{"filename":"../../private.docx"}')
    responses = [
        client.get(url(case)),
        client.post(url(case, "/preview"), json=body),
        client.post(url(case, "/generate"), json={**body, "preview_hash": shown["preview_hash"]}),
        client.get(url(case, f"/runs/{ready['id']}/files/pdf")),
        client.get(url(case, f"/runs/{ready['id']}/pages/1")),
    ]
    assert all(r.status_code == 422 for r in responses)
    assert all("membrete" in r.text for r in responses)
    assert_no_local_path([r.json() for r in responses], settings.data_dir)
    assert renderer.calls == 1


def test_old_run_without_format_identity_is_stale_under_current_renderer(office_app):
    app, client, _, _ = office_app
    case, _ = approved_case(app, client)
    ready = wait_office(app, client, case, generate(client, case, inputs(client, case)))
    old = app.state.offices.store.get(case["id"], ready["id"])
    old.pop("office_version")
    old.pop("letterhead")
    with app.state.offices.store.connect() as connection:
        connection.execute("UPDATE office_runs SET body=? WHERE id=?", (json.dumps(old), old["id"]))
    assert app.state.offices._files_intact(old)
    projected = client.get(url(case, f"/runs/{old['id']}")).json()
    assert projected["stale"] and projected["letterhead"] is None
    assert projected["office_version"] == 1
    assert client.get(url(case, f"/runs/{old['id']}/files/pdf")).status_code == 409


@pytest.mark.parametrize("boundary", ["during_preview", "before_generation_lock"])
def test_template_is_rechecked_after_preview_and_before_accepting_job(
    office_app, monkeypatch, boundary
):
    app, client, renderer, settings = office_app
    case, _ = approved_case(app, client)
    activate_letterhead(settings)
    body = institutional_inputs(client, case)
    shown = preview(client, case, body)
    if boundary == "during_preview":
        from pqrs_claro import office_service

        original = office_service.build_document

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            activate_letterhead(settings, "Cambio mientras se compone la vista")
            return result

        monkeypatch.setattr(office_service, "build_document", changed)
        response = client.post(url(case, "/preview"), json=body)
    else:
        original = app.state.offices._preview

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            activate_letterhead(settings, "Cambio antes de aceptar la generación")
            return result

        monkeypatch.setattr(app.state.offices, "_preview", changed)
        response = client.post(
            url(case, "/generate"), json={**body, "preview_hash": shown["preview_hash"]}
        )
    assert response.status_code == 409 and "membrete" in response.text
    assert not app.state.offices.store.list(case["id"]) and renderer.calls == 0


def test_restart_reuses_only_files_with_the_current_letterhead(office_app):
    app, client, _, settings = office_app
    case, _ = approved_case(app, client)
    activate_letterhead(settings)
    body = institutional_inputs(client, case)
    ready = wait_office(app, client, case, generate(client, case, body))
    renderer = FakeOfficeRenderer()
    reopened = create_app(settings, office_renderer=renderer)
    with TestClient(reopened) as second_client:
        assert second_client.get(url(case, f"/runs/{ready['id']}/files/pdf")).status_code == 200
        assert generate(second_client, case, body)["id"] == ready["id"]
        assert renderer.calls == 0
        activate_letterhead(settings, "Versión posterior al reinicio")
        assert second_client.get(url(case, f"/runs/{ready['id']}/files/pdf")).status_code == 409
        replacement = wait_office(
            reopened, second_client, case, generate(second_client, case, body)
        )
        assert replacement["status"] == "ready" and replacement["id"] != ready["id"]
        assert renderer.calls == 1
