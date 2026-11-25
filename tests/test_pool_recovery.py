import time

from fastapi.testclient import TestClient
from test_app import pdf_bytes  # noqa: F401

from pqrs_claro.config import Settings
from pqrs_claro.unified_app import create_unified_app


def settled(client, path):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        row = client.get(path).json()
        if row["error"] or row["stage"] != "preparing":
            return row
        time.sleep(.02)
    raise AssertionError("El borrador quedó procesándose")


def test_restart_after_receipt_waits_for_admin_on_same_pdf(tmp_path, pdf_bytes):  # noqa: F811
    settings = Settings(data_dir=tmp_path, management_enabled=True)
    app = create_unified_app(settings)
    # Simulate an interruption just after durable receipt, before queue admission.
    case = app.state.store.create("prueba.pdf", pdf_bytes, receipt={"workflow": "fiaga"})
    path = f"/api/cases/{case['id']}/pool"
    with TestClient(app) as client:
        saved = client.get(path).json()
        assert saved["stage"] == "admin_review" and not saved["requests"]
    second = create_unified_app(settings)
    with TestClient(second) as client:
        assert client.get(path).json() == saved
        actor = {"actor_id": "admin", "revision": 1}
        assert client.post(path + "/start", json={"actor_id": "admin"}).status_code == 409
        assert client.post(path + "/import-review", json=actor).status_code == 409
        assert client.post(path + "/publish", json={**actor, "tasks": []}).status_code == 409
        assert client.get(f"/api/cases/{case['id']}/original").content == pdf_bytes
