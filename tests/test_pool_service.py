from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pqrs_claro.management import ManagementStore
from pqrs_claro.pool_api import pool_router
from pqrs_claro.pool_service import PoolService
from pqrs_claro.storage import CaseStore, Conflict


@pytest.fixture
def setup_pool(tmp_path):
    store = CaseStore(tmp_path)
    ManagementStore(store)
    pool = PoolService(store)
    case = store.create("recepcion.pdf", b"pdf", receipt={"workflow": "fiaga", "subject": "Caso"})
    pool.enroll(case["id"])
    return pool, case["id"]


def snapshot(*gaps):
    return {"text": "Borrador con los puntos disponibles.", "checks": {},
            "requests": [dict(id=f"P{i}", text=f"Punto {i}", gap=gap, gaps=[gap] if gap else [],
                              answer="Respuesta parcial") for i, gap in enumerate(gaps, 1)]}


def task(request_id, department, manager=None):
    return dict(request_id=request_id, department=department,
                instruction="Aportar el documento solicitado", manager_id=manager)


def test_queue_turns_revision_attachments_and_targeted_return(setup_pool):
    pool, cid = setup_pool
    initial = pool.import_admin_review(cid, "admin", 1, snapshot("Archivo", "", "Firma"))
    with pytest.raises(ValueError):
        pool.publish(cid, "admin", initial["revision"], [task("P1", "Registro")])
    with pytest.raises(Conflict):
        pool.publish(cid, "gestor-1", initial["revision"], [])
    with pytest.raises(ValueError):
        pool.publish(cid, "admin", initial["revision"], [task("P1", "Registro", "desconocido")])
    state = pool.publish(cid, "admin", initial["revision"],
                         [task("P1", "Registro"), task("P3", "Secretaría", "gestor-2")])
    first, second = (t["id"] for t in state["tasks"])
    assert [t["status"] for t in state["tasks"]] == ["available", "waiting"]
    assert pool.list()[0]["task"]["id"] == first
    with pytest.raises(Conflict):
        pool.claim(cid, second, "gestor-2", state["revision"])
    revision = state["revision"]

    def take(actor):
        try:
            PoolService(pool.store).claim(cid, first, actor, revision)
            return True
        except Conflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(workers.map(take, ("gestor-1", "gestor-2"))) == 1
    state = pool.get(cid)
    owner = state["tasks"][0]["owner_id"]
    with pytest.raises(Conflict):
        pool.complete(cid, first, owner, revision, "Texto obsoleto", [])
    with pytest.raises(Conflict):
        pool.complete(cid, first, "admin", state["revision"], "Texto", [])
    with pytest.raises(ValueError):
        pool.complete(cid, first, owner, state["revision"], " ", [])
    state = pool.complete(cid, first, owner, state["revision"], "",
                          [("archivo.txt", BytesIO(b"Anexo de ejemplo"))])
    assert state["tasks"][1]["status"] == "available"
    with pytest.raises(Conflict):
        pool.claim(cid, second, "gestor-1", state["revision"])
    state = pool.claim(cid, second, "gestor-2", state["revision"])
    scheduled = []
    pool.on_integration = scheduled.append
    state = pool.complete(cid, second, "gestor-2", state["revision"], "Firma revisada", [])
    assert scheduled == [cid]
    assert state["stage"] == "integration"
    revision, previous, tasks = PoolService(pool.store).integration_input(cid)
    assert previous["text"] == initial["draft"]
    file = tasks[0]["contributions"][0]["files"][0]
    assert file["text"] == "Anexo de ejemplo"
    assert pool.attachment(cid, file["id"]) == ("archivo.txt", b"Anexo de ejemplo")
    state = pool.set_integrated(cid, snapshot("", "", "Firma ilegible"), revision=revision)
    with pytest.raises(Conflict):
        pool.approve(cid, "admin", state["revision"])
    state = pool.publish(cid, "admin", state["revision"], [task("P3", "Secretaría")],
                         returned=True)
    assert len(state["tasks"]) == 3
    fix = state["tasks"][2]["id"]
    state = pool.claim(cid, fix, "gestor-1", state["revision"])
    state = pool.complete(cid, fix, "gestor-1", state["revision"], "Firma verificada", [])
    revision, previous, tasks = pool.integration_input(cid)
    assert [t["id"] for t in tasks] == [fix]
    assert previous["requests"][2]["gap"] == "Firma ilegible"
    state = pool.set_integrated(cid, snapshot("", "", ""), revision=revision)
    with pytest.raises(Conflict):
        pool.approve(cid, "gestor-1", state["revision"])
    state = pool.approve(cid, "admin", state["revision"])
    assert state["document_url"].endswith("/pool/document.docx")
    assert state["approved_at"] and len(state["tasks"]) == 3
    assert PoolService(pool.store).get(cid) == state
    with pytest.raises(Conflict):
        pool.publish(cid, "admin", state["revision"], [task("P1", "Registro")], returned=True)


