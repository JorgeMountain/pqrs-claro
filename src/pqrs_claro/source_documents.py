"""Indicios locales del objeto documental pedido, sin certificar su autenticidad."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _plain(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )


def requested_document(request: dict[str, Any]) -> str | None:
    """Resguardo acotado para peticiones explícitas de entrega de documentos."""
    text = _plain(f"{request.get('title', '')} {request.get('description', '')}")
    delivery = re.search(r"\b(copias?|adjunt\w*|remit\w*|entreg\w*|envi\w*|facilit\w*)\b", text)
    if not delivery:
        return None
    documents = re.findall(
        r"\b(acta|contrato|resolucion|certificado|certificacion|expediente|informe|"
        r"documento|constancia|convenio|acuerdo|circular|oficio|registro|correo|"
        r"respuesta)s?(?![a-z])",
        _plain(f"{request.get('description', '')} {request.get('title', '')}"),
    )
    # Una envoltura genérica no sustituye al objeto: «documento que contiene el acta».
    return next((kind for kind in documents if kind != "documento"), None) or (
        "documento" if documents or "copia" in text else None
    )


def requested_document_number(request: dict[str, Any], kind: str) -> str | None:
    text = _plain(f"{request.get('description', '')} {request.get('title', '')}")
    match = re.search(
        rf"\b{kind}s?\s*(?:(?:numero|nro\.?|no\.?|num\.?|#)\s*)?(\d+(?:-\d+)*)",
        text,
    )
    return match.group(1) if match else None


def requested_certification(request: dict[str, Any]) -> bool:
    """Distingue pedir una certificación de solicitar una explicación de hechos."""
    text = _plain(str(request.get("description") or request.get("title") or ""))
    if re.search(r"\bcertifi(?:car|que|quen)\b", text):
        return True
    return bool(
        re.search(r"\bcertifica(?:cion(?:es)?|dos?|das?)\b", text)
        and re.search(r"\b(?:solicit\w*|obtener|expedir|expidan?|emitir|emitan?)\b", text)
    )


def document_matches(request: dict[str, Any], source: dict[str, Any], kind: str) -> bool:
    """Comprueba indicios de identidad; no certifica autenticidad ni integridad del archivo."""
    if kind == "documento":
        return False
    name = _plain(f"{source.get('title', '')} {source.get('filename', '')}").replace("_", " ")
    quote = _plain(str(source.get("quote") or ""))
    email = bool(
        re.search(r"\b(?:gmail|fwd|correo de|correo electronico)\b", name)
        or re.search(r"gmail\s*[-:]|https?://mail\.google\.com/", quote)
        or (
            re.search(r"(?m)^\s*(?:para|to):", quote)
            and re.search(r"\b\d+ mensajes?\b|(?m:^\s*(?:de|from):)", quote)
        )
    )
    if kind == "correo":
        if not email:
            return False
        # El oficio mencionado precisa qué correo se pidió; no convierte su adjunto en localizado.
        number = requested_document_number(request, "oficio")
        return not number or bool(re.search(rf"(?<!\d){re.escape(number)}(?!\d)", quote))
    if email:
        return False
    kinds = "(?:oficio|respuesta)" if kind == "respuesta" else kind
    if not re.search(rf"\b{kinds}s?(?![a-z])", name):
        return False
    number = requested_document_number(request, kind)
    if number:
        # El número central identifica el oficio institucional 21360001-1436-2024.
        parts = number.split("-")
        key = parts[-2] if len(parts) > 1 and len(parts[-1]) == 4 else parts[-1]
        if not re.search(rf"(?<!\d){re.escape(key)}(?!\d)", name):
            return False
    header = re.search(rf"(?m)^\s*{kinds}s?(?![a-z])[^\n]*", quote)
    if header and number and not re.search(
        rf"(?<!\d){re.escape(number)}(?!\d)", header.group()
    ):
        header = None
    numbered_header = number and re.search(
        rf"(?m)^\s*(?:\d+-)*{re.escape(number)}(?:-\d+)*\s*$", quote
    )
    return bool(header or numbered_header)


def numbered_document_references(text: str) -> list[str]:
    """Referencias explícitas para conservar otros componentes de un mismo faltante."""
    references = re.findall(
        r"\b(acta|contrato|resolucion|certificado|certificacion|informe|convenio|"
        r"acuerdo|circular|oficio|respuesta)s?\s*"
        r"(?:(?:numero|nro\.?|no\.?|num\.?|#)\s*)?(\d+(?:-\d+)*)",
        _plain(text).replace("\u00ad", ""),
    )
    return list(dict.fromkeys(f"{kind} {number}" for kind, number in references))


def named_document_candidates(text: str, candidates: list[dict[str, Any]]) -> list[dict]:
    """Localiza por nombre y número; no convierte una mención en identidad acreditada.

    Solo consulta el nombre del archivo, nunca números extraídos de su contenido o
    relaciones de catálogo. Un correo titulado con su adjunto tampoco es el adjunto.
    """
    references = [reference.split(" ", 1) for reference in numbered_document_references(text)]
    located = []
    for source in candidates:
        if source.get("category") not in {
            "historical_response", "historical_attachment", "case_evidence"
        }:
            continue
        name = _plain(str(source.get("filename") or source.get("title") or "")).replace("_", " ")
        quote = _plain(str(source.get("quote") or ""))
        if re.search(r"\b(?:gmail|fwd|correo|notificacion|remision)\b", name) or re.search(
            r"gmail\s*[-:]|https?://mail\.google\.com/|(?m:^\s*(?:para|to):)", quote
        ):
            continue
        for kind, number in references:
            parts = number.split("-")
            year = parts[-1] if len(parts) > 1 and len(parts[-1]) == 4 else None
            key = parts[-2] if year else parts[-1]
            kinds = r"(?:oficio|respuesta)" if kind in {"oficio", "respuesta"} else kind
            if not re.search(rf"\b{kinds}s?\b", name):
                continue
            if not re.search(rf"(?<!\d){re.escape(key)}(?!\d)", name):
                continue
            # No equiparar el mismo número de oficio de años diferentes.
            named_years = re.findall(rf"(?<!\d){re.escape(key)}[- ](\d{{4}})(?!\d)", name)
            if year and named_years and year not in named_years:
                continue
            located.append(source)
            break
    return located
