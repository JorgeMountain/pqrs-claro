"""Búsqueda léxica local: devuelve fragmentos originales, nunca genera evidencia."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from .source_documents import document_matches, requested_document, requested_document_number

# Las palabras de trámite suelen aparecer en todas las peticiones y no discriminan
# documentos. Se conservan negaciones, números y términos propios del asunto.
_STOPWORDS = frozenset(
    "a al algo ante asi bajo cada como con cual cuales cuando de del desde donde el ella "
    "ellos en entre era es esa ese esta este estos estas fue ha hasta hay la las le les "
    "lo los me mi mis o para por que quien se ser si sobre son su sus un una uno unos "
    "unas y ya yo solicitud solicitudes solicito solicitar solicitan favor porfavor "
    "atentamente cordialmente informar indique indicar informacion "
    "respetuosamente".split()
)
HISTORICAL_CATEGORIES = frozenset(
    {"historical_response", "historical_petition", "historical_attachment"}
)
_EVIDENCE_CATEGORIES = (
    frozenset({"national_norm", "institutional_norm", "case_evidence"}) | HISTORICAL_CATEGORIES
)


def source_in_scope(request: dict[str, Any], source: dict[str, Any]) -> bool:
    """Una colección histórica solo es visible tras vincularla al expediente.

    El filtro también cubre normas guardadas en una colección. Ausencia de case_id
    en una fuente histórica nunca la convierte en una fuente pública compartida.
    """
    collection_id = source.get("collection_id")
    allowed = request.get("allowed_collection_ids", [])
    if not isinstance(allowed, (list, tuple, set, frozenset)):
        allowed = []
    if collection_id and collection_id not in allowed:
        return False
    if source.get("category") in HISTORICAL_CATEGORIES and not collection_id:
        return False
    return "case_id" not in request or source.get("case_id") in (None, request["case_id"])


def tokenize(text: str) -> list[str]:
    """Normaliza mayúsculas y tildes; no simula comprensión semántica."""
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    normalized = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized)
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in _STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


def _rank(
    request: dict[str, Any], eligible: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """BM25 sobre un corpus cuyo alcance ya fue filtrado por retrieve."""
    if not eligible:
        return []
    query = " ".join(str(request.get(key) or "") for key in ("title", "description"))
    query_terms = set(tokenize(query))
    document_kind = requested_document(request)
    document_number = (
        requested_document_number(request, "oficio" if document_kind == "correo" else document_kind)
        if document_kind
        else None
    )
    if not query_terms:
        return []
    # El título ayuda a localizar un documento solicitado, incluso cuando el
    # encabezado no se repite dentro de todos sus fragmentos.
    documents = [
        Counter(tokenize(f"{chunk.get('title', '')} {chunk['quote']}")) for chunk in eligible
    ]
    lengths = [sum(document.values()) for document in documents]
    average_length = sum(lengths) / len(lengths) or 1.0
    frequencies = Counter(term for document in documents for term in document)
    ranked: list[dict[str, Any]] = []
    k1, b = 1.5, 0.75
    for chunk, document, length in zip(eligible, documents, lengths, strict=True):
        matched = sorted(query_terms.intersection(document))
        if not matched:
            continue
        score = 0.0
        for term in matched:
            inverse_frequency = math.log1p(
                (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
            )
            count = document[term]
            score += (
                inverse_frequency
                * count
                * (k1 + 1)
                / (count + k1 * (1 - b + b * length / average_length))
            )
        if score > 0:
            # Una petición repetida en un correo puede coincidir con más palabras
            # que el archivo pedido. Reservamos prioridad para indicios del objeto
            # y su número, sin atribuirle autenticidad, entrega ni revisión.
            identity = bool(document_kind and document_matches(request, chunk, document_kind))
            named_identity = bool(
                identity
                and document_number
                and re.search(
                    rf"(?<!\d){re.escape(document_number)}(?!\d)",
                    f"{chunk.get('title', '')} {chunk.get('filename', '')}",
                )
            )
            ranked.append(
                {
                    **chunk,
                    "score": round(score, 8),
                    "matched_terms": matched,
                    "document_identity_rank": int(identity) + int(named_identity),
                }
            )
    ranked.sort(
        key=lambda chunk: (
            -chunk["document_identity_rank"],
            -chunk["score"],
            str(chunk["chunk_id"]),
        )
    )
    return ranked


_ANSWER_START = re.compile(
    r"damos\s+respuesta\s+a\s+su\s+solicitud|"
    r"respondemos\s+a\s+su\s+solicitud|"
    r"se\s+permite\s+dar\s+respuesta\s+en\s+los\s+siguientes|"
    r"procede\s+a\s+dar\s+respuesta\s+en\s+los\s+siguientes|"
    r"permitimos\s+responder\s+de\s+fondo\s+a\s+sus\s+solicitudes\s+"
    r"en\s+los\s+siguientes",
    re.IGNORECASE,
)
_REPRODUCED_REQUEST = re.compile(
    r"\s*(?:En\s+el\s+numeral\b[^\n]*?usted\s+solicita|"
    r"Frente\s+a\s+la\s+solicitud\s+contenida|Se\s+solicita\s+cordial)",
    re.IGNORECASE,
)


def _answer_chunks(eligible: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detecta un inicio literal de contestación; no infiere por posición final."""
    boundaries: dict[str, tuple[int, int]] = {}
    for chunk in eligible:
        if chunk.get("category") != "historical_response":
            continue
        match = _ANSWER_START.search(chunk["quote"])
        if not match:
            continue
        position = (
            int(chunk.get("page", 0)),
            int(chunk.get("line_start", 1)) + chunk["quote"][: match.start()].count("\n"),
        )
        document_id = str(chunk["document_id"])
        boundaries[document_id] = min(position, boundaries.get(document_id, position))
    return [
        chunk for chunk in eligible
        if str(chunk["document_id"]) in boundaries
        and (int(chunk.get("page", 0)), int(chunk.get("line_end", 1)))
        >= boundaries[str(chunk["document_id"])]
        and not _REPRODUCED_REQUEST.match(chunk["quote"])
    ]


