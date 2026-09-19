"""Rutas estáticas del recorrido, compartidas por ambos modos de arranque."""

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT


def mount_recorrido_ui(app, *, backend_port=None):
    """Registrar después de la API: el montaje raíz siempre queda al final."""
    static = ROOT / "src" / "pqrs_claro" / "static"
    demo = ROOT / "output" / "ux-peticiones-20260910"

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
        return FileResponse(demo / "logo.png")

    @app.get("/library-evidence.js")
    def evidence_module():
        return FileResponse(static / "evidence-upload.js", media_type="text/javascript")

    app.mount("/shared", StaticFiles(directory=static), name="shared-ui")
    app.mount("/files", StaticFiles(directory=demo / "files"), name="demo-files")
    app.mount("/", StaticFiles(directory=static / "recorrido", html=True), name="recorrido")
