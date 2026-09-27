"""Espacio local, temporal y aislado para probar clasificación con Laya."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import jev_lab
from .classification_questions import QUESTIONS
from .config import ROOT

PORT = 8775
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_TEXT_CHARS = 3000
LAYA_TIMEOUT_SECONDS = 150
MODEL_NAMES = {"english", "multilingual", "typed-decisions"}
DEFAULT_TYPE_MODEL = "english"
DEFAULT_RUDE_MODEL = "multilingual"


def _local_laya_url(value: str | None = None) -> str:
    raw = (value or os.environ.get("LAYA_LOCAL_URL") or "http://127.0.0.1:8770").strip()
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("LAYA_LOCAL_URL no es una URL válida.") from exc
    if (
        parsed.scheme != "http"
        or hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("LAYA_LOCAL_URL debe apuntar por HTTP a localhost o 127.0.0.1.")
    authority = hostname if port is None else f"{hostname}:{port}"
    return f"http://{authority}"


def _extract_pdf(raw: bytes) -> tuple[str, int, list[str]]:
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=415,
            detail="El archivo seleccionado no parece ser un PDF válido.",
        )
    try:
        document = pymupdf.open(stream=raw, filetype="pdf")
    except Exception:
        raise HTTPException(status_code=422, detail="No se pudo leer el PDF.") from None
    with document:
        if document.needs_pass:
            raise HTTPException(
                status_code=422,
                detail="El PDF tiene contraseña y no se puede leer.",
            )
        page_count = len(document)
        if page_count == 0:
            raise HTTPException(status_code=422, detail="El PDF no contiene páginas.")
        if page_count > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"El límite de este banco es de {MAX_PDF_PAGES} páginas por PDF.",
            )
        page_texts = [page.get_text("text").strip() for page in document]
    warnings = []
    if any(not page_text for page_text in page_texts):
        warnings.append(
            "Una o más páginas no contienen texto seleccionable. Este banco no hace OCR."
        )
    text = "\n\n".join(part for part in page_texts if part).strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="No se encontró texto seleccionable. Pega el texto o usa un PDF con OCR.",
        )
    return text, page_count, warnings


def create_laya_lab_app(
    *,
    laya_base_url: str | None = None,
    laya_transport: httpx.AsyncBaseTransport | None = None,
    jev_api_key: str | None = None,
    jev_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create the standalone tester; it has no connection to PQRS databases or services."""
    base_url = _local_laya_url(laya_base_url)
    app = FastAPI(
        title="Banco de pruebas de Laya",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )
    app.state.laya_base_url = base_url
    app.state.laya_transport = laya_transport

    @app.middleware("http")
    async def private_no_store(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'"
        )
        return response

    @app.get("/laya-lab-environment")
    async def environment():
        return {
            "environment": "fiaga-laya-lab",
            "code_root": str(ROOT),
            "data_root": None,
            "port": PORT,
        }

    async def laya_request(path: str, payload: dict | None = None) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(LAYA_TIMEOUT_SECONDS, connect=2.0),
                trust_env=False,
                transport=app.state.laya_transport,
            ) as client:
                url = app.state.laya_base_url + path
                if payload is None:
                    return await client.get(url)
                return await client.post(url, json=payload)
        except httpx.RequestError as exc:
            raise exc

    @app.get("/api/status")
    async def status():
        try:
            response = await laya_request("/api/health")
            response.raise_for_status()
            health = response.json()
            models = health.get("models", {})
            ready_models = [name for name, state in models.items() if state == "ready"]
            return {
                "connected": True,
                "jev_configured": bool(jev_lab.get_key() if jev_api_key is None else jev_api_key),
                "ready": bool(ready_models),
                "models": models,
                "version": health.get("version"),
                "device": health.get("device"),
                "message": (
                    "Laya local está lista para pruebas."
                    if ready_models
                    else "Laya responde, pero todavía no hay modelos listos."
                ),
            }
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            return {
                "connected": False,
                "jev_configured": bool(jev_lab.get_key() if jev_api_key is None else jev_api_key),
                "ready": False,
                "models": {},
                "message": (
                    "No se encuentra Laya local en el puerto 8770. "
                    "Inicia Laya y vuelve a comprobar."
                ),
            }

    @app.post("/api/classify")
    async def classify(
        text: str = Form(default=""),
        provider: str = Form(default="laya"),
        file: UploadFile | None = File(default=None),
        type_model: str = Form(default=DEFAULT_TYPE_MODEL),
        rude_model: str = Form(default=DEFAULT_RUDE_MODEL),
    ):
        if provider not in {"laya", "jev"}:
            raise HTTPException(status_code=422, detail="Proveedor no válido.")
        if type_model not in MODEL_NAMES or rude_model not in MODEL_NAMES:
            raise HTTPException(status_code=422, detail="Selecciona un modelo de Laya disponible.")
        pasted = text.strip()
        if file is not None and pasted:
            raise HTTPException(
                status_code=422,
                detail="Usa una sola entrada por prueba: texto o PDF.",
            )
        if file is None and not pasted:
            raise HTTPException(status_code=422, detail="Pega texto o selecciona un PDF.")

        warnings: list[str] = []
        page_count = None
        source = "texto"
        if file is not None:
            source = "PDF"
            if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
                raise HTTPException(status_code=415, detail="Solo se admiten archivos PDF.")
            raw = await file.read(MAX_PDF_BYTES + 1)
            await file.close()
            if len(raw) > MAX_PDF_BYTES:
                raise HTTPException(status_code=413, detail="El PDF supera el límite de 10 MB.")
            pasted, page_count, warnings = _extract_pdf(raw)
        if len(pasted) > MAX_TEXT_CHARS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"El texto extraído supera el límite de {MAX_TEXT_CHARS:,} caracteres. "
                    "Acórtalo para esta prueba; el banco no recorta el contenido en silencio."
                ),
            )

        if provider == "jev":
            result = await jev_lab.predict(
                pasted, QUESTIONS, key=jev_api_key, transport=jev_transport
            )
            return {
                "provider": "jev",
                "result": result,
                "source": source,
                "page_count": page_count,
                "character_count": len(pasted),
                "warnings": warnings,
            }

        try:
            type_response = await laya_request(
                "/api/predict",
                {
                    "state": pasted,
                    "questions": {"petition_type": QUESTIONS["petition_type"]},
                    "model": type_model,
                    "lang": "es",
                },
            )
            type_response.raise_for_status()
            type_result = type_response.json()

            rude_response = await laya_request(
                "/api/predict",
                {
                    "state": pasted,
                    "questions": {"rude_language": QUESTIONS["rude_language"]},
                    "model": rude_model,
                    "lang": "es",
                },
            )
            rude_response.raise_for_status()
            rude_result = rude_response.json()
        except httpx.RequestError:
            raise HTTPException(
                status_code=503,
                detail="Laya local no está disponible. Comprueba el servidor en 127.0.0.1:8770.",
            ) from None
        except httpx.HTTPStatusError as exc:
            try:
                reason = exc.response.json().get("error", "falló la clasificación")
            except ValueError:
                reason = "falló la clasificación"
            raise HTTPException(
                status_code=502,
                detail=f"Laya no pudo completar la clasificación: {reason}",
            ) from None
        except ValueError:
            raise HTTPException(
                status_code=502,
                detail="Laya devolvió una respuesta que no se pudo interpretar.",
            ) from None

        if not isinstance(type_result, dict) or not isinstance(rude_result, dict):
            raise HTTPException(
                status_code=502,
                detail="Laya devolvió una respuesta que no se pudo interpretar.",
            )
        type_answers = type_result.get("answers")
        rude_answers = rude_result.get("answers")
        if (
            not isinstance(type_answers, dict)
            or "petition_type" not in type_answers
            or not isinstance(rude_answers, dict)
            or "rude_language" not in rude_answers
        ):
            raise HTTPException(
                status_code=502,
                detail="Laya no devolvió ambas clasificaciones.",
            )
        type_routing = type_result.get("routing") or {}
        rude_routing = rude_result.get("routing") or {}
        call_tokens = [
            int((item.get("usage") or {}).get("input_tokens", 0))
            for item in (type_result, rude_result)
        ]
        result = {
            "answers": {
                "petition_type": type_answers["petition_type"],
                "rude_language": rude_answers["rude_language"],
            },
            "routing": {
                "models": {
                    "petition_type": type_routing.get("model", type_model),
                    "rude_language": rude_routing.get("model", rude_model),
                }
            },
            "usage": {
                "input_tokens": sum(call_tokens),
                "max_input_tokens": max(call_tokens, default=0),
            },
            "latency_ms": round(
                float(type_result.get("latency_ms", 0)) + float(rude_result.get("latency_ms", 0)),
                1,
            ),
        }
        return {
            "provider": "laya",
            "result": result,
            "source": source,
            "page_count": page_count,
            "character_count": len(pasted),
            "warnings": warnings,
        }

    static = ROOT / "src" / "pqrs_claro" / "static" / "laya-lab"
    app.mount("/assets", StaticFiles(directory=static), name="laya-lab-assets")

    @app.get("/")
    async def home():
        return FileResponse(static / "index.html", media_type="text/html")

    return app
