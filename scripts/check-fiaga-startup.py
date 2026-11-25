"""Comprueba el arranque real de la aplicación unificada con una bandeja temporal."""

import json
import os
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory


def get(port, path):
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"{path} devolvió HTTP {response.status}")
        return response.read()
    finally:
        connection.close()


def main():
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    with TemporaryDirectory(prefix="fiaga-startup-") as temporary:
        env = os.environ.copy()
        env.update(
            PYTHONPATH=os.pathsep.join(filter(None, [str(root / "src"), env.get("PYTHONPATH")])),
            PQRS_CLARO_DATA_DIR=temporary,
            PQRS_CLARO_KEY_FILE=str(Path(temporary) / "unused.env"),
            OPENAI_API_KEY="unused-smoke-test-key",
            PQRS_CLARO_CLASSIFICATION_PROVIDER="openai",
        )
        server = subprocess.Popen(
            [sys.executable, "-m", "pqrs_claro.unified_app", "--port", str(port)],
            cwd=root,
            env=env,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError(f"FIAGA terminó durante el arranque ({server.returncode})")
                try:
                    status = json.loads(get(port, "/recorrido-status"))
                    break
                except OSError:
                    time.sleep(0.25)
            else:
                raise TimeoutError("FIAGA no respondió en 60 segundos")
            if status.get("mode") != "unified" or status.get("library") != "connected":
                raise RuntimeError("El servicio respondió sin el recorrido unificado de FIAGA")
            if b"./fiaga.js" not in get(port, "/"):
                raise RuntimeError("La página de inicio no carga la interfaz FIAGA")
            config = json.loads(get(port, "/api/config"))
            if not (config["initial_review_enabled"] and config["management_enabled"]):
                raise RuntimeError("La revisión inicial o la gestión están desactivadas")
            if json.loads(get(port, "/api/cases")) != []:
                raise RuntimeError("La bandeja temporal debe estar vacía")
            print("FIAGA respondió con la portada, el recorrido unificado y la bandeja temporal.")
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    main()
