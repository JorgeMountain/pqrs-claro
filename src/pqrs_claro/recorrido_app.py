"""Recorrido conservado; biblioteca servida por el único backend local activo."""

import argparse
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import ROOT


def create_recorrido(backend_port=8770, transport=None):
    static = ROOT / "src" / "pqrs_claro" / "static"
    demo = ROOT / "output" / "ux-peticiones-20260910"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{backend_port}",
            transport=transport,
            timeout=120,
            trust_env=False,
        ) as client:
            app.state.backend = client
            yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def fresh_interface(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith(("/api/", "/files/")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/recorrido-status")
    def status():
        return {"interface": "recorrido", "library": "connected", "backend_port": backend_port}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def api_proxy(path: str, request: Request):
        # El destino está fijado en loopback. No se abre otra conexión SQLite ni
        # se confunde la demostración guardada con un expediente real.
        headers = {key: request.headers[key] for key in ("content-type",) if key in request.headers}
        try:
            result = await app.state.backend.request(
                request.method,
                "/api/" + path,
                params=request.query_params.multi_items(),
                headers=headers,
                content=await request.body(),
            )
        except httpx.HTTPError:
            return JSONResponse(
                {
                    "detail": "No pudimos contactar la biblioteca. "
                    "Comprueba que el servicio esté activo y reintenta."
                },
                status_code=503,
            )
        forwarded = {
            key: result.headers[key]
            for key in ("content-type", "content-disposition")
            if key in result.headers
        }
        return Response(result.content, status_code=result.status_code, headers=forwarded)

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
    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8772)
    parser.add_argument("--backend-port", type=int, default=8770)
    args = parser.parse_args()
    if args.port == args.backend_port:
        parser.error("El recorrido y el servicio deben tener puertos distintos.")
    uvicorn.run(create_recorrido(args.backend_port), host="127.0.0.1", port=args.port)
