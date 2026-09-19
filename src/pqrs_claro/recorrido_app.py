"""Recorrido conservado; biblioteca servida por el único backend local activo."""

import argparse
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .recorrido_ui import mount_recorrido_ui


def create_recorrido(backend_port=8770, transport=None):
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
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def fresh_interface(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if (origin and origin != expected) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return JSONResponse(
                    {"detail": "Abra la aplicación local para realizar esta acción."}, 403
                )
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith(("/api/", "/files/")):
            response.headers["Cache-Control"] = "no-cache"
        return response

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

    mount_recorrido_ui(app, backend_port=backend_port)
    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8772)
    parser.add_argument("--backend-port", type=int, default=8770)
    args = parser.parse_args()
    if args.port == args.backend_port:
        parser.error("El recorrido y el servicio deben tener puertos distintos.")
    uvicorn.run(
        create_recorrido(args.backend_port), host="127.0.0.1", port=args.port, access_log=False
    )
