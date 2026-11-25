"""Etiquetas de consulta por versión, independientes del texto usado por el RAG."""

import re
import unicodedata

from .models import DomainError

ADMISSIONS_COLLECTION = "drive-admisiones-udea-2027-1"
MAX_TOPICS = 16


def _label(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainError("Una etiqueta debe ser texto.")
    value = " ".join(unicodedata.normalize("NFC", value).split())
    if len(value) > 120:
        raise DomainError("Cada etiqueta admite hasta 120 caracteres.")
    return value or None


def normalized_labels(topics, issuer, period):
    if not isinstance(topics, list) or len(topics) > MAX_TOPICS:
        raise DomainError(f"Selecciona hasta {MAX_TOPICS} temas por documento.")
    unique = {}
    for topic in topics:
        name = _label(topic)
        if name:
            unique.setdefault(name.casefold(), name)
    return {"topics": [unique[key] for key in sorted(unique)],
            "issuer": _label(issuer), "period": _label(period)}


def admissions_labels(source, first_page, second_page):
    """Use catalog membership and the document's own title, cover and contents."""
    if source.get("collection_id") != ADMISSIONS_COLLECTION:
        return None
    title = source.get("title") or source["filename"]
    topics = ["Admisiones"]
    basis = ["Tema general: colección Admisiones UdeA 2027-1."]
    texts = [(title, "título"), (first_page, "página 1")]
    if re.search(r"\bcontenido\b", second_page[:160], re.I):
        texts.append((second_page, "tabla de contenido de la página 2"))
    for term, name in ((r"calendario|cronograma", "Calendario académico"),
                       ("examen", "Examen de admisión"), ("credencial", "Credencial"),
                       ("inscripci[oó]n|inscripciones", "Inscripción")):
        for text, place in texts:
            match = re.search(r"\b(?:" + term + r")\b", text, re.I)
            if match:
                topics.append(name)
                basis.append(f"{name}: «{match[0]}» en {place}.")
                break
    period = None
    periods = set(re.findall(r"\b(20\d\d)\s*[-–]\s*([12])\b", title))
    if len(periods) == 1:
        period = "-".join(periods.pop())
        basis.append(f"Período en el título: {title}.")
    # A contact address, recipient, folder or author mentioned in the body is not an issuer.
    issuer = None
    attribution = re.search(
        r"^[ \t]*(?:dependencia emisora|emitid[oa] por|expedid[oa] por)[ \t]*:[ \t]*"
        r"([^\r\n;]{3,120})(?=[;\r\n]|$)",
        first_page, re.I | re.M,
    )
    if attribution:
        issuer = attribution.group(1).strip().rstrip(".")
        basis.append(f"Página 1: {attribution.group(0).strip()}.")
    elif re.search(
        r"^\s*Vicerrectoría de Docencia\s+Departamento de\s+Admisiones y Registro\s*$",
        first_page[:1200], re.I | re.M,
    ):
        issuer = "Departamento de Admisiones y Registro"
        basis.append("Portada: Vicerrectoría de Docencia / Departamento de Admisiones y Registro.")
    return normalized_labels(topics, issuer, period), " ".join(basis)
