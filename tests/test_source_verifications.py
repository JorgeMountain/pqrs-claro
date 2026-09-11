"""Aplicaciones por pregunta, citas inmutables y separación entre atribución e IA."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError
from pqrs_claro.source_library import make_chunks
from pqrs_claro.storage import Conflict

CHECK_KEY = "check-" + "a" * 24


def api_check(source=None, *, reason="applicability", stage="evidence"):
    return {
        "check_key": CHECK_KEY, "reason_code": reason, "stage": stage,
        "state": "confirmation_pending", "scope_key": "test-request-scope",
        "linked_source_ids": [source["id"]] if source else [],
        "source_versions": [{
            "source_id": source["id"], "document_id": source["document_id"],
            "version": source["version"], "sha256": source["sha256"],
            "extraction_revision": source.get("extraction_revision"),
        }] if source else [],
    }


@pytest.fixture
def environment(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, api_key="", model="test-model"),
                     extractor=PDFExtractor(), source_extractor=PDFExtractor())
    store = app.state.store
    case = store.create("peticion.pdf", b"%PDF-fixture-no-extraction")
    requests = [
        {"id": "P1", "label": "1", "title": "Profesor", "description": "Profesor en 2015-1.",
         "parent_id": None, "source_refs": []},
        {"id": "P2", "label": "a", "title": "Confirmación", "description": "Confirmar su nombre.",
         "parent_id": "P1", "source_refs": []},
        {"id": "P3", "label": "2", "title": "Correo", "description": "Indicar correo de contacto.",
         "parent_id": None, "source_refs": []},
    ]
    case = store.update(case["id"], status="confirmed", identification={
        "subject": "Prácticas", "requests": requests, "document_date": "2026-01-02",
    })
    source = app.state.library.add(
        "oficio.txt", "Según el plan de 2015-1, la profesora fue Ana Pérez.\n"
        "El oficio declara que se contrastó ese plan con el correo del departamento.".encode(),
        title="Respuesta anterior", category="institutional_norm", origin="Fuente de prueba",
    )
    detail = app.state.library.get(source["id"], case["id"])
    chunk = make_chunks(detail["source"], detail["pages"])[0]
    passage = {key: chunk[key] for key in ("chunk_id", "page", "line_start", "line_end", "quote")}
    with TestClient(app) as client:
        yield app, client, case, source, passage


def human_payload(case, source, passage):
    return {
        "version": case["version"], "fact": "Ana Pérez dictó la asignatura en 2015-1.",
        "source_id": source["id"], "passage": passage,
        "basis": "Cotejé el nombre y periodo con el plan original que conserva el departamento.",
        "recorded_by": "María Ruiz, responsable de pruebas", "attributed_to": None,
        "scope": {"person": "Ana Pérez", "period": "2015-1", "subject": "Asignatura"},
        "request_ids": ["P1", "P2"],
    }


def create_human(environment):
    app, _, case, source, passage = environment
    return app.state.verifications.record_human(case["id"], **human_payload(case, source, passage))


def apply_record(environment, record, *, request_ids=None):
    app, _, case, _, _ = environment
    return app.state.verifications.apply(
        case["id"], record["id"], case["version"],
        request_ids=request_ids or ["P2"], check_key=CHECK_KEY,
        basis="La pregunta se refiere a la misma persona, asignatura y periodo de la comprobación.",
        recorded_by="María Ruiz", check_reason="applicability",
    )


def test_literal_passage_source_metadata_and_actor_are_server_owned(environment):
    app, client, case, source, passage = environment
    payload = human_payload(case, source, passage)
    fingerprint = app.state.verifications.fingerprint(case["id"])
    response = client.post(f"/api/cases/{case['id']}/verifications", json=payload)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["kind"] == "human_review"
    assert record["recording_method"] == "human_form"
    assert record["source_sha256"] == source["sha256"]
    assert record["version"] == source["version"]
    assert record["case_version"] == case["version"]
    assert app.state.verifications.active_applications(case) == []
    assert app.state.verifications.fingerprint(case["id"]) == fingerprint
    for forged in ({"kind": "antecedent_declared"}, {"recorded_at": "ayer"},
                   {"source_sha256": "hash-falso"}):
        response = client.post(f"/api/cases/{case['id']}/verifications", json=payload | forged)
        assert response.status_code == 422


@pytest.mark.parametrize("change", [
    {"quote": "El sistema certificó la respuesta."}, {"line_end": 500}, {"chunk_id": "C1"},
])
def test_fabricated_or_mislocated_passage_is_rejected(environment, change):
    app, _, case, source, passage = environment
    payload = human_payload(case, source, passage | change)
    with pytest.raises(DomainError):
        app.state.verifications.record_human(case["id"], **payload)
    assert app.state.verifications.list(case["id"])["records"] == []


def test_antecedent_is_attributed_not_human_and_never_auto_applied(environment):
    app, _, case, source, passage = environment
    verifications = app.state.verifications
    fingerprint = verifications.fingerprint(case["id"])
    record = verifications.record_antecedent(
        case, source, passage, "La respuesta declara un cotejo con el plan de 2015-1.",
        "El segundo renglón atribuye al oficio el contraste con el plan y correo.",
        attributed_to=None, request_ids=["P2"],
    )
    same_record = verifications.record_antecedent(
        case, source, passage, record["fact"], record["basis"], request_ids=["P2"],
    )
    assert same_record["id"] == record["id"]
    assert record["kind"] == "antecedent_declared"
    assert record["attributed_to"] is None
    assert verifications.active_applications(case) == []
    assert verifications.fingerprint(case["id"]) == fingerprint
    application = apply_record(environment, record)
    assert verifications.active_applications(case)[0]["record"]["kind"] == "antecedent_declared"
    assert application["verification_id"] == record["id"]


def test_changed_parent_reopens_only_affected_questions(environment):
    app, _, case, _, _ = environment
    record = create_human(environment)
    apply_record(environment, record, request_ids=["P2", "P3"])
    identification = copy.deepcopy(case["identification"])
    identification["requests"][0]["description"] = "Profesor en 2019-2."
    changed = app.state.store.update(case["id"], identification=identification)
    applications = app.state.verifications.active_applications(changed)
    assert len(applications) == 1
    assert applications[0]["request_ids"] == ["P3"]
    listed = app.state.verifications.list(case["id"])["applications"][0]
    assert listed["inactive_request_ids"] == ["P2"]
    assert listed["active_request_ids"] == ["P3"]


@pytest.mark.parametrize("change", [
    {"extraction_revision": 2}, {"sha256": "changed"}, {"version": 2},
])
def test_changed_document_or_extraction_reopens_application(environment, change):
    app, _, case, source, _ = environment
    record = create_human(environment)
    apply_record(environment, record)
    assert app.state.verifications.active_applications(case)
    with app.state.library.connect() as conn:
        body = json.loads(conn.execute("SELECT body FROM sources WHERE id=?", (source["id"],))
                          .fetchone()[0])
        body.update(change)
        conn.execute("UPDATE sources SET body=? WHERE id=?", (json.dumps(body), source["id"]))
    assert app.state.verifications.active_applications(case) == []
    assert app.state.verifications.get(record["id"])["source_sha256"] == source["sha256"]


def test_source_collection_access_is_checked_before_recording_and_reusing(environment):
    app, _, case, source, _ = environment
    record = create_human(environment)
    apply_record(environment, record)
    with app.state.library.connect() as conn:
        body = json.loads(conn.execute("SELECT body FROM sources WHERE id=?", (source["id"],))
                          .fetchone()[0])
        body["collection_id"] = "restricted"
        conn.execute("UPDATE sources SET body=? WHERE id=?", (json.dumps(body), source["id"]))
    assert app.state.verifications.active_applications(case) == []
    with pytest.raises(DomainError, match="ámbito"):
        create_human(environment)


def test_revocation_is_append_only_and_invalidates_applications(environment):
    app, _, case, _, _ = environment
    record = create_human(environment)
    application = apply_record(environment, record)
    verifications = app.state.verifications
    fingerprint = verifications.fingerprint(case["id"])
    verifications.revoke(case["id"], "verification", record["id"], case["version"],
                         reason="El periodo requiere corregirse.", recorded_by="María Ruiz")
    assert verifications.get(record["id"]) == record
    assert verifications.active_applications(case) == []
    assert verifications.fingerprint(case["id"]) != fingerprint
    with verifications.connect() as conn:
        assert conn.execute("SELECT count(*) FROM verification_events").fetchone()[0] == 1
        stored_id = conn.execute("SELECT id FROM verification_applications").fetchone()[0]
        assert stored_id == application["id"]


def test_case_version_conflict_and_new_case_need_fresh_application(environment):
    app, _, case, source, passage = environment
    payload = human_payload(case, source, passage)
    with pytest.raises(Conflict):
        app.state.verifications.record_human(case["id"], **(payload | {"version": 1}))
    record = create_human(environment)
    apply_record(environment, record)
    another = app.state.store.create("otro.pdf", b"%PDF-another")
    another = app.state.store.update(another["id"], status="confirmed",
                                    identification=case["identification"])
    assert app.state.verifications.list(another["id"])["records"]
    assert app.state.verifications.active_applications(another) == []


def test_application_api_requires_real_current_check_and_matching_source(environment, monkeypatch):
    app, client, case, source, _ = environment
    record = create_human(environment)
    check = api_check(source)
    run = {"status": "ready", "stale": False,
           "results": [{"request_id": "P2", "checks": [check]}]}
    monkeypatch.setattr(app.state.sources, "get", lambda case_id: run)
    url = f"/api/cases/{case['id']}/verifications/{record['id']}/applications"
    payload = {"version": case["version"], "request_ids": ["P2"], "check_key": CHECK_KEY,
               "basis": "Corresponde a la misma pregunta y periodo.", "recorded_by": "María"}
    response = client.post(url, json=payload)
    assert response.status_code == 201, response.text
    run["stale"] = True
    assert client.post(url, json=payload).status_code == 409
    run["stale"] = False
    assert client.post(url, json=payload | {"request_ids": ["P3"]}).status_code == 422
    check["linked_source_ids"] = ["another-source"]
    assert client.post(url, json=payload).status_code == 422


@pytest.mark.parametrize("reason", ["extraction_error", "partial_extraction", "document_missing"])
def test_written_confirmation_does_not_close_missing_file_or_reading_error(
    environment, monkeypatch, reason,
):
    app, client, case, _, _ = environment
    record = app.state.verifications.record_human(
        case["id"], case["version"], fact="Yo impartí esa asignatura.",
        basis="Lo conozco porque fui la docente responsable en ese semestre.",
        recorded_by="Ana Pérez", request_ids=["P2"],
    )
    check = {"check_key": CHECK_KEY, "reason_code": reason, "linked_source_ids": []}
    monkeypatch.setattr(app.state.sources, "get", lambda _: {
        "status": "ready", "stale": False,
        "results": [{"request_id": "P2", "checks": [check]}],
    })
    response = client.post(
        f"/api/cases/{case['id']}/verifications/{record['id']}/applications",
        json={"version": case["version"], "request_ids": ["P2"], "check_key": CHECK_KEY,
              "basis": "Confirmación escrita.", "recorded_by": "Ana Pérez"},
    )
    assert response.status_code == 422
    assert app.state.verifications.active_applications(case) == []


def test_written_firsthand_confirmation_can_be_applied_to_specific_fact(environment, monkeypatch):
    app, client, case, _, _ = environment
    response = client.post(f"/api/cases/{case['id']}/verifications", json={
        "version": case["version"], "fact": "Yo impartí esa asignatura en 2015-1.",
        "basis": "Fui la profesora responsable; contrasté la fecha con mi agenda docente.",
        "recorded_by": "Ana Pérez", "request_ids": ["P2"],
    })
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["source_id"] is None and record["passage"] is None
    monkeypatch.setattr(app.state.sources, "get", lambda _: {
        "status": "ready", "stale": False, "results": [{"request_id": "P2", "checks": [
            api_check(reason="fact_confirmation"),
        ]}],
    })
    response = client.post(
        f"/api/cases/{case['id']}/verifications/{record['id']}/applications",
        json={"version": case["version"], "request_ids": ["P2"], "check_key": CHECK_KEY,
              "basis": "El hecho confirmado responde al mismo periodo solicitado.",
              "recorded_by": "Ana Pérez"},
    )
    assert response.status_code == 201, response.text


def test_modified_original_bytes_cannot_be_used_to_apply_verification(environment):
    app, _, case, source, _ = environment
    record = create_human(environment)
    original = app.state.library.original(source["id"], case["id"])
    original.write_bytes(b"bytes changed after the review")
    with pytest.raises(DomainError, match="original cambió"):
        apply_record(environment, record)
    assert app.state.verifications.active_applications(case) == []


@pytest.mark.parametrize("reason,stage", [
    ("provenance", "evidence"), ("issued_version", "evidence"),
    ("transcription", "evidence"), ("fact_confirmation", "fulfillment"),
])
def test_declared_antecedent_cannot_replace_document_control_or_future_action(
    environment, monkeypatch, reason, stage,
):
    app, client, case, source, passage = environment
    record = app.state.verifications.record_antecedent(
        case, source, passage, "El oficio declara que se cotejó el plan.",
        "El segundo renglón menciona ese contraste.", request_ids=["P2"],
    )
    monkeypatch.setattr(app.state.sources, "get", lambda _: {
        "status": "ready", "stale": False, "results": [{"request_id": "P2", "checks": [{
            "check_key": CHECK_KEY, "reason_code": reason, "linked_source_ids": [source["id"]],
            "stage": stage,
        }]}],
    })
    response = client.post(
        f"/api/cases/{case['id']}/verifications/{record['id']}/applications",
        json={"version": case["version"], "request_ids": ["P2"], "check_key": CHECK_KEY,
              "basis": "Intento de reutilización insuficiente para este control.",
              "recorded_by": "Persona de pruebas"},
    )
    assert response.status_code == 422
    assert app.state.verifications.active_applications(case) == []
