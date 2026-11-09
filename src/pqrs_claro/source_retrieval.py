"""Recuperación híbrida local; las coincidencias siempre conservan el texto original."""

from __future__ import annotations

import hashlib
import math
import re
import sys
import unicodedata
from array import array
from collections import Counter, OrderedDict, defaultdict
from functools import lru_cache
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
# The same Unicode normalization as before, applied in C instead of visiting
# every character in Python for each of the institutional library's passages.
_COMBINING_MARKS = dict.fromkeys(
    code for code in range(0x110000) if unicodedata.combining(chr(code))
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
    normalized = unicodedata.normalize("NFKD", text.casefold()).translate(_COMBINING_MARKS)
    normalized = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized)
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in _STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


TERMS_VERSION = "lexical-nfkd-v1"
DEFAULT_CONTEXT_CACHE_BYTES = 64 * 1024 * 1024
DEFAULT_BODY_STATISTICS_CACHE_BYTES = 64 * 1024 * 1024


def terms_key(chunk):
    text = f"{chunk.get('title', '')} {chunk['quote']}"
    return hashlib.sha256((TERMS_VERSION + "\n" + text).encode("utf-8")).hexdigest()


def _build_statistics(rows, document_terms):
    # Posting positions refer to this exact sequence of rows.
    lengths, postings = [], {}
    for position, row in enumerate(rows):
        document = document_terms(row)
        lengths.append(sum(document.values()))
        for term, count in document.items():
            entry = postings.get(term)
            if entry is None:
                entry = postings[term] = (array("I"), array("I"))
            entry[0].append(position)
            entry[1].append(count)
    return lengths, sum(lengths) / max(1, len(lengths)) or 1, postings


def _body_statistics_bytes(quotes, statistics):
    lengths, average, postings = statistics
    # Include referenced strings and numbers even if shared by other entries.
    return (256 + sys.getsizeof(quotes) + sum(map(sys.getsizeof, quotes))
            + sys.getsizeof(statistics) + sys.getsizeof(lengths) + sum(map(sys.getsizeof, lengths))
            + sys.getsizeof(average) + sys.getsizeof(postings)
            + sum(sys.getsizeof(term) + sys.getsizeof(entry) + sys.getsizeof(entry[0])
                  + sys.getsizeof(entry[1]) for term, entry in postings.items()))


