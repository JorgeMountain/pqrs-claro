"""Rutas estáticas del recorrido, compartidas por ambos modos de arranque."""

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT


def mount_recorrido_ui(app, *, backend_port=None):
    """Registrar después de la API: el montaje raíz siempre queda al final."""
    static = ROOT / "src" / "pqrs_claro" / "static"
    legacy_demo = ROOT / "output" / "ux-peticiones-20260910"
    # A fresh clone includes the empty snapshot required by the current inbox.
    # Keep an existing local demo available without distributing its documents.
    demo = static / "demo"
    if (legacy_demo / "data.json").is_file() and (legacy_demo / "files").is_dir():
        demo = legacy_demo

    @app.get("/recorrido-status")
    def status():
        result = {"interface": "recorrido", "library": "connected"}
        if backend_port is not None:
            result["backend_port"] = backend_port
        else:
            result["mode"] = "unified"
        return result

    @app.get("/data.json")
    def demo_data():
        return FileResponse(demo / "data.json")

    @app.get("/logo.png")
    def logo():
        image = demo / "logo.png"
        return FileResponse(image if image.is_file() else static / "assets" / "udea-ingenieria.png")

    @app.get("/library-evidence.js")
    def evidence_module():
        return FileResponse(static / "evidence-upload.js", media_type="text/javascript")

    app.mount("/shared", StaticFiles(directory=static), name="shared-ui")
    app.mount("/files", StaticFiles(directory=demo / "files"), name="demo-files")
    app.mount("/", StaticFiles(directory=static / "recorrido", html=True), name="recorrido")
