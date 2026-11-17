"""Indicios locales del objeto documental pedido, sin certificar su autenticidad."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any

from .request_intent import classify_request_intent, delivery_request_text

NORM_DOCUMENT_KINDS = frozenset({
    "ley", "decreto", "resolucion", "acuerdo", "circular", "reglamento",
    "estatuto", "ordenanza", "manual", "guia",
})
# Administrative document classes can sit between the kind and its number. Keep
# this bounded to naming modifiers: arbitrary prose must not bind another act's ID.
_NUMBER_PREFIX = (
    r"\s*(?:(?:rectoral|academico|academica|superior|administrativo|administrativa|"
    r"ministerial|municipal|departamental|nacional|distrital|organica|organico|"
    r"del\s+consejo\s+(?:academico|superior|de\s+facultad)|de\s+facultad)\s+)?"
    r"(?:(?:numero|nro\.?|no\.?|num\.?|#)\s*)?"
)
_DOCUMENT_KINDS = (
    "acta|contrato|resolucion|certificado|certificacion|expediente|informe|"
    "constancia|convenio|acuerdo|circular|oficio|registro|correo|respuesta|"
    "ley|decreto|reglamento|estatuto|ordenanza|manual|guia"
)
_DOCUMENT_NUMBER = r"\d+(?:-[a-zA-Z0-9]+)*"
_NUMBERED_TAIL = (rf"{_NUMBER_PREFIX}(?P<number>{_DOCUMENT_NUMBER})"
                  r"(?:\s+(?:de|del)\s+(?:ano\s+)?(?P<year>(?:19|20)\d{2}))?\b")
_NON_DOCUMENT_LABELS = frozenset({
    "articulo", "pagina", "linea", "seccion", "numeral", "inciso", "ano", "dia",
    "capitulo", "parrafo", "punto", "peticion", "solicitud", "documento", "archivo",
    "ejemplar", "copia", "del", "de", "la", "el",
})


@lru_cache(maxsize=4096)
def _plain(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )


def requested_document(request: dict[str, Any]) -> str | None:
    """Resguardo acotado para peticiones explícitas de entrega de documentos."""
    return delivery_document_target(request)["kind"]


def _explicit_numbered_objects(text):
    """Open document denomination, anchored to the object of the delivery command."""
    prefix = (r"\b(?:copias?|adjunt\w*|remit\w*|entreg\w*|envi\w*|facilit\w*)\s+"
              r"(?:(?:una?|el|la|los|las|unas|unos|integra|integras|completa|completas|"
              r"firmada|firmadas|autentica|certificada|disponible)\s+)*"
              r"(?:(?:de|del)\s+)?(?:(?:el|la|los|las)\s+)?")
    plain = _plain(text)
    found = _object_matches(prefix + r"(?P<kind>[a-z][a-z-]{2,35})" + _NUMBERED_TAIL, plain)
    if found:
        # One delivery command can coordinate several objects. Stop at a new
        # informational mandate so its object is not mistaken for another copy.
        copy_part = re.split(r"\b(?:y|e)\s+(?:explique[n]?|informe[n]?|indique[n]?|"
                             r"describa[n]?|compare[n]?|aclare[n]?)\b", plain, maxsplit=1)[0]
        coordinated = (r"(?:\b(?:y|e)|,)\s+(?:(?:de|del)\s+)?(?:(?:el|la|los|las)\s+)?"
                       r"(?P<kind>[a-z][a-z-]{2,35})" + _NUMBERED_TAIL)
        found.extend(_object_matches(coordinated, copy_part))
    return found


def _object_matches(pattern, text, *, capitalized=False):
    values = []
    for match in re.finditer(pattern, text, re.IGNORECASE):
        if capitalized and not text[match.start("kind")].isupper():
            continue
        kind = _plain(match["kind"])
        if kind in _NON_DOCUMENT_LABELS:
            continue
        identity = _plain(text[match.start("kind"):match.end()]).strip()
        modifiers = _identity_modifiers(text[match.end("kind"):match.start("number")])
        values.append({"kind": kind, "text": identity, "number": _plain(match["number"]),
                       "year": match["year"], "modifiers": modifiers,
                       "open_identity": kind not in _DOCUMENT_KINDS.split("|")})
    return values


def _identity_modifiers(text):
    return sorted(set(re.findall(r"[a-z]+", _plain(text)))
                  - {"no", "nro", "num", "numero", "de", "del"})


def _object_key(row):
    return row["kind"], row["number"], row["year"], tuple(row["modifiers"])


def _named_objects(text):
    """Named identities in the petition, independent of available library files."""
    pattern = rf"\b(?P<kind>{_DOCUMENT_KINDS})s?" + _NUMBERED_TAIL
    # A capitalized denomination followed by its own number is an explicit
    # name, even when a new document class is absent from the legacy vocabulary.
    # Structural page/article numbers are not documentary identities.
    open_pattern = (r"\b(?P<kind>[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ-]{2,35})"
                    + _NUMBERED_TAIL)
    result = {}
    for value in [*_object_matches(pattern, _plain(text)),
                  *_object_matches(open_pattern, text, capitalized=True),
                  *_explicit_numbered_objects(text)]:
        result.setdefault(_object_key(value), value)
    return list(result.values())


def _original_scope_text(request):
    """Only original scope; exclude other numbered requests, including their copies."""
    context = (request.get("context") or {}).get("document_context") or {}
    if (context.get("origin") != "original_petition" or context.get("truncated")
            or context.get("purpose") != "scope_only_not_evidence"):
        return ""
    other_ranges = [row for row in context.get("question_ranges", [])
                    if row.get("request_id") != request.get("id")]
    retained = []
    for excerpt in context.get("excerpts", []):
        page, first = excerpt.get("page"), excerpt.get("line_start")
        if type(page) is not int or type(first) is not int:
            continue
        for offset, line in enumerate(str(excerpt.get("quote") or "").splitlines()):
            number = first + offset
            if not any(row.get("page") == page
                       and type(row.get("line_start")) is int
                       and type(row.get("line_end")) is int
                       and row["line_start"] <= number <= row["line_end"]
                       for row in other_ranges):
                retained.append(line)
    return "\n".join(retained)


def delivery_document_target(request: dict[str, Any]) -> dict:
    """Resolve an anaphoric copy only from its unique named object in the petition.

    A source candidate can establish whether a target is located, never what was
    requested. Missing/ambiguous identity remains a clarification, not absence.
    """
    empty = {"status": "not_requested", "kind": None, "text": "", "origin": None,
             "references": []}
    if not classify_request_intent(request)["document_delivery_requested"]:
        return empty
    delivery = delivery_request_text(request)
    explicit = list({_object_key(row): row
                     for row in _explicit_numbered_objects(delivery)}.values())
    if len(explicit) == 1:
        named = explicit[0]
        return {**empty, "status": "explicit", "kind": named["kind"], "text": delivery,
                "origin": "delivery_clause", "references": [named["text"]],
                "open_identity": named["open_identity"], "identity": named}
    if len(explicit) > 1:
        return {**empty, "status": "ambiguous", "kind": "documento", "text": delivery,
                "origin": "delivery_clause", "references": [row["text"] for row in explicit]}
    kind = referenced_document({"description": delivery})
    if kind and kind != "documento":
        return {**empty, "status": "explicit", "kind": kind,
                "text": delivery, "origin": "delivery_clause"}
    unresolved = {**empty, "status": "unresolved", "kind": "documento", "text": delivery}
    # The object of a reference/attachment relation is not the document that
    # mentions it. With no explicit identity this requires clarification.
    if re.search(r"\b(?:anexos?|adjuntos?)\b|"
                 r"\b(?:documento|archivo|ejemplar)\b[^.;!?]{0,100}\bque\b"
                 r"[^.;!?]{0,80}\b(?:mencion\w*|cit\w*|refer\w*|anex\w*|adjunt\w*)\b",
                 delivery):
        return unresolved
    own_text = str(request.get("description") or request.get("title") or "")
    origins = [
        ("request", own_text),
        ("request_source_refs", "\n".join(str(row.get("quote") or "")
                                        for row in request.get("source_refs", []))),
        ("original_petition_scope", _original_scope_text(request)),
    ]
    for origin, text in origins:
        objects = _named_objects(text)
        if len(objects) > 1:
            return {**unresolved, "status": "ambiguous", "origin": origin,
                    "references": [row["text"] for row in objects]}
        if objects:
            target = objects[0]
            return {**unresolved, "status": "resolved", "kind": target["kind"],
                    "text": "copia de " + target["text"], "origin": origin,
                    "references": [target["text"]], "open_identity": target["open_identity"],
                    "identity": target}
    return unresolved


def referenced_document(request: dict[str, Any]) -> str | None:
    """Indicio para recuperación: mencionar un envío pasado no pide entregar hoy.

    Conserva el criterio previo de búsqueda, separado de los guardas que generan
    pendientes documentales. No clasifica actuaciones ni certificaciones futuras.
    """
    text = _plain(f"{request.get('title', '')} {request.get('description', '')}")
    delivery = re.search(r"\b(copias?|adjunt\w*|remit\w*|entreg\w*|envi\w*|facilit\w*)\b", text)
    if not delivery:
        return None
    documents = re.findall(
        r"\b(acta|contrato|resolucion|certificado|certificacion|expediente|informe|"
        r"documento|constancia|convenio|acuerdo|circular|oficio|registro|correo|"
        r"respuesta|ley|decreto|reglamento|estatuto|ordenanza|manual|guia)s?(?![a-z])",
        _plain(f"{request.get('description', '')} {request.get('title', '')}"),
    )
    # Una envoltura genérica no sustituye al objeto: «documento que contiene el acta».
    return next((kind for kind in documents if kind != "documento"), None) or (
        "documento" if documents or "copia" in text else None
    )


def requested_document_number(request: dict[str, Any], kind: str) -> str | None:
    target = delivery_document_target(request)
    identity = target.get("identity")
    if identity and identity["kind"] == kind:
        return identity["number"]
    text = target["text"] or _plain(
        f"{request.get('description', '')} {request.get('title', '')}"
    )
    match = re.search(
        rf"\b{kind}s?{_NUMBER_PREFIX}({_DOCUMENT_NUMBER})",
        text,
    )
    return match.group(1) if match else None


def _document_header(source: dict[str, Any], kinds: str) -> re.Match[str] | None:
    raw = str(source.get("quote") or "")
    quote = _plain(raw)
    direct = re.search(rf"(?m)^\s*{kinds}s?(?![a-z])[^\n]*", quote)
    if direct:
        return direct
    # A short uppercase heading can include a letterhead before its document
    # identity. Restrict this to the opening lines of the normative original;
    # ordinary references inside its body remain mere mentions.
    if (source.get("category") not in {"national_norm", "institutional_norm"}
            or source.get("page") != 1 or source.get("line_start") != 1):
        return None
    offset = 0
    for line in raw.splitlines(keepends=True)[:3]:
        if line.isupper() and len(line.strip()) <= 180:
            heading = re.match(
                rf"\s*[a-z ()/ ]{{1,100}}\s[-–—|:]\s+(?P<identity>{kinds}s?\b[^\n]*)",
                _plain(line),
            )
            prefix = _plain(line)[:heading.start("identity")] if heading else ""
            if heading and not re.search(
                r"\b(?:correo|adjunt\w*|anex\w*|remis\w*|remit\w*|env[ií]\w*|"
                r"referenc\w*|mencion\w*|copias?)\b", prefix,
            ):
                return re.compile(rf"{kinds}s?\b[^\n]*").match(
                    quote, offset + heading.start("identity")
                )
        offset += len(_plain(line))
    return None


def normative_copy_matches(request: dict[str, Any], source: dict[str, Any], kind: str) -> bool:
    """Identify the requested normative original, never attest delivery or a case fact.

    The library checks the original hash and version before producing candidates.
    Here we require that identity metadata survives, plus a matching literal header;
    an attachment mention in another file never acquires the document role.
    """
    target = delivery_document_target(request)
    if target["kind"] != kind or target["status"] not in {"explicit", "resolved"}:
        return False
    permitted_kind = kind in NORM_DOCUMENT_KINDS or (
        target.get("open_identity") is True and target["kind"] == kind)
    return permitted_kind and _identified_copy_matches(request, source, kind)


def available_copy_matches(request: dict[str, Any], source: dict[str, Any]) -> bool:
    """Local identity of the requested stored copy, never authenticity or dispatch.

    Candidates come from the library's hash-checked, permission-scoped snapshot.
    Requiring that metadata here prevents a title-only match from waiving checks.
    """
    target = delivery_document_target(request)
    if target["status"] not in {"explicit", "resolved"}:
        return False
    if source.get("category") not in {
        "national_norm", "institutional_norm", "case_evidence",
        "historical_response", "historical_attachment",
    }:
        return False
    return _identified_copy_matches(request, source, target["kind"])


def _identified_copy_matches(request, source, kind):
    target = delivery_document_target(request)
    if not document_matches(request, source, kind):
        return False
    if (not source.get("source_id") or not source.get("document_id")
            or type(source.get("version")) is not int or source["version"] < 1
            or not re.fullmatch(r"[a-fA-F0-9]{64}", str(source.get("sha256") or ""))
            or source.get("is_latest") is not True or source.get("validity") == "superseded"):
        return False
    text = target["text"]
    reference = re.search(rf"\b{kind}s?\b[^.;!?\n]*", text)
    if reference is None:
        return False
    quote = _plain(str(source.get("quote") or ""))
    header = _document_header(source, kind)
    header_lines = quote[header.start():].splitlines()[:4] if header else []
    number = requested_document_number(request, kind)
    if number:
        wanted = target.get("identity") or next((row for row in _named_objects(reference.group())
                                                if row["kind"] == kind), None)
        identified = _numbered_header_identity(source, kind)
        if not wanted or not identified or identified["number"] != wanted["number"]:
            return False
        if wanted.get("year") and identified.get("year") != wanted["year"]:
            return False
        # An explicit conflicting catalog identity is not repaired by borrowing
        # a matching number/year from another reference elsewhere in the file.
        named = next((row for row in _named_objects(str(source.get("title") or ""))
                      if row["kind"] == kind), None)
        if named and (named["number"] != wanted["number"]
                      or (wanted.get("year") and named.get("year")
                          and named["year"] != wanted["year"])):
            return False
        if not set(wanted["modifiers"]).issubset(identified["modifiers"]):
            return False
    # Without a number, preserve the requested subject rather than accepting any
    # regulation of the same generic kind (e.g. housing vs. travel grants).
    if not number:
        identity = re.split(r"\s+(?:y|e)\s+(?:explique[n]?|informe[n]?|"
                            r"describa[n]?|indique[n]?)\b",
                            reference.group(), maxsplit=1)[0]
        generic = {kind, "de", "del", "la", "el", "los", "las", "en", "para", "por",
                   "sobre", "un", "una", "su", "que", "copia", "integra", "completa"}
        words = {word for word in re.findall(r"[a-z]+", identity)
                 if len(word) > 2 and word not in generic}
        name = _plain(f"{source.get('title', '')} {source.get('filename', '')}").replace("_", " ")
        identity_words = set(re.findall(r"[a-z]+", name + " " + "\n".join(header_lines)))
        if not words or not words.issubset(identity_words):
            return False
    return True


def _numbered_header_identity(source, kind):
    """Bind the complete identifier and year to their own header, never nearby acts."""
    header = _document_header(source, kind)
    if not header:
        return None
    block = _plain(str(source.get("quote") or ""))[header.start():]
    match = re.match(rf"\s*(?P<kind>{kind})s?" + _NUMBERED_TAIL, block)
    if not match:
        return None
    result = {"kind": kind, "number": match["number"], "year": match["year"],
              "modifiers": _identity_modifiers(block[match.end("kind"):match.start("number")])}
    # The immediately following date line may carry the document's own year.
    # A sentence about another act is never treated as a date/header continuation.
    if result["year"] is None:
        tail = block[match.end():]
        lines = tail.splitlines()
        if lines and not lines[0].strip():
            date = next((line.strip() for line in lines[1:] if line.strip()), "")
            month = ("enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
                     "octubre|noviembre|diciembre")
            date_prefix = r"(?:fecha\s*:\s*)?(?:[a-z ]{2,60},\s*)?"
            dated = re.fullmatch(
                date_prefix + rf"(?:\d{{1,2}}\s+de\s+(?:{month})\s+de\s+"
                r"(?P<year>(?:19|20)\d{2})|\d{1,2}[/.-]\d{1,2}[/.-]"
                r"(?P<numeric_year>(?:19|20)\d{2})|(?P<iso_year>(?:19|20)\d{2})"
                r"[-/]\d{1,2}[-/]\d{1,2})[ .]*", date)
            if dated:
                result["year"] = next(value for value in dated.groups() if value)
    return result


def requested_certification(request: dict[str, Any]) -> bool:
    """Distingue pedir una certificación de solicitar una explicación de hechos."""
    return classify_request_intent(request)["certification_requested"]


def document_matches(request: dict[str, Any], source: dict[str, Any], kind: str) -> bool:
    """Comprueba indicios de identidad; no certifica autenticidad ni integridad del archivo."""
    if kind == "documento":
        return False
    name = _plain(f"{source.get('title', '')} {source.get('filename', '')}").replace("_", " ")
    kinds = "(?:oficio|respuesta)" if kind == "respuesta" else kind
    if kind != "correo" and not re.search(rf"\b{kinds}s?(?![a-z])", name):
        return False
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
        key = (number if re.search(r"[a-z]", number) else
               parts[-2] if len(parts) > 1 and len(parts[-1]) == 4 else parts[-1])
        if not re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", name):
            return False
    header = _document_header(source, kinds)
    if header and number and not re.search(
        rf"(?<![a-z0-9]){re.escape(number)}(?![a-z0-9-])", header.group()
    ):
        header = None
    numbered_header = number and re.search(rf"(?m)^\s*{re.escape(number)}\s*$", quote)
    return bool(header or numbered_header)


def numbered_document_references(text: str) -> list[str]:
    """Referencias explícitas para conservar otros componentes de un mismo faltante."""
    return list(dict.fromkeys(f"{row['kind']} {row['number']}"
                             for row in _named_objects(text.replace("\u00ad", ""))))


def named_document_candidates(text: str, candidates: list[dict[str, Any]]) -> list[dict]:
    """Localiza por nombre y número; no convierte una mención en identidad acreditada.

    Solo consulta el nombre del archivo, nunca números extraídos de su contenido o
    relaciones de catálogo. Un correo titulado con su adjunto tampoco es el adjunto.
    """
    references = [reference.split(" ", 1) for reference in numbered_document_references(text)]
    if not references:
        return []
    located = []
    for source in candidates:
        if source.get("category") not in {
            "historical_response", "historical_attachment", "case_evidence",
            "national_norm", "institutional_norm",
        }:
            continue
        name = _plain(
            f"{source.get('filename') or ''} {source.get('title') or ''}"
        ).replace("_", " ")
        if re.search(r"\b(?:gmail|fwd|correo|notificacion|remision)\b", name):
            continue
        for kind, number in references:
            if (source.get("category") in {"national_norm", "institutional_norm"}
                    and kind in _DOCUMENT_KINDS.split("|") and kind not in NORM_DOCUMENT_KINDS):
                continue
            parts = number.split("-")
            year = parts[-1] if len(parts) > 1 and len(parts[-1]) == 4 else None
            key = number if re.search(r"[a-z]", number) else parts[-2] if year else parts[-1]
            kinds = r"(?:oficio|respuesta)" if kind in {"oficio", "respuesta"} else kind
            if not re.search(rf"\b{kinds}s?\b", name):
                continue
            if not re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", name):
                continue
            # No equiparar el mismo número de oficio de años diferentes.
            named_years = re.findall(rf"(?<!\d){re.escape(key)}[- ](\d{{4}})(?!\d)", name)
            if year and named_years and year not in named_years:
                continue
            quote = _plain(str(source.get("quote") or ""))
            if re.search(
                r"gmail\s*[-:]|https?://mail\.google\.com/|(?m:^\s*(?:para|to):)", quote
            ):
                break
            located.append(source)
            break
    return located