def test_retry_legacy_and_receipt_recovery(setup_pool):
    pool, cid = setup_pool
    old = pool.store.create("legado.pdf", b"old")["id"]
    assert pool.get(old)["stage"] == "legacy"
    assert not pool.exists(old)
    with pytest.raises(Conflict):
        pool.start(old, "admin")
    missed = pool.store.create("nuevo.pdf", b"new", receipt={"workflow": "fiaga"})["id"]
    assert pool.unenrolled_receipts() == [missed]
    pool.enroll(missed)
    assert pool.pending_jobs() == []
    assert pool.get(missed)["stage"] == "admin_review"
    with pytest.raises(Conflict):
        pool.start(cid, "admin")
    state = pool.import_admin_review(cid, "admin", 1, snapshot(""))
    state = pool.publish(cid, "admin", state["revision"], [])
    assert state["stage"] == "final_review"
    assert pool.approve(cid, "admin", state["revision"])["stage"] == "approved"
    with pool.store.connect() as db:
        db.execute("INSERT INTO case_lifecycle VALUES (?,?,?)", (cid, 1, "hora"))
    assert cid not in {row["case_id"] for row in pool.list()}
    with pytest.raises(Conflict):
        pool.get(cid)
    with pool.store.connect() as db:
        db.execute("DELETE FROM cases WHERE id=?", (cid,))
    assert not pool.exists(cid)


def test_http_file_and_note_are_persisted_together(setup_pool):
    pool, cid = setup_pool
    app = FastAPI()
    app.include_router(pool_router(pool))
    pool.import_admin_review(cid, "admin", 1, snapshot("Certificación"))
    base = f"/api/cases/{cid}/pool"
    with TestClient(app) as client:
        route = client.post(base + "/publish", json=dict(
            revision=2, actor_id="admin", tasks=[task("P1", "Archivo")]))
        assert route.status_code == 200
        state = route.json()
        uri = base + "/tasks/" + state["tasks"][0]["id"]
        claim = client.post(uri + "/claim", json=dict(actor_id="gestor-1", revision=3))
        assert claim.status_code == 200
        complete = client.post(
            uri + "/complete",
            data={
                "actor_id": "gestor-1",
                "revision": 4,
                "note": "Revisado por Archivo\r\nCon firma",
            },
            files=[
                ("files", ("acta.txt", b"Doc 1", "text/plain")),
                ("files", ("firma.txt", b"Doc 2", "text/plain")),
            ],
        )
        assert complete.status_code == 200
        detail = client.get(base).json()
        assert detail["stage"] == "integration"
        contribution = detail["tasks"][0]["contributions"][0]
        assert contribution["note"] == "Revisado por Archivo\nCon firma"
        assert [client.get(f["url"]).content for f in contribution["files"]] == [b"Doc 1", b"Doc 2"]
        assert client.get("/api/pool").json()["items"][0]["task"] is None