class RetrievalIndex:
    """Reutiliza estadísticas por alcance, sin mezclar colecciones ni expedientes."""

    def __init__(self, chunks, *, prepared_terms=None,
                 context_cache_bytes=DEFAULT_CONTEXT_CACHE_BYTES,
                 body_statistics_cache_bytes=DEFAULT_BODY_STATISTICS_CACHE_BYTES):
        self.chunks = chunks
        self._statistics = {}
        self._body_statistics = OrderedDict()
        self._body_statistics_budget = max(0, body_statistics_cache_bytes)
        self._identities = {}
        self._calendar = {}
        self._context = OrderedDict()
        self._context_budget = max(0, context_cache_bytes)
        self._prepared_terms = prepared_terms or {}
        self.diagnostics = {"prepared_hits": 0, "computed": 0,
                            "context_hits": 0, "context_computed": 0,
                            "context_cache_bytes": 0,
                            "context_body_prepared_hits": 0, "context_body_computed": 0,
                            "body_statistics_builds": 0, "body_statistics_hits": 0,
                            "body_statistics_oversized": 0, "body_statistics_evictions": 0,
                            "body_statistics_cache_bytes": 0}

    def normalized_text(self, text):
        """Prepare context on demand, after scope filtering; never cache metadata."""
        cached = self._context.get(text)
        if cached is not None:
            self._context.move_to_end(text)
            self.diagnostics["context_hits"] += 1
            return cached[:2]
        normalized = _search_words(text)
        terms = Counter(tokenize(normalized))
        self.diagnostics["context_computed"] += 1
        # Conservative estimate includes the original key even if the corpus
        # already owns it, plus token/count objects and an LRU entry allowance.
        size = (sys.getsizeof(text) + sys.getsizeof(normalized) + sys.getsizeof(terms)
                + sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in terms.items()) + 256)
        if size <= self._context_budget:
            while (self._context and
                   self.diagnostics["context_cache_bytes"] + size > self._context_budget):
                _, (_, _, old_size) = self._context.popitem(last=False)
                self.diagnostics["context_cache_bytes"] -= old_size
            self._context[text] = normalized, terms, size
            self.diagnostics["context_cache_bytes"] += size
        return normalized, terms

    def calendar_features(self, quote):
        """Share only date features of identical text, never source metadata."""
        if quote not in self._calendar:
            self._calendar[quote] = _calendar_features(quote)
        return self._calendar[quote]

    def body_context_terms(self, row):
        """Derive normalized body counts from the content-keyed lexical index."""
        document = self._prepared_terms.get(terms_key(row))
        if document is None:
            document = Counter(tokenize(row["quote"]))
            title = {}
            self.diagnostics["context_body_computed"] += 1
        else:
            title = Counter(tokenize(str(row.get("title", ""))))
            self.diagnostics["context_body_prepared_hits"] += 1
        terms = Counter()
        for word, count in document.items():
            frequency = count - title.get(word, 0)
            if frequency > 0:
                # _search_words transforms each lexical token independently.
                # The second tokenization also removes any resulting stopword.
                for normalized in _calendar_word_tokens(word):
                    terms[normalized] += frequency
        return terms

    def identity(self, request, chunk, kind, number):
        if not kind or kind == "documento":
            return 0
        query_key = (request.get("title", ""), request.get("description", ""))
        identities = self._identities.setdefault(query_key, {})
        key = chunk["chunk_id"]
        title, filename, quote = chunk.get("title", ""), chunk.get("filename", ""), chunk["quote"]
        cached = identities.get(key)
        if cached and cached[0] == title and cached[1] == filename and cached[2] == quote:
            return cached[3]
        identity = document_matches(request, chunk, kind)
        named = bool(identity and number and re.search(
            rf"(?<!\d){re.escape(number)}(?!\d)", f"{title} {filename}",
        ))
        rank = int(identity) + int(named)
        identities[key] = (title, filename, quote, rank)
        return rank

    def _document_terms(self, chunk):
        document = self._prepared_terms.get(terms_key(chunk))
        if document is None:
            self.diagnostics["computed"] += 1
            return Counter(tokenize(f"{chunk.get('title', '')} {chunk['quote']}"))
        self.diagnostics["prepared_hits"] += 1
        return document

    def statistics(self, eligible):
        key = tuple((str(chunk["chunk_id"]), chunk.get("title", ""), chunk["quote"])
                    for chunk in eligible)
        statistics = self._statistics.get(key)
        if statistics is None:
            statistics = self._statistics[key] = _build_statistics(eligible, self._document_terms)
        return statistics

    def body_statistics(self, rows):
        """Reuse numeric postings for an ordered sequence of normalized bodies."""
        # Ranking reads identifiers and citations from the current rows. For
        # body-only BM25, identical ordered quotes yield identical frequencies.
        budget = self._body_statistics_budget
        quotes = tuple(row["quote"] for row in rows) if budget else ()
        entry = self._body_statistics.get(quotes)
        if entry is not None:
            self._body_statistics.move_to_end(quotes)
            self.diagnostics["body_statistics_hits"] += 1
            return entry[0]
        self.diagnostics["body_statistics_builds"] += 1
        statistics = _build_statistics(rows, self.body_context_terms)
        if not budget:
            return statistics
        size = _body_statistics_bytes(quotes, statistics)
        if size > budget:
            self.diagnostics["body_statistics_oversized"] += 1
            return statistics
        while self.diagnostics["body_statistics_cache_bytes"] + size > budget:
            _, evicted = self._body_statistics.popitem(last=False)
            self.diagnostics["body_statistics_cache_bytes"] -= evicted[1]
            self.diagnostics["body_statistics_evictions"] += 1
        self._body_statistics[quotes] = (statistics, size)
        self.diagnostics["body_statistics_cache_bytes"] += size
        return statistics


def _rank(request, eligible, *, index=None, query=None, statistics=None):
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
    if statistics is None:
        statistics = index.statistics(eligible)
    lengths, average_length, postings = statistics
    scores = Counter()
    matches = {}
    for term in sorted(query_terms):
        occurrences = postings.get(term)
        if occurrences is None:
            continue
        positions, counts = occurrences
        inverse_frequency = math.log1p(
            (len(eligible) - len(positions) + 0.5) / (len(positions) + 0.5)
        )
        for position, count in zip(positions, counts):
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


def _eligible_chunks(request, chunks):
    return [row for row in chunks if row.get("category") in _EVIDENCE_CATEGORIES
            and row.get("validity") != "superseded" and str(row.get("quote") or "").strip()
            and source_in_scope(request, row)]


