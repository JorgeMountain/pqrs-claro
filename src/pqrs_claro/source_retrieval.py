"""Recuperación híbrida local; las coincidencias siempre conservan el texto original."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from .source_documents import (
    document_matches,
    named_document_candidates,
    numbered_document_references,
    referenced_document,
    requested_document_number,
)

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


class RetrievalIndex:
    """Reutiliza estadísticas por alcance, sin mezclar colecciones ni expedientes."""

    def __init__(self, chunks):
        self.chunks = chunks
        self._statistics = {}
        self._identities = {}

    def identity(self, request, chunk, kind, number):
        if not kind or kind == "documento":
            return 0
        query_key = (request.get("title", ""), request.get("description", ""))
        identities = self._identities.setdefault(query_key, {})
        key = chunk["chunk_id"]
        if key not in identities:
            identity = document_matches(request, chunk, kind)
            named = bool(identity and number and re.search(
                rf"(?<!\d){re.escape(number)}(?!\d)",
                f"{chunk.get('title', '')} {chunk.get('filename', '')}",
            ))
            identities[key] = int(identity) + int(named)
        return identities[key]

    def statistics(self, eligible):
        key = tuple((str(chunk["chunk_id"]), chunk["quote"]) for chunk in eligible)
        if key not in self._statistics:
            documents = [
                Counter(tokenize(f"{chunk.get('title', '')} {chunk['quote']}"))
                for chunk in eligible
            ]
            lengths = [sum(document.values()) for document in documents]
            postings = {}
            for index, document in enumerate(documents):
                for term, count in document.items():
                    postings.setdefault(term, []).append((index, count))
            self._statistics[key] = lengths, sum(lengths) / max(1, len(lengths)) or 1, postings
        return self._statistics[key]


def _rank(request, eligible, *, index=None, query=None):
    """BM25 con estadísticas del corpus autorizado y consultas independientes."""
    if not eligible:
        return []
    if query is None:
        query = " ".join(str(request.get(key) or "") for key in ("title", "description"))
    query_terms = set(tokenize(query))
    document_kind = referenced_document(request)
    document_number = (
        requested_document_number(request, "oficio" if document_kind == "correo" else document_kind)
        if document_kind
        else None
    )
    if not query_terms:
        return []
    index = index or RetrievalIndex(eligible)
    lengths, average_length, postings = index.statistics(eligible)
    scores = Counter()
    matches = {}
    for term in sorted(query_terms):
        occurrences = postings.get(term, [])
        inverse_frequency = math.log1p(
            (len(eligible) - len(occurrences) + 0.5) / (len(occurrences) + 0.5)
        )
        for position, count in occurrences:
            scores[position] += inverse_frequency * count * 2.5 / (
                count + 1.5 * (0.25 + 0.75 * lengths[position] / average_length)
            )
            matches.setdefault(position, []).append(term)
    ranked: list[dict[str, Any]] = []
    for position, score in scores.items():
        chunk = eligible[position]
        matched = matches[position]
        if score > 0:
            # Una petición repetida en un correo puede coincidir con más palabras
            # que el archivo pedido. Reservamos prioridad para indicios del objeto
            # y su número, sin atribuirle autenticidad, entrega ni revisión.
            identity_rank = index.identity(request, chunk, document_kind, document_number)
            ranked.append(
                {
                    **chunk,
                    "score": round(score, 8),
                    "matched_terms": matched,
                    "document_identity_rank": identity_rank,
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


def _baseline(
    request: dict[str, Any], chunks: list[dict[str, Any]], limit: int = 24, *, index=None
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
    general = _document_budget(_rank(request, eligible, index=index), max(32, limit))
    answers = _document_budget(
        _rank(request, _answer_chunks(eligible), index=index), max(32, limit)
    )
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


_QUESTION = re.compile(
    r"^\s*(?:(?:\(?[a-z]\)|\d+[.)])\s*(?:¿|copias?\b|entrega\b|solicit\w*\b)|"
    r"¿)",
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"^\s*(?:PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[ÉE]PTIMO|OCTAVO)\s*:",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")


def _adjacent_answer(anchor, eligible):
    """Una pregunta explícita en un oficio y su contestación contigua, sin sintetizar.

    Los párrafos DOCX pueden ser secciones distintas. PDF conserva cada fragmento
    con su página y líneas. Nunca se salta a otra fuente ni a otra pregunta.
    """
    if anchor.get("category") != "historical_response" or not _QUESTION.match(anchor["quote"]):
        return []
    siblings = sorted(
        (c for c in eligible if c["source_id"] == anchor["source_id"]),
        key=lambda c: (int(c.get("page", 0)), int(c.get("line_start", 1))),
    )
    start = next(i for i, c in enumerate(siblings) if c["chunk_id"] == anchor["chunk_id"])
    result, size = [anchor], len(anchor["quote"])
    for following in siblings[start + 1 : start + 8]:
        if _QUESTION.match(following["quote"]) or _SECTION.match(following["quote"]):
            break
        # Los números solo sirven como coordenadas; no saltar páginas omitidas.
        if int(following.get("page", 0)) > int(result[-1].get("page", 0)) + 1:
            break
        if size + len(following["quote"]) > 6500:
            break
        result.append(following)
        size += len(following["quote"])
    return result if len(result) > 1 else []


def _targeted_passages(request, eligible, *, index):
    """Prioriza una ubicación explícita de un archivo nombrado, con citas intactas.

    Solo resuelve una referencia documental inequívoca en la pregunta atómica.
    Las páginas/literales no se propagan a otros oficios mencionados en contexto.
    Un encabezado se devuelve como otro fragmento del mismo archivo, nunca se
    concatena con la respuesta ni acredita expedición o revisión institucional.
    """
    query = " ".join(str(request.get(key) or "") for key in ("title", "description"))
    plain = "".join(char for char in unicodedata.normalize("NFKD", query.casefold())
                    if not unicodedata.combining(char))
    references = numbered_document_references(query)
    if len(references) != 1:
        return []
    page = re.search(r"\b(?:pagina|pag\.)\s*(\d{1,4})\b", plain)
    literal = re.search(r"\bliteral\s+[\"'«]?([a-z])\b", plain)
    if not page and not literal:
        return []
    located = named_document_candidates(query, eligible)
    if not located:
        return []
    matching = [row for row in located if not page or row.get("page") == int(page[1])]
    marker = re.compile(
        rf"(?im)^\s*(?:\(\s*{re.escape(literal[1])}\s*\)|"
        rf"{re.escape(literal[1])}\s*[.)])\s+"
    ) if literal else None
    # Buscar el literal dentro del fragmento: un corte PDF puede comenzar en la
    # última frase del contexto y contener la pregunta y respuesta más adelante.
    literal_rows = [row for row in matching if marker and marker.search(row["quote"])]
    if literal and not page:
        matching = literal_rows
    ranking = {row["chunk_id"]: row for row in _rank(request, matching, index=index)}
    matching.sort(key=lambda row: (
        -int(row in literal_rows),
        -ranking.get(row["chunk_id"], {}).get("score", 0),
        int(row.get("page", 0)), int(row.get("line_start", 1)), row["chunk_id"],
    ))
    targets = matching[:4]
    result = [(row, "requested_passage") for row in targets]
    # Si el literal termina justo antes de «Respuesta», conservar su continuación
    # inmediata aunque no repita entidades y BM25 le dé pocos puntos.
    for anchor in targets[:1]:
        if not literal_rows or anchor not in literal_rows:
            continue
        siblings = sorted(
            [row for row in eligible if row["source_id"] == anchor["source_id"]],
            key=lambda row: (int(row.get("page", 0)), int(row.get("line_start", 1))),
        )
        position = next(i for i, row in enumerate(siblings)
                        if row["chunk_id"] == anchor["chunk_id"])
        following = siblings[position + 1:position + 2]
        for row in following:
            same_page = row.get("page") == anchor.get("page")
            next_page = int(row.get("page", 0)) == int(anchor.get("page", 0)) + 1
            near_line = int(row.get("line_start", 1)) <= int(anchor.get("line_end", 1)) + 1
            if ((same_page and near_line) or next_page) and not (
                _QUESTION.match(row["quote"]) or _SECTION.match(row["quote"])
            ):
                result.append(({**row, "adjacent_to": anchor["chunk_id"]}, "adjacent_answer"))
    kind, _ = references[0].split(" ", 1)
    identity_request = {"description": references[0]}
    target_sources = {row["source_id"] for row in targets}
    for source_id in sorted(target_sources)[:2]:
        siblings = [row for row in eligible if row["source_id"] == source_id]
        first_page = min(int(row.get("page", 0)) for row in siblings)
        headers = [row for row in siblings if int(row.get("page", 0)) == first_page
                   and document_matches(identity_request, row, kind)]
        if headers:
            header = min(headers, key=lambda row: (int(row.get("line_start", 1)), row["chunk_id"]))
            result.append((header, "document_identity"))
    return result


def retrieve(request, chunks, limit=24, *, index=None, semantic=None):
    """Combina consulta atómica, contexto, identidad, entidades y significado.

    Conserva resultados léxicos útiles y abre espacio a fuentes complementarias.
    Un resultado es un candidato: sus canales y vecindad nunca prueban un hecho.
    El componente semántico es opcional y solo recibe el corpus ya autorizado.
    """
    if limit <= 0:
        return []
    limit = min(24, limit)
    eligible = [c for c in chunks if c.get("category") in _EVIDENCE_CATEGORIES
                and c.get("validity") != "superseded" and str(c.get("quote") or "").strip()
                and source_in_scope(request, c)]
    query = " ".join(str(request.get(k) or "") for k in ("title", "description"))
    if not tokenize(query) or not eligible:
        return []
    index = index or RetrievalIndex(eligible)
    baseline = _baseline(request, eligible, limit, index=index)
    general = _rank(request, eligible, index=index)
    channels = {"lexical": baseline}
    context_queries = request.get("retrieval_queries") or [request.get("retrieval_context", "")]
    if isinstance(context_queries, str):
        context_queries = [context_queries]
    context_rows = []
    for context_query in context_queries[:3]:
        if isinstance(context_query, str) and context_query.strip():
            context_rows.extend(_rank(request, eligible, index=index, query=context_query)[:24])
    channels["context"] = context_rows
    identity_text = query + " " + str(request.get("retrieval_context") or "")
    named = {c["chunk_id"] for c in named_document_candidates(identity_text, eligible)}
    channels["identifier"] = [c for c in general if c["chunk_id"] in named]
    # Un correo exacto ofrece un canal específico. Listas masivas de destinatarios
    # no deben desplazar automáticamente una asociación local nombre/cuenta.
    emails = set(_EMAIL.findall(query.casefold()))
    entities = []
    if emails:
        entity_query = " ".join(sorted(emails))
        entities = [c for c in _rank(request, eligible, index=index, query=entity_query)
                    if emails.intersection(_EMAIL.findall(c["quote"].casefold()))]
        entities.sort(key=lambda c: (
            len(set(_EMAIL.findall(c["quote"].casefold()))) > 4,
            -c["score"], c["chunk_id"],
        ))
    channels["entity"] = entities
    channels["semantic"] = semantic.rank(query, eligible, limit=40) if semantic else []
    # Revalida IDs e identidad del fragmento incluso para proveedores enchufables.
    authorized = {c["chunk_id"]: c for c in eligible}
    channels = {name: [
        {**authorized[row["chunk_id"]], **{key: row[key] for key in (
            ("semantic_score",) if name == "semantic"
            else ("score", "matched_terms", "document_identity_rank")
        ) if key in row}}
        for row in rows if row["chunk_id"] in authorized
        and row["source_id"] == authorized[row["chunk_id"]]["source_id"]
        and row["quote"] == authorized[row["chunk_id"]]["quote"]
    ] for name, rows in channels.items()}
    selected, seen, counts = [], set(), Counter()
    requested_documents = {c["document_id"] for c in general
                           if c.get("document_identity_rank", 0)}

    def add(row, channel, *, expanded=False):
        if len(selected) >= limit or row["chunk_id"] in seen:
            return False
        document_limit = 8 if expanded else (
            3 if row["document_id"] in requested_documents or channel != "lexical" else 2
        )
        if counts[row["document_id"]] >= document_limit:
            return False
        selected.append({**row, "retrieval_channel": channel})
        seen.add(row["chunk_id"])
        counts[row["document_id"]] += 1
        return True

    # Una ubicación explícita domina las coincidencias léxicas con otros numerales.
    # Cada elemento sigue siendo un candidato original, con su alcance y metadatos.
    for row, channel in _targeted_passages(request, eligible, index=index):
        add(row, channel, expanded=True)
    # Protege resultados ya útiles, incluida la prioridad del objeto pedido.
    for row in baseline[:8]:
        add(row, "lexical")
    # Solo una pareja contigua por consulta: la pregunta atómica sigue dominando.
    # La prioridad de identidad localiza el archivo pedido; no debe esconder la
    # pregunta casi literal de un oficio cuando buscamos su contestación contigua.
    question_chunks = []
    for candidate in eligible:
        if candidate.get("category") != "historical_response":
            continue
        if _QUESTION.match(candidate["quote"]):
            # Puntuar la pregunta y no todas las respuestas diferentes que puedan
            # compartir su fragmento PDF. Solo se devuelve después el original.
            question_text = re.split(r"\?\s*|\n\s*\n|\bRespuesta\s*:", candidate["quote"],
                                     maxsplit=1, flags=re.IGNORECASE)[0][:900]
            question_chunks.append({**candidate, "quote": question_text})
    anchors = sorted(_rank(request, question_chunks, index=index),
                     key=lambda row: (-row["score"], row["chunk_id"]))
    # Preguntar quién figura en un plan y pedir su copia son objetivos distintos,
    # aunque compartan materia y semestre. Mantener esa intención en la vecindad.
    if re.search(r"\bcopias?\b", query, flags=re.IGNORECASE) and anchors:
        strongest = anchors[0]["score"]
        anchors.sort(key=lambda row: (
            -int(row["score"] >= strongest * .5 and bool(re.match(
                r"^\s*(?:\(?[a-z]\)|\d+[.)])\s*copias?\b", row["quote"], re.IGNORECASE
            ))), -row["score"], row["chunk_id"],
        ))
    for candidate in anchors[:24]:
        anchor = authorized[candidate["chunk_id"]]
        adjacent = _adjacent_answer(anchor, eligible)
        if adjacent and len(adjacent) <= limit - len(selected) + int(anchor["chunk_id"] in seen):
            for row in adjacent:
                add({**row, "adjacent_to": anchor["chunk_id"]}, "adjacent_answer", expanded=True)
            break
    for name, quota in (("identifier", 2), ("entity", 2), ("semantic", 3), ("context", 2)):
        added = 0
        for row in channels[name]:
            added += add(row, name)
            if added >= quota:
                break
    # Fusión por rango: BM25 y coseno no se comparan como si fueran la misma escala.
    fusion, representatives = Counter(), {}
    for name, rows in channels.items():
        counted = set()
        for rank, row in enumerate(rows):
            key = row["chunk_id"]
            if key not in counted:
                fusion[key] += 1 / (60 + rank + 1)
                representatives.setdefault(key, (row, name))
                counted.add(key)
    for key in sorted(fusion, key=lambda key: (-fusion[key], key)):
        row, name = representatives[key]
        add(row, name)
    return selected
