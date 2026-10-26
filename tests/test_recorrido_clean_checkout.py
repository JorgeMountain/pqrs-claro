"""A clone starts without local output files; existing demos remain optional."""

import json
from shutil import copytree

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pqrs_claro import recorrido_ui


def checkout(tmp_path, monkeypatch):
    copytree(recorrido_ui.ROOT / "src/pqrs_claro/static", tmp_path / "src/pqrs_claro/static")
    monkeypatch.setattr(recorrido_ui, "ROOT", tmp_path)
    return tmp_path


def test_inbox_assets_work_without_output_directory(tmp_path, monkeypatch):
    root = checkout(tmp_path, monkeypatch)
    assert not (root / "output").exists()
    app = FastAPI()
    recorrido_ui.mount_recorrido_ui(app)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/data.json").json()["requests"] == []
        assert client.get("/logo.png").headers["content-type"] == "image/png"
        assert client.get("/files/not-present.pdf").status_code == 404


def test_existing_local_demo_is_preserved(tmp_path, monkeypatch):
    root = checkout(tmp_path, monkeypatch)
    demo = root / "output/ux-peticiones-20260910"
    (demo / "files").mkdir(parents=True)
    payload = {"subject": "Demo ficticia aislada", "requests": []}
    (demo / "data.json").write_text(json.dumps(payload), encoding="utf-8")
    (demo / "files/example.txt").write_text("Ejemplo ficticio", encoding="utf-8")
    app = FastAPI()
    recorrido_ui.mount_recorrido_ui(app)
    with TestClient(app) as client:
        assert client.get("/data.json").json() == payload
        assert client.get("/files/example.txt").text == "Ejemplo ficticio"
        assert client.get("/logo.png").status_code == 200
