"""Búsqueda léxica local: devuelve fragmentos originales, nunca genera evidencia."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

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
_EVIDENCE_CATEGORIES = frozenset({"national_norm", "institutional_norm", "case_evidence"})


def tokenize(text: str) -> list[str]:
    """Normaliza mayúsculas y tildes; no simula comprensión semántica."""
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in _STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


def retrieve(
    request: dict[str, Any], chunks: list[dict[str, Any]], limit: int = 8
) -> list[dict[str, Any]]:
    """Ordena con BM25 y limita a tres fragmentos por documento.

    El servicio debe suministrar únicamente fuentes públicas de la biblioteca y
    fuentes de este expediente. Si request incluye case_id se verifica de nuevo.
    Las respuestas anteriores orientan estilo; aquí nunca se usan como evidencia.
    No encontrar coincidencias significa ausencia en esta búsqueda, no inexistencia.
    """
    if limit <= 0:
        return []
    query = " ".join(str(request.get(key) or "") for key in ("title", "description"))
    query_terms = set(tokenize(query))
    if not query_terms:
        return []
    eligible = [
        chunk
        for chunk in chunks
        if chunk.get("category") in _EVIDENCE_CATEGORIES
        and chunk.get("validity") != "superseded"
        and str(chunk.get("quote") or "").strip()
        and ("case_id" not in request or chunk.get("case_id") in (None, request["case_id"]))
    ]
    if not eligible:
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
            ranked.append({**chunk, "score": round(score, 8), "matched_terms": matched})
    ranked.sort(key=lambda chunk: (-chunk["score"], str(chunk["chunk_id"])))
    counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in ranked:
        document_id = str(chunk["document_id"])
        chunk_id = str(chunk["chunk_id"])
        if counts[document_id] >= 3 or chunk_id in seen:
            continue
        results.append(chunk)
        counts[document_id] += 1
        seen.add(chunk_id)
        if len(results) == limit:
            break
    return results
