"""Original MIME conservado; vista de texto sin HTML ejecutable ni recursos remotos."""

import html
import io
import re
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path

import pymupdf

MAX_RAW = 30 * 1024 * 1024
MAX_TEXT = 120000


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        elif not self.hidden and tag in {"p", "div", "br", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def case_numbers(text):
    matches = re.findall(
        r"\b(?:caso|pqrs|radicado|case)\s*(?:n[uú]mero|no\.?|n[º°])?\s*[:#-]?\s*"
        r"([a-zA-Z]*-?\d[\w./-]{0,59})",
        text,
        flags=re.I,
    )
    return list(dict.fromkeys(matches))[:20]


def parse_message(raw, metadata):
    if len(raw) > MAX_RAW:
        raise ValueError("El correo supera 30 MB. Carga directamente el PDF de la petición.")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    headers = {
        key: str(message.get(key, ""))[:2000]
        for key in ("From", "To", "Subject", "Date", "Message-ID")
    }
    body_part = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body_part:
        try:
            text = body_part.get_content()
        except (LookupError, UnicodeError):
            text = body_part.get_payload(decode=True).decode("utf-8", errors="replace")
        if body_part.get_content_type() == "text/html":
            parser = PlainHTML()
            parser.feed(text)
            text = "".join(parser.parts)
    if not isinstance(text, str):
        text = ""
    text = text.replace("\x00", "").strip()
    attachments, contents = [], {}
    for index, part in enumerate(message.walk()):
        if part.is_multipart() or not part.get_filename():
            continue
        data = part.get_payload(decode=True) or b""
        name = Path(str(part.get_filename()).replace("\\", "/")).name[:180]
        key = str(index)
        is_pdf = name.lower().endswith(".pdf") and data.startswith(b"%PDF-")
        attachments.append({"id": key, "name": name, "size": len(data), "pdf": is_pdf})
        contents[key] = data
    received = None
    try:
        received = datetime.fromtimestamp(
            int(metadata["internalDate"]) / 1000, tz=timezone.utc
        ).isoformat()
    except (KeyError, ValueError, OverflowError, OSError):
        pass
    numbers = case_numbers(headers["Subject"] + "\n" + text)
    public = {
        "id": metadata["id"],
        "thread_id": metadata.get("threadId"),
        "subject": headers["Subject"],
        "sender": headers["From"],
        "to": headers["To"],
        "date_header": headers["Date"],
        "email_received_at": received,
        "internet_message_id": headers["Message-ID"],
        "text": text[:MAX_TEXT],
        "text_too_long": len(text) > MAX_TEXT,
        "attachments": attachments,
        "case_numbers": numbers,
        "case_number": numbers[0] if len(numbers) == 1 else "",
    }
    return public, contents


def body_pdf(message):
    if not message["text"].strip() or message["text_too_long"]:
        raise ValueError("El texto está vacío o supera el límite. Selecciona el PDF adjunto.")
    parts = [
        "Copia de consulta del correo · original .eml conservado",
        "Asunto: " + message["subject"],
        "Remitente: " + message["sender"],
        "Para: " + message["to"],
        "Fecha del encabezado: " + message["date_header"],
        "Recepción en Gmail: " + (message["email_received_at"] or "No disponible"),
        message["text"],
    ]
    markup = "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in parts)
    buffer = io.BytesIO()
    story = pymupdf.Story(html=markup, user_css="body {font-size:11pt;} p {margin-bottom:10pt;}")
    with pymupdf.DocumentWriter(buffer) as writer:
        more, pages = True, 0
        while more:
            if pages >= 40:
                raise ValueError("El correo supera 40 páginas. Carga una petición más acotada.")
            device = writer.begin_page(pymupdf.Rect(0, 0, 595, 842))
            more, _ = story.place(pymupdf.Rect(42, 42, 553, 800))
            story.draw(device)
            writer.end_page()
            pages += 1
    return buffer.getvalue()