class _PassageGroups:
    """Rows of one authorized request, grouped in input order by source version."""

    def __init__(self, eligible):
        self.rows = eligible
        self.by_id = {}
        self.by_source = defaultdict(list)
        self.historical = []
        self._ordered = {}
        for row in eligible:
            self.by_id[row["chunk_id"]] = row
            self.by_source[row["source_id"]].append(row)
            if row.get("category") == "historical_response":
                self.historical.append(row)

    def following(self, anchor, limit):
        source = anchor["source_id"]
        if source not in self._ordered:
            # Stable sort retains input order when PDF coordinates coincide.
            ordered = sorted(self.by_source[source], key=lambda row: (
                int(row.get("page", 0)), int(row.get("line_start", 1))))
            positions = {}
            for position, row in enumerate(ordered):
                positions.setdefault(row["chunk_id"], position)
            self._ordered[source] = ordered, positions
        ordered, positions = self._ordered[source]
        start = positions[anchor["chunk_id"]] + 1
        return ordered[start:start + limit]


def _answer_chunks(eligible: list[dict[str, Any]], *, historical=None) -> list[dict[str, Any]]:
    """Detecta un inicio literal de contestación; no infiere por posición final."""
    boundaries: dict[str, tuple[int, int]] = {}
    if historical is None:
        historical = (row for row in eligible if row.get("category") == "historical_response")
    for chunk in historical:
        match = _ANSWER_START.search(chunk["quote"])
        if not match:
            continue
        position = (
            int(chunk.get("page", 0)),
            int(chunk.get("line_start", 1)) + chunk["quote"][: match.start()].count("\n"),
        )
        document_id = str(chunk["document_id"])
        boundaries[document_id] = min(position, boundaries.get(document_id, position))
    if not boundaries:
        return []
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
    request: dict[str, Any], chunks: list[dict[str, Any]], limit: int = 24, *, index=None,
    ranked=None, passages=None,
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
    if passages is None:
        passages = _PassageGroups(_eligible_chunks(request, chunks))
    eligible = passages.rows
    general = _document_budget(
        ranked if ranked is not None else _rank(request, eligible, index=index), max(32, limit)
    )
    answers = _document_budget(
        _rank(request, _answer_chunks(eligible, historical=passages.historical), index=index),
        max(32, limit),
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


def _topic_variant(word):
    """Keep the phrase pattern and its finite vocabulary together."""
    if re.fullmatch(r"constancias?|certificados?|certificaciones?|certificacion", word):
        return (r"(?:constancias?|certificados?|certificacion(?:es)?)",
                ("constancia", "constancias", "certificado", "certificados",
                 "certificacion", "certificaciones"))
    if word.endswith(("ica", "ico", "icas", "icos")):
        stem = re.sub(r"ic[oa]s?$", "", word)
        return (re.escape(stem) + r"ic[oa]s?",
                tuple(stem + ending for ending in ("ica", "ico", "icas", "icos")))
    if len(word) > 4 and word.endswith(("as", "os")):
        return re.escape(word[:-1]) + "s?", (word[:-1], word)
    return re.escape(word), (word,)


def _topic_passages(request, eligible, *, index=None, postings=None, originals=None):
    """Busca el tema breve en el cuerpo, sin que el título del archivo lo suplante.

    Las variantes sólo amplían candidatos. No acreditan equivalencia jurídica,
    pertinencia, vigencia ni identidad del documento solicitado.
    """
    generic = {"tramite", "obtener", "pasos", "seguir", "necesarios", "necesarias",
               "solicitante", "persona", "identificar", "explicar", "solicitud"}
    words = [word for word in tokenize(str(request.get("title") or ""))
             if word not in generic]
    if len(words) < 2:
        return []

    variants = {word: _topic_variant(word) for word in words}
    pairs = list(zip(words, words[1:]))[:4]
    patterns = [re.compile(r"\b" + variants[left][0] + r"\b(?:\W+\w+){0,3}\W+\b"
                           + variants[right][0] + r"\b") for left, right in pairs]
    candidates = eligible
    if index is not None:
        required = dict.fromkeys(word for pair in pairs for word in pair)
        # A true phrase match contains both ASCII words as whole tokens in the
        # same normalized body. The lexical index also includes titles and splits
        # letters/digits: these can only add false positives, which the unchanged
        # phrase regex below rejects. If tokenization ever drops a variant (for
        # example a stopword), fall back to scanning rather than lose that match.
        if all(tokenize(form) == [form] for word in required for form in variants[word][1]):
            if postings is None:
                postings = index.statistics(eligible)[2]
            positions = {}
            for word in required:
                positions[word] = set()
                for form in variants[word][1]:
                    entry = postings.get(form)
                    if entry is not None:
                        positions[word].update(entry[0])
            selected = set()
            for left, right in pairs:
                selected.update(positions[left].intersection(positions[right]))
            # Original order matters when equal normalized bodies are deduplicated.
            candidates = (eligible[position] for position in sorted(selected))
    matches, expanded, seen = [], set(words), set()
    for row in candidates:
        body = unicodedata.normalize("NFKD", row["quote"].casefold()).translate(_COMBINING_MARKS)
        if any(pattern.search(body) for pattern in patterns):
            normalized = " ".join(body.split())
            if normalized in seen:
                continue
            seen.add(normalized)
            # Las formas que activaron la coincidencia también deben puntuar;
            # «certificados académicos» no contiene literalmente «constancia académica».
            for word in words:
                expanded.update(re.findall(r"\b" + variants[word][0] + r"\b", body))
            # Puntuar el contenido del pasaje; un nombre largo no añade evidencia.
            matches.append({**row, "title": ""})
    if not matches:
        return []
    if originals is None:
        originals = {row["chunk_id"]: row for row in eligible}
    ranked = _rank({}, matches, query=" ".join(sorted(expanded)))
    return [originals[row["chunk_id"]] for row in _document_budget(ranked, 12)]


def _adjacent_answer(anchor, eligible, *, passages=None):
    """Una pregunta explícita en un oficio y su contestación contigua, sin sintetizar.

    Los párrafos DOCX pueden ser secciones distintas. PDF conserva cada fragmento
    con su página y líneas. Nunca se salta a otra fuente ni a otra pregunta.
    """
    if anchor.get("category") != "historical_response" or not _QUESTION.match(anchor["quote"]):
        return []
    if passages is None:
        passages = _PassageGroups(eligible)
    result, size = [anchor], len(anchor["quote"])
    for following in passages.following(anchor, 7):
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


def _targeted_passages(request, eligible, *, index, passages=None):
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
    if not targets:
        return []
    if passages is None:
        passages = _PassageGroups(eligible)
    result = [(row, "requested_passage") for row in targets]
    # Si el literal termina justo antes de «Respuesta», conservar su continuación
    # inmediata aunque no repita entidades y BM25 le dé pocos puntos.
    for anchor in targets[:1]:
        if not literal_rows or anchor not in literal_rows:
            continue
        for row in passages.following(anchor, 1):
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
        siblings = passages.by_source[source_id]
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
    eligible = _eligible_chunks(request, chunks)
    query = " ".join(str(request.get(k) or "") for k in ("title", "description"))
    if not tokenize(query) or not eligible:
        return []
    passages = _PassageGroups(eligible)
    index = index or RetrievalIndex(eligible)
    # These channels read the same ordered, permission-filtered rows. Resolve
    # their shared postings once. Subset rankings below resolve their own IDF.
    statistics = index.statistics(eligible)
    general = _rank(request, eligible, index=index, statistics=statistics)
    baseline = _baseline(request, eligible, limit, index=index, ranked=general, passages=passages)
    channels = {"lexical": baseline}
    context_queries = request.get("retrieval_queries") or [request.get("retrieval_context", "")]
    if isinstance(context_queries, str):
        context_queries = [context_queries]
    context_rows = []
    for context_query in context_queries[:3]:
        if isinstance(context_query, str) and context_query.strip():
            context_rows.extend(_rank(request, eligible, index=index, query=context_query,
                                      statistics=statistics)[:24])
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
        entities = [c for c in _rank(request, eligible, index=index, query=entity_query,
                                     statistics=statistics)
                    if emails.intersection(_EMAIL.findall(c["quote"].casefold()))]
        entities.sort(key=lambda c: (
            len(set(_EMAIL.findall(c["quote"].casefold()))) > 4,
            -c["score"], c["chunk_id"],
        ))
    channels["entity"] = entities
    channels["semantic"] = semantic.rank(query, eligible, limit=40) if semantic else []
    # Revalida IDs e identidad del fragmento incluso para proveedores enchufables.
    authorized = passages.by_id
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
            6 if channel in {"document_content", "semantic"} else
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
    for row, channel in _targeted_passages(request, eligible, index=index, passages=passages):
        add(row, channel, expanded=True)
    for row in baseline[:8]:
        if row.get("document_identity_rank", 0):
            add(row, "lexical")
    # Las preguntas por fechas necesitan pasajes con fechas explícitas, no solo
    # apartados que repitan "presentación", "calendario" o "convocatoria".
    for row in _date_passages(request, eligible, index=index, postings=statistics[2]):
        add(row, "calendar")
    ranked_by_id = {row["chunk_id"]: row for row in general}
    # Reserva el tema del título atómico antes del cupo de contestaciones previas.
    # Así las fórmulas genéricas de otros trámites no ocupan toda la selección.
    for row in _topic_passages(request, eligible, index=index, postings=statistics[2],
                               originals=authorized)[:6]:
        add(ranked_by_id.get(row["chunk_id"], row), "topic")
    # El asunto ayuda a localizar el documento; la pregunta atómica selecciona
    # su contenido. Una portada coincidente no sustituye el pasaje de respuesta.
    for row in _document_content(request, eligible, index=index, passages=passages):
        add(ranked_by_id.get(row["chunk_id"], row), "document_content")
    # Protege resultados ya útiles, incluida la prioridad del objeto pedido.
    for row in baseline[:8]:
        add(row, "lexical")
    # Solo una pareja contigua por consulta: la pregunta atómica sigue dominando.
    # La prioridad de identidad localiza el archivo pedido; no debe esconder la
    # pregunta casi literal de un oficio cuando buscamos su contestación contigua.
    question_chunks = []
    for candidate in passages.historical:
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
        adjacent = _adjacent_answer(anchor, eligible, passages=passages)
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


def _search_words(text, *, expand=False):
    """Variantes de consulta, nunca cambios al texto citado ni hechos nuevos."""
    words = tokenize(text)
    normalized = []
    for word in words:
        if word.endswith("iones"):
            word = word[:-2]
        elif len(word) > 4 and word.endswith(("as", "os")):
            word = word[:-1]
        normalized.append(word)
    # Equivalencias generales de preguntas informativas, sin respuestas de dominio.
    variants = {"tiempo": "duracion", "porcentaje": "ponderacion peso"}
    extra = [variants[w] for w in normalized if w in variants] if expand else []
    return " ".join(normalized + extra)


_EXPLICIT_DATE = re.compile(
    r"\b\d{1,2}\s+(?:y\s+\d{1,2}\s+)?de\s+"
    r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b"
    r"|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\b"
)


@lru_cache(maxsize=8192)
def _calendar_word_tokens(word):
    """Reutiliza palabras, nunca permisos, resultados ni fragmentos de otro caso."""
    return tuple(tokenize(_search_words(word)))


def _calendar_features(quote):
    features = []
    for match in _EXPLICIT_DATE.finditer(quote.casefold()):
        offset = max(0, match.start() - 180)
        nearby = quote[offset:match.end() + 180]
        words = []
        for word in re.finditer(r"\w+", nearby):
            tokens = _calendar_word_tokens(word[0])
            if tokens:
                distance = max(0, match.start() - offset - word.end(),
                               offset + word.start() - match.end())
                words.append((tokens, distance))
        features.append(words)
    return features


def _calendar_candidates(event, eligible, index, postings=None):
    """A lexical superset of calendar hits, including clipped/raw Unicode words."""
    if index is None or any(word in stopword for word in event for stopword in _STOPWORDS):
        # Raw word boundaries and the 180-character window can expose part of a
        # stopword absent from the index: e.g. "infor" inside "informacion".
        return eligible
    if postings is None:
        postings = index.statistics(eligible)[2]
    positions = set()
    for term, (matches, _) in postings.items():
        # Calendar features split raw Unicode before normalizing and may clip a
        # word at either window edge. The resulting ASCII event (>3 characters)
        # is still a substring of a full lexical token, even when combining
        # marks join words, letters/digits split, or _search_words trims a suffix.
        # Exact-token lookup would lose those hits. Titles may add candidates;
        # unchanged date/window/proximity checks below decide actual relevance.
        if any(word in term for word in event):
            positions.update(matches)
    return (eligible[position] for position in sorted(positions))


def _normalized_passage(row, text, index, prepared, *, body=False):
    if index is None:
        return {**row, "title": "", "quote": _search_words(text)}
    if body:
        # Body statistics read the original title/content key to derive counts.
        return row
    normalized, terms = index.normalized_text(text)
    passage = {**row, "title": "", "quote": normalized}
    prepared[terms_key(passage)] = terms
    return passage


def _rank_context(rows, query, index, prepared, *, body=False):
    if not rows:
        return []
    if body and index is not None:
        return _rank({}, rows, query=query, index=index, statistics=index.body_statistics(rows))
    local = RetrievalIndex(rows, prepared_terms=prepared) if index is not None else None
    return _rank({}, rows, query=query, index=local)


def _date_passages(request, eligible, *, index=None, postings=None):
    """Reserva dos candidatos fechados; no interpreta la fecha ni su vigencia.

    Los fragmentos ya están filtrados por permisos. Se exige una coincidencia
    del asunto de la pregunta cerca de la fecha y se conserva el texto original.
    """
    query = " ".join(str(request.get(k) or "") for k in ("title", "description"))
    words = set(tokenize(_search_words(query)))
    if not words.intersection({"fecha", "calendario"}) and not re.search(
        r"\bcu[aá]ndo\b", query, re.IGNORECASE
    ):
        return []
    generic = {"fecha", "calendario", "cuando", "prevista", "previsto", "previstas",
               "previstos", "presentacion", "informar", "dentro", "convocatoria",
               "periodo", "consulta", "programada", "programado", "solicita",
               "correspondiente", "conocer"}
    event = {w for w in words - generic if len(w) > 3 and not w.isdigit()}
    if not event:
        return []
    candidates, originals, proximity, prepared = [], {}, {}, {}
    for row in _calendar_candidates(event, eligible, index, postings):
        # Tokenizar toda la página diluye la relación. La ventana admite títulos
        # y celdas consecutivas en calendarios extraídos de PDF.
        relations = []
        features = (index.calendar_features(row["quote"]) if index is not None
                    else _calendar_features(row["quote"]))
        for words_near_date in features:
            hits = [(tokens[0], distance) for tokens, distance in words_near_date
                    if event.intersection(tokens)]
            if hits:
                relations.append((len({word for word, distance in hits}),
                                  -min(distance for word, distance in hits)))
        if not relations:
            continue
        proximity[row["chunk_id"]] = max(relations)
        originals[row["chunk_id"]] = row
        candidates.append(_normalized_passage(row, row["quote"], index, prepared, body=True))
    ranked = _rank_context(candidates, _search_words(query, expand=True),
                           index, prepared, body=True)
    # Relate the date to the requested event, not to repeated words elsewhere
    # on the page (e.g. historical regulations or registration deadlines).
    ranked.sort(key=lambda r: proximity[r["chunk_id"]], reverse=True)
    return [originals[r["chunk_id"]] for r in ranked[:2]]


def _document_content(request, eligible, *, index=None, passages=None):
    """Recuperación acotada dentro de hasta tres documentos de tema coincidente.

    El corpus ya está filtrado por permisos y versión. El asunto solo localiza
    documentos, nunca se convierte en evidencia ni sustituye la pregunta. Se
    requieren dos términos discriminantes coincidentes en metadatos, y luego
    coincidencia en el cuerpo. Se devuelven las citas originales sin normalizar.
    """
    query = " ".join(str(request.get(k) or "") for k in ("title", "description"))
    subject = str((request.get("context") or {}).get("subject") or "")[:1200]
    if passages is None:
        passages = _PassageGroups(eligible)
    metadata, prepared = [], {}
    for siblings in passages.by_source.values():
        row = siblings[0]
        metadata.append(_normalized_passage(row, " ".join(
            str(row.get(key) or "") for key in ("title", "filename", "historical_group")
        ), index, prepared))
    topic = _search_words(subject or query)
    generic = {"universidad", "institucional", "documento", "respuesta", "consulta", "solicita"}
    terms = {w for w in tokenize(topic) if len(w) >= 3 and w not in generic}
    matches = [row for row in metadata
               if len(terms.intersection(prepared[terms_key(row)] if index is not None
                                         else tokenize(row["quote"]))) >= 2]
    if not matches:
        return []
    # No favorecer documentos largos por repetir su título en cada fragmento.
    documents = _rank_context(matches, topic, index, prepared)[:3]
    result = []
    for document in documents:
        body = passages.by_source[document["source_id"]]
        if index is None:
            body = [_normalized_passage(row, row["quote"], index, prepared, body=True)
                    for row in body]
        # Reservar más que los dos primeros: títulos de trámite y referencias
        # al portal pueden puntuar por encima del contenido de la respuesta.
        # El cupo semántico conserva espacio adicional dentro del mismo archivo.
        for hit in _rank_context(body, _search_words(query, expand=True),
                                 index, prepared, body=True)[:4]:
            result.append(passages.by_id[hit["chunk_id"]])
    return result
