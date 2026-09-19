"""Recepción Gmail, sin envío, borrado, cambios de etiquetas ni aprobación automática."""

import html
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import Field

from .gmail_auth import GmailError
from .models import StrictModel


class ImportMail(StrictModel):
    account: str = Field(min_length=3, max_length=320)
    mode: Literal["pdf", "body", "link"]
    attachment_id: str | None = Field(default=None, max_length=20)
    case_number: str = Field(default="", max_length=100)
    body_confirmed: bool = False
    target_case_id: str | None = Field(default=None, max_length=100)


def gmail_router(service):
    router = APIRouter(prefix="/api/gmail")

    @router.get("/status")
    def status():
        return service.auth.status()

    @router.post("/configure")
    async def configure(file: UploadFile = File(...)):
        try:
            raw = await file.read(65537)
            if len(raw) > 65536:
                raise GmailError("El JSON de configuración supera 64 KB.")
            service.auth.configure(raw)
            return service.auth.status()
        finally:
            await file.close()

    @router.post("/authorize")
    def authorize():
        return service.auth.authorize()

    @router.get("/oauth/callback", response_class=HTMLResponse)
    def callback(state: str = "", code: str = "", error: str | None = None):
        try:
            account = service.auth.callback(state, code, error)
            message = "Gmail conectado: " + account + ". Vuelve al sistema y consulta los correos."
            status_code = 200
        except GmailError as exc:
            message, status_code = str(exc), 400
        # No echoes of authorization code, state or upstream response.
        return HTMLResponse(
            '<!doctype html><html lang="es"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Conexión con Gmail</title><h1>Conexión con Gmail</h1><p>"
            + html.escape(message)
            + '</p><a href="/">Volver al sistema</a></html>',
            status_code=status_code,
        )

    @router.post("/disconnect")
    def disconnect():
        with service.lock:
            service.auth.disconnect()
        return service.auth.status()

    @router.get("/messages")
    def messages(
        label: str = Query(default="PQRS-Pruebas", min_length=1, max_length=100),
        page_token: str = Query(default="", max_length=2048),
    ):
        return service.inbox(label.strip(), page_token)

    @router.get("/messages/{mid}")
    def detail(mid: str, account: str = Query(max_length=320)):
        return service.detail(mid, account)

    @router.post("/messages/{mid}/import")
    def import_mail(mid: str, body: ImportMail):
        return service.import_message(mid, body)

    @router.get("/originals/{key}")
    def original(key: str):
        return Response(
            service.raw(service.row(key)),
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="correo-original.eml"'},
        )

    @router.get("/originals/{key}/attachments/{attachment_id}")
    def attachment(key: str, attachment_id: str):
        item, data = service.attachment(key, attachment_id)
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(item["name"], safe="")
            },
        )

    @router.get("/cases/{case_id}")
    def linked(case_id: str):
        return {"messages": service.case_messages(case_id)}

    return router