def test_human_review_records_exact_changes_and_preserves_initial_draft(setup_pool):
    pool, cid = setup_pool
    before = snapshot("Falta firma", "")
    pool.import_admin_review(cid, "admin", 1, before)
    with pytest.raises(Conflict):
        pool.review_request(cid, "P1", "gestor-1", 2, "Cambio", [], "Motivo")
    with pytest.raises(ValueError):
        pool.review_request(cid, "P1", "admin", 2, "", [], "Sí")
    with pytest.raises(ValueError):
        pool.review_request(cid, "P1", "admin", 2, "La copia es legible.", [], " ")
    state = pool.review_request(cid, "P1", "admin", 2, "La copia es legible.", [],
                                "El ejemplar ya consta en el expediente.")
    assert state["initial_draft"] == before["text"]
    assert "La copia es legible." in state["draft"] and "Punto 2" in state["draft"]
    record = state["events"][-1]
    assert record["before"] == {"answer": "Respuesta parcial", "gaps": ["Falta firma"]}
    assert record["after"] == {"answer": "La copia es legible.", "gaps": []}
    assert state["requests"][0]["human_review"]["reason"] == record["reason"]
    assert state["requests"][1] == before["requests"][1]
    final = pool.publish(cid, "admin", state["revision"], [])
    with pytest.raises(Conflict):
        pool.review_request(cid, "P2", "admin", 2, "Otra", [], "Ortografía")
    revised = pool.review_request(cid, "P2", "admin", final["revision"], "", ["Adjuntar acta"],
                                  "Hace falta el acta de aprobación.")
    with pytest.raises(Conflict):
        pool.approve(cid, "admin", revised["revision"])
    returned = pool.publish(cid, "admin", revised["revision"], [task("P2", "Secretaría")],
                            returned=True)
    assert returned["stage"] == "pool"


def test_suggest_responsibles_endpoint_is_admin_only_and_read_only(tmp_path):
    from pqrs_claro.app import create_app
    from pqrs_claro.config import Settings

    class FakeRouting:
        def __init__(self):
            self.calls = []

        def suggest(self, case_context, items):
            self.calls.append((case_context, items))
            return {
                "suggestions": [
                    {
                        "index": 0,
                        "kind": "docente",
                        "responsible": "Docente: Carlos Andrés Trujillo Suárez",
                        "reason": "La petición pide que el docente firme personalmente.",
                    },
                    {
                        "index": 1,
                        "kind": "dependencia",
                        "responsible": "Departamento de Ingeniería Mecánica",
                        "reason": "El trámite requiere estudio interno del departamento.",
                    },
                ]
            }

    routing = FakeRouting()
    app = create_app(Settings(data_dir=tmp_path / "data"), pool_routing_engine=routing)
    with TestClient(app) as client:
        case = app.state.store.create(
            "solicitud.pdf", b"%PDF-1.4\n%%EOF", receipt={"workflow": "fiaga"}
        )
        cid = case["id"]
        app.state.pool.enroll(cid)
        app.state.pool.import_admin_review(cid, "admin", 1, snapshot("Falta firma", "Falta acta"))
        base = f"/api/cases/{cid}/pool"
        payload = {
            "actor_id": "admin",
            "revision": 2,
            "tasks": [
                {"request_id": "P1", "instruction": "Firmar respuesta personalmente"},
                {"request_id": "P2", "instruction": "Adjuntar acta del comité"},
            ],
        }
        forbidden = client.post(base + "/suggest-responsibles", json={**payload, "actor_id": "g1"})
        assert forbidden.status_code == 409
        stale = client.post(base + "/suggest-responsibles", json={**payload, "revision": 1})
        assert stale.status_code == 409
        bad_req = client.post(
            base + "/suggest-responsibles",
            json={**payload, "tasks": [{"request_id": "P99", "instruction": "Otro"}]},
        )
        assert bad_req.status_code == 422

        ok = client.post(base + "/suggest-responsibles", json=payload)
        assert ok.status_code == 200, ok.text
        suggestions = ok.json()["suggestions"]
        assert len(suggestions) == 2
        assert suggestions[0]["kind"] == "docente"
        assert "Carlos Andrés Trujillo Suárez" in suggestions[0]["responsible"]
        assert suggestions[1]["kind"] == "dependencia"
        assert suggestions[1]["responsible"] == "Departamento de Ingeniería Mecánica"
        # Suggesting must never advance revision or publish tasks automatically.
        detail = client.get(base).json()
        assert detail["stage"] == "initial_review" and detail["revision"] == 2
        assert detail["tasks"] == []