def _document_budget(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    results = []
    for chunk in rows:
        document_id = str(chunk["document_id"])
        if counts[document_id] >= 3:
            continue
        results.append(chunk)
        counts[document_id] += 1
        if len(results) == limit:
            break
    return results


def retrieve(
    request: dict[str, Any], chunks: list[dict[str, Any]], limit: int = 24
) -> list[dict[str, Any]]:
    """Combina búsqueda general y contestaciones, hasta 24 fragmentos originales.

    Filtra alcance antes de ambas búsquedas. Conserva prioridad del documento o
    correo pedido, reserva espacio a contestaciones tras un marcador explícito y
    limita repeticiones a dos fragmentos por documento, o tres para el objeto
    identificado que se solicita. Un límite explícito menor se respeta. Los
    indicadores de estructura no prueban hechos ni autenticidad;
    no encontrar coincidencias tampoco certifica inexistencia institucional.
    """
    if limit <= 0:
        return []
    limit = min(limit, 24)
    eligible = [
        chunk for chunk in chunks
        if chunk.get("category") in _EVIDENCE_CATEGORIES
        and chunk.get("validity") != "superseded"
        and str(chunk.get("quote") or "").strip()
        and source_in_scope(request, chunk)
    ]
    general = _document_budget(_rank(request, eligible), max(32, limit))
    answers = _document_budget(_rank(request, _answer_chunks(eligible)), max(32, limit))
    selected: list[dict[str, Any]] = []
    requested_documents = {
        str(row["document_id"]) for row in general
        if row.get("document_identity_rank", 0) > 0
    }
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    terms: list[set[str]] = []

    def add(row, deduplicate=True):
        document_id, chunk_id = str(row["document_id"]), str(row["chunk_id"])
        document_limit = 3 if document_id in requested_documents else 2
        if (
            len(selected) >= limit or chunk_id in seen
            or counts[document_id] >= document_limit
        ):
            return False
        words = set(tokenize(row["quote"]))
        if deduplicate and any(
            len(words & previous) / max(1, len(words | previous)) >= .82
            for previous in terms
        ):
            return False
        selected.append(row)
        counts[document_id] += 1
        seen.add(chunk_id)
        terms.append(words)
        return True

    for row in general:
        if row.get("document_identity_rank", 0) <= 0:
            break
        add(row, deduplicate=False)
        if len(selected) >= min(4, limit):
            break
    answer_budget = min(12, limit - len(selected))
    answer_count = 0
    for row in answers:
        answer_count += add(row)
        if answer_count >= answer_budget:
            break
    for row in general:
        add(row)
    # Si no hay suficientes pasajes distintos, mantener el límite explícito no
    # exige perder coincidencias útiles; se conserva el máximo por documento.
    for row in general:
        add(row, deduplicate=False)
    return selected
