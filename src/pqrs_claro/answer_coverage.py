"""Trace answer units to authorized passages; semantic relevance remains a review task.

The helpers copy source text, never manufacture it. They validate references and
review links, not whether a paraphrased claim is entailed or a rule is applicable.
"""

import hashlib
import json
import re
import unicodedata
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, ValidationError

from .models import DomainError, StrictModel
from .request_requirements import build_requirements
from .source_passages import PassageRange
from .source_retrieval import source_in_scope

MAX_UNITS = 64
MAX_UNIT_CITATIONS = 8
UnitKind = Literal["answer", "condition", "exception", "basis", "sequence", "context"]
DETAILS_VERSION = 1
MAX_DETAILS_PER_UNIT = 12

UNIT_CHECK_GUIDANCE = """
Comprueba cada unidad required=true exactamente una vez en unit_checks, usando su
unit_id U: answered, pending, omitted u out_of_scope. answered exige párrafos
actuales con contenido propio y todas las fuentes citadas por la unidad entre esos
párrafos; cada párrafo señalado debe citar alguna de ellas. Repetir el claim del inventario
o citar el plan no prueba que el borrador lo diga ni que la fuente lo sostenga.
Conserva el supuesto, actor, condición, excepción y alcance de cada unidad.
pending requiere una brecha específica todavía abierta, no sólo metadata_only ni
un control cerrado. Todos sus vínculos deben ser brechas de evidence que bloqueen
la aprobación; actuaciones futuras de fulfillment no cubren contenido omitido.
omitted identifica contenido material que falta corregir.
Si hay un párrafo que intenta cubrir parcialmente la unidad, omitted indica su
paragraph_indexes para reparar allí; no señales un párrafo de otro supuesto.
out_of_scope explica por qué no responde ni condiciona o limita lo preguntado; no
se usa para eludir una contradicción entre regímenes potencialmente aplicables.
Las unidades opcionales de contexto no crean obligaciones ni pendientes automáticos.
Mantén separados y abiertos los controles legítimos de vigencia y procedencia.
Evalúa fidelidad semántica: saltos de línea, espacios tipográficos o variaciones de
maquetación alrededor de un guion son equivalentes si no cambian un código, cifra,
unidad, operador, alternativa o literal cuya exactitud se haya pedido expresamente.
No bloquees por un formato exacto que la fuente no exige. Esta tolerancia sólo afecta
la redacción: las citas guardadas deben seguir siendo texto literal, sin normalizarlas.
"""


class PlanUnitProposal(StrictModel):
    requirement_id: str = Field(min_length=1, max_length=40)
    kind: UnitKind
    claim: str = Field(min_length=1, max_length=4000)
    required: StrictBool
    citations: list[PassageRange] = Field(min_length=1, max_length=MAX_UNIT_CITATIONS)
    reason: str = Field(min_length=1, max_length=2000)


class DetailMemberRange(StrictModel):
    word_start: StrictInt = Field(ge=1)
    word_end: StrictInt = Field(ge=1)


class DetailProposal(StrictModel):
    kind: Literal["authority", "alternatives"]
    citation: PassageRange
    members: list[DetailMemberRange] = Field(min_length=1, max_length=8)
    reason: str = Field(min_length=1, max_length=1200)


class DetailedPlanUnitProposal(PlanUnitProposal):
    details: list[DetailProposal] = Field(max_length=MAX_DETAILS_PER_UNIT)
    no_details_reason: str = Field(max_length=700)


class DetailEvidence(DetailMemberRange):
    member_index: StrictInt = Field(ge=1)
    paragraph_index: StrictInt = Field(ge=0)


class DetailCheck(StrictModel):
    detail_id: str = Field(pattern=r"^U[1-9][0-9]*-K[1-9][0-9]*$", max_length=60)
    status: Literal["answered", "pending", "omitted", "out_of_scope"]
    evidence: list[DetailEvidence] = Field(max_length=24)
    pending_indexes: list[StrictInt] = Field(max_length=60)
    explanation: str = Field(min_length=1, max_length=1600)


class UnitCheck(StrictModel):
    unit_id: str = Field(min_length=1, max_length=40)
    status: Literal["answered", "pending", "omitted", "out_of_scope"]
    paragraph_indexes: list[StrictInt] = Field(default_factory=list, max_length=20)
    pending_indexes: list[StrictInt] = Field(default_factory=list, max_length=60)
    explanation: str = Field(min_length=1, max_length=2000)


class _UnitCitation(StrictModel):
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=10000)


class _Detail(StrictModel):
    id: str = Field(pattern=r"^U[1-9][0-9]*-K[1-9][0-9]*$", max_length=60)
    kind: Literal["authority", "alternatives"]
    citation: _UnitCitation
    members: list[_UnitCitation] = Field(min_length=1, max_length=8)
    reason: str = Field(min_length=1, max_length=1200)


class _Unit(StrictModel):
    id: str = Field(pattern=r"^U[1-9][0-9]*$", max_length=40)
    requirement_id: str = Field(min_length=1, max_length=40)
    kind: UnitKind
    claim: str = Field(min_length=1, max_length=4000)
    required: StrictBool
    citations: list[_UnitCitation] = Field(min_length=1, max_length=MAX_UNIT_CITATIONS)
    reason: str = Field(min_length=1, max_length=2000)
    details_version: StrictInt | None = Field(default=None, ge=1, le=1)
    details: list[_Detail] = Field(default_factory=list, max_length=MAX_DETAILS_PER_UNIT)
    no_details_reason: str = Field(default="", max_length=700)


def _list(values, schema):
    if not isinstance(values, list) or len(values) > MAX_UNITS:
        raise DomainError("El inventario admite hasta 64 unidades de respuesta.")
    try:
        rows = [schema.model_validate(value).model_dump() for value in values]
    except (ValidationError, TypeError):
        raise DomainError("Las unidades de respuesta contienen campos inválidos.") from None
    if schema is _Unit:
        for original, row in zip(values, rows, strict=True):
            detail_keys = {"details_version", "details", "no_details_reason"}
            original_keys = (
                original.model_fields_set if hasattr(original, "model_fields_set") else original
            )
            if not any(key in original_keys for key in detail_keys):
                for key in detail_keys:
                    row.pop(key)
            elif row["details_version"] != DETAILS_VERSION:
                raise DomainError("El inventario de detalles necesita actualizarse.")
            else:
                _validate_details(row)
    return rows


def _requirements(request):
    rows = request.get("request_requirements") or build_requirements(request)
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip()
        for row in rows
    ):
        raise DomainError("Los incisos de la solicitud no son válidos.")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise DomainError("Los incisos de la solicitud están repetidos.")
    return set(ids)


def _source(chunk_id, request, index):
    source = index.get(chunk_id)
    if not isinstance(source, dict) or source.get("chunk_id") != chunk_id:
        raise DomainError("Una unidad cita un fragmento que no es un soporte autorizado.")
    if not source_in_scope(request, source):
        raise DomainError("Una unidad cita un soporte fuera del ámbito autorizado.")
    if source.get("is_latest") is False or source.get("validity") == "superseded":
        raise DomainError("Una unidad cita una versión reemplazada; actualiza sus fuentes.")
    if not isinstance(source.get("quote"), str) or not source["quote"].strip():
        raise DomainError("Una unidad no tiene un soporte literal válido.")
    return source


def _aliases(aliases):
    if (
        not isinstance(aliases, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key.strip()
            or not value.strip()
            for key, value in aliases.items()
        )
        or len(aliases.values()) != len(set(aliases.values()))
    ):
        raise DomainError("Los aliases de las unidades no son unívocos.")
    return {alias: chunk_id for chunk_id, alias in aliases.items()}


def validate_units(units, request, index):
    """Return canonical copies or raise DomainError; never mutate stored evidence."""
    rows = _list(units, _Unit)
    requirements = _requirements(request)
    if len({row["id"] for row in rows}) != len(rows):
        raise DomainError("Las unidades de respuesta tienen identificadores repetidos.")
    for row in rows:
        if row["requirement_id"] not in requirements:
            raise DomainError("Una unidad no corresponde a un inciso de esta solicitud.")
        if row["kind"] == "context" and row["required"]:
            raise DomainError("El contexto complementario no es una obligación de respuesta.")
        if not row["claim"].strip() or not row["reason"].strip() or not row["citations"]:
            raise DomainError("Cada unidad necesita contenido, motivo y una cita literal.")
        seen = set()
        for citation in row["citations"]:
            source = _source(citation["chunk_id"], request, index)
            key = (citation["chunk_id"], citation["quote"])
            if (
                not citation["quote"].strip()
                or citation["quote"] not in source["quote"]
                or key in seen
            ):
                raise DomainError("Una cita de unidad no es literal o está repetida.")
            seen.add(key)
    return rows


def materialize_units(proposals, request, index, aliases):
    """Resolve S aliases and closed 1-based chunk-local ranges into literal text."""
    rows = _list(proposals, PlanUnitProposal)
    reverse = _aliases(aliases)
    units = []
    for number, row in enumerate(rows, 1):
        citations = []
        for citation in row["citations"]:
            chunk_id = reverse.get(citation["chunk_id"])
            source = _source(chunk_id, request, index)
            lines = source["quote"].splitlines(True)
            start, end = citation["line_start"], citation["line_end"]
            if not 1 <= start <= end <= len(lines):
                raise DomainError("Una unidad selecciona líneas fuera de su fragmento.")
            citations.append({"chunk_id": chunk_id, "quote": "".join(lines[start - 1 : end])})
        units.append({**row, "id": f"U{number}", "citations": citations})
    return validate_units(units, request, index)


def aliased_units(units, aliases):
    """Copy canonical units to provider aliases, retaining U identifiers."""
    _aliases(aliases)
    rows = _list(units, _Unit)
    for row in rows:
        for citation in row["citations"]:
            if citation["chunk_id"] not in aliases:
                raise DomainError("Una unidad no tiene un alias citable en esta respuesta.")
            citation["chunk_id"] = aliases[citation["chunk_id"]]
        for detail in row.get("details", []):
            for citation in [detail["citation"], *detail["members"]]:
                if citation["chunk_id"] not in aliases:
                    raise DomainError("Un detalle no tiene un alias citable en esta respuesta.")
                citation["chunk_id"] = aliases[citation["chunk_id"]]
    return rows


def _issue(code, description, paragraph_index=None):
    return {"code": code, "description": description, "paragraph_index": paragraph_index}


def _open_specific_gap(item):
    if not isinstance(item, dict):
        return False
    resolution = item.get("resolution") or {}
    if not isinstance(resolution, dict):
        return False
    return (
        isinstance(item.get("description"), str)
        and bool(item["description"].strip())
        and item.get("basis") != "metadata_only"
        and item.get("stage", "evidence") == "evidence"
        and item.get("blocks_approval", True) is not False
        and item.get("state") not in {"closed", "resolved", "dismissed", "verified", "completed"}
        and resolution.get("status") in {None, "open"}
        and resolution.get("action") in {None, "open"}
    )


def unit_issues(units, checks, draft):
    """Validate review links; the model/human judges entailment and exclusion reasons."""
    try:
        rows = _list(units, _Unit)
        reviewed = _list(checks, UnitCheck)
    except DomainError:
        return [
            _issue("unit_review_invalid", "El inventario o su revisión contiene campos inválidos.")
        ]
    expected = {row["id"]: row for row in rows}
    reviewed_ids = [row["unit_id"] for row in reviewed]
    if (
        len(expected) != len(rows)
        or len(reviewed_ids) != len(set(reviewed_ids))
        or set(reviewed_ids) - set(expected)
        or any(row["kind"] == "context" and row["required"] for row in rows)
    ):
        return [
            _issue("unit_review_invalid", "La revisión repite o desconoce unidades autorizadas.")
        ]
    missing = {row["id"] for row in rows if row["required"]} - set(reviewed_ids)
    issues = []
    if missing:
        issues.append(
            _issue(
                "unit_review_incomplete",
                "Falta comprobar unidades obligatorias: " + ", ".join(sorted(missing)) + ".",
            )
        )
    if not isinstance(draft, dict):
        return issues + [_issue("unit_review_invalid", "No existe un borrador comprobable.")]
    paragraphs, pending = draft.get("paragraphs", []), draft.get("pending", [])
    if not isinstance(paragraphs, list) or not isinstance(pending, list):
        return issues + [_issue("unit_review_invalid", "Los párrafos o pendientes no son válidos.")]
    for row in reviewed:
        unit = expected[row["unit_id"]]
        pi, mi, status = row["paragraph_indexes"], row["pending_indexes"], row["status"]
        valid = (
            bool(row["explanation"].strip())
            and len(pi) == len(set(pi))
            and len(mi) == len(set(mi))
            and all(0 <= i < len(paragraphs) for i in pi)
            and all(0 <= i < len(pending) for i in mi)
        )
        if valid and status == "answered":
            cited = {citation["chunk_id"] for citation in unit["citations"]}
            valid = (
                bool(pi)
                and not mi
                and all(
                    isinstance(paragraphs[i], dict)
                    and isinstance(paragraphs[i].get("text"), str)
                    and bool(paragraphs[i]["text"].strip())
                    and isinstance(paragraphs[i].get("cited_chunk_ids"), list)
                    and all(isinstance(value, str) for value in paragraphs[i]["cited_chunk_ids"])
                    and any(chunk_id in cited for chunk_id in paragraphs[i]["cited_chunk_ids"])
                    for i in pi
                )
            )
            if valid:
                paragraph_citations = {
                    chunk_id for i in pi for chunk_id in paragraphs[i]["cited_chunk_ids"]
                }
                valid = cited <= paragraph_citations
        elif valid and status == "pending":
            valid = bool(mi) and all(_open_specific_gap(pending[i]) for i in mi)
        elif valid and status == "out_of_scope":
            valid = not mi
        if not valid:
            issues.append(
                _issue(
                    "unit_review_invalid",
                    f"La unidad {row['unit_id']} "
                    "no tiene una explicación o vínculos de revisión válidos.",
                )
            )
        elif status == "omitted" and unit["required"]:
            issues.append(
                _issue(
                    "answer_unit_omitted",
                    f"Falta conservar la unidad {row['unit_id']}: "
                    + unit["claim"]
                    + " "
                    + row["explanation"],
                    pi[0] if pi else None,
                )
            )
    return issues


DETAIL_PLAN_GUIDANCE = """
Inventaría también los detalles materiales que una síntesis no puede esconder.
Cada unidad aporta details y no_details_reason; Python añade su versión e IDs K.
authority identifica una denominación específica de autoridad, órgano, dependencia
o institución cuya identidad debe conservarse. Selecciona sólo su nombre o
denominación mínima inequívoca, no toda la oración ni un rol genérico como responsable.
Cada authority tiene un miembro. alternatives conserva una relación de alternativas
con dos o más miembros. Selecciona todas las opciones y una citation que contenga la
relación y sus calificadores. No conviertas la alternativa en obligaciones acumuladas.
Si las opciones identifican autoridades específicas, inventaría además cada nombre
como authority: la alternativa y las identidades son detalles diferentes.
No elijas detalles sólo del resumen claim: lee las citas completas. Un claim que
diga el comité correspondiente no reemplaza los órganos identificados por la fuente.
No inventarás nombres a partir de títulos, metadatos o de la petición.

En este plan numbered_lines contiene [número_de_línea, [[número_global_de_palabra,
palabra], ...]]. Conserva los rangos de líneas para citations y para la citation de
cada detalle. members usa word_start/word_end inclusivos, globales dentro del mismo
chunk de esa citation. Python copia literalmente las palabras y los separadores del
original; no escribas citas libres ni números fuera del soporte. La citation del
detalle debe estar contenida en una cita de la unidad, y cada miembro dentro de esa
citation. No añadas fuentes nuevas ni detalles ajenos al requisito. Una unidad sin
detalles de estas clases debe explicar concretamente por qué en no_details_reason;
si details no está vacío, no_details_reason queda vacío. Los controles legítimos de
vigencia, procedencia y aplicación siguen pendientes; no son detalles a redactar como
hechos comprobados. Preserva las identidades y alternativas respaldadas aunque la
vigencia de su fuente esté por cotejar: atribuir su contenido no resuelve ese cotejo.
"""

DETAIL_CHECK_GUIDANCE = """
Comprueba cada detalle de las unidades required=true exactamente una vez en
detail_checks, por su detail_id Ux-Ky, además de unit_checks. Un unit.status answered
no sustituye estas comprobaciones. Lee el pasaje completo y no sólo el claim genérico.
answered requiere contenido actual que conserve cada miembro y su relación; no basta
citar el fragmento ni decir el órgano correspondiente. Para authority, la identidad
específica debe aparecer en el borrador; un sinónimo de un rol genérico no acredita
el nombre institucional. No exijas copiar la oración completa ni su puntuación.
Para alternatives, cada opción puede expresarse con una paráfrasis fiel; comprueba
también la disyunción y sus condiciones. No exijas la palabra o si hay otra expresión
equivalente, pero marcar omitted si el texto convierte opciones en deberes conjuntos.
Explica expresamente cómo conserva o pierde esa relación.

evidence contiene rangos numéricos del borrador: paragraph_index, word_start,
word_end y member_index empezando en 1 dentro del detalle. Cada miembro necesita al
menos un rango si status=answered. Usa numbered_detail_paragraphs para seleccionar
palabras; Python materializa el texto exacto. Cada párrafo señalado debe citar el
fragmento del detalle. No selecciones un nombre del plan como si fuera del borrador.
Para omitted, señala también evidencia del párrafo que intenta responder parcialmente
si existe, de modo que pueda repararse sin tocar párrafos ajenos.
pending exige un pendiente específico y abierto vinculado al detalle; no sirve un
control de metadatos ni cerrar o inventar una comprobación. Cada vínculo debe ser
una brecha de evidence que bloquee la aprobación: una actuación de fulfillment no
sustituye un detalle de respuesta ausente. No conviertas la omisión
de un nombre disponible en falta documental. out_of_scope debe justificar por qué
el detalle no responde ni condiciona lo solicitado. Una autoridad o alternativa que
desaparece no se declara cubierta sólo porque está en una cita. No cierres controles
legítimos ni cambies textos o pendientes desde esta comprobación.
"""


def _identity_tokens(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    # Only typography: preserve accents, digits, operators and internal apostrophes.
    text = re.sub(
        r"(?<=[^\W\d_])[\-\u2010\u00ad]\s*\r?\n\s*(?=[^\W\d_])", "", text,
    )
    text = re.sub(r"(?<=[^\W\d_])[\-\u2010\u2011](?=[^\W\d_])", " ", text)
    return tuple(
        token.strip("\"'‘’“”.,;:!?()[]{}")
        for token in text.split()
        if token.strip("\"'‘’“”.,;:!?()[]{}")
    )


def _contains_identity(name, text):
    needle, haystack = _identity_tokens(name), _identity_tokens(text)
    return bool(needle) and any(
        haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
    )


def _validate_details(unit):
    details = unit["details"]
    if bool(details) == bool(unit["no_details_reason"].strip()):
        raise DomainError("El inventario debe declarar detalles o justificar su ausencia.")
    seen = set()
    for number, detail in enumerate(details, 1):
        if detail["id"] != f"{unit['id']}-K{number}" or not detail["reason"].strip():
            raise DomainError("Un detalle no conserva su identidad o justificación.")
        citation = detail["citation"]
        if not citation["quote"].strip() or not any(
            c["chunk_id"] == citation["chunk_id"] and citation["quote"] in c["quote"]
            for c in unit["citations"]
        ):
            raise DomainError("El detalle debe estar contenido en una cita de su unidad.")
        members = detail["members"]
        if (
            detail["kind"] == "authority"
            and len(members) != 1
            or detail["kind"] == "alternatives"
            and len(members) < 2
        ):
            raise DomainError("La identidad o alternativa no tiene sus miembros completos.")
        identities = set()
        for member in members:
            key = _identity_tokens(member["quote"])
            if (
                not key
                or key in identities
                or member["chunk_id"] != citation["chunk_id"]
                or member["quote"] not in citation["quote"]
            ):
                raise DomainError(
                    "Un miembro no es literal, es repetido o queda fuera del detalle."
                )
            identities.add(key)
        signature = (detail["kind"], citation["chunk_id"], tuple(sorted(identities)))
        if signature in seen:
            raise DomainError("El inventario repite el mismo detalle.")
        seen.add(signature)


def has_current_details(units):
    try:
        rows = _list(units, _Unit)
    except DomainError:
        return False
    return all(row.get("details_version") == DETAILS_VERSION for row in rows)


def numbered_detail_lines(quote):
    """Line numbers for citations and chunk-global word numbers for identities."""
    rows, word_number = [], 0
    for line_number, line in enumerate(quote.splitlines(True), 1):
        words = []
        for word in re.finditer(r"\S+", line):
            word_number += 1
            words.append([word_number, word.group()])
        rows.append([line_number, words])
    return rows


def numbered_detail_paragraphs(paragraphs, units=None):
    """Number only paragraphs that can provide cited detail evidence, retaining indexes.

    With no inventory argument the caller retains the complete numbering contract.
    An explicit inventory can omit unrelated prose from this auxiliary representation;
    the complete original paragraphs remain in the review payload.
    """
    detail_sources = None if units is None else {
        detail["citation"]["chunk_id"]
        for unit in units for detail in unit.get("details", [])
    }
    return [
        {
            "paragraph_index": i,
            "numbered_words": [
                [number, word.group()]
                for number, word in enumerate(re.finditer(r"\S+", p["text"]), 1)
            ],
        }
        for i, p in enumerate(paragraphs)
        if detail_sources is None or detail_sources.intersection(p.get("cited_chunk_ids", []))
    ]


def _word_quote(text, start, end):
    words = list(re.finditer(r"\S+", text))
    if not 1 <= start <= end <= len(words):
        raise DomainError("Un detalle selecciona palabras fuera de su texto actual.")
    left, right = words[start - 1].start(), words[end - 1].end()
    return text[left:right], left, right


def _detail_evidence_quote(text, span, detail, member_index):
    quote, _, _ = _word_quote(text, span["word_start"], span["word_end"])
    if detail["kind"] != "authority" or span["word_start"] <= 1:
        return quote
    identity = _identity_tokens(detail["members"][member_index - 1]["quote"])
    if (len(identity) <= 1 or identity[0] not in {"el", "la", "los", "las"}
            or _identity_tokens(quote) != identity[1:]):
        return quote
    # A reviewer may select the complete name except its leading article. Read
    # only the immediately preceding token; do not remove articles from names,
    # search another clause or substitute evidence from a different citation.
    article, _, _ = _word_quote(text, span["word_start"] - 1, span["word_start"] - 1)
    if article.casefold() != identity[0]:
        return quote  # Punctuation after the article is not contiguous identity.
    expanded, _, _ = _word_quote(text, span["word_start"] - 1, span["word_end"])
    return expanded if _identity_tokens(expanded) == identity else quote


def materialize_detailed_units(proposals, request, index, aliases):
    proposed = _list(proposals, DetailedPlanUnitProposal)
    units = materialize_units(
        [
            {
                key: value
                for key, value in row.items()
                if key not in {"details", "no_details_reason"}
            }
            for row in proposed
        ],
        request,
        index,
        aliases,
    )
    reverse = _aliases(aliases)
    for unit, proposal in zip(units, proposed, strict=True):
        details = []
        for number, detail in enumerate(proposal["details"], 1):
            selected = detail["citation"]
            chunk_id = reverse.get(selected["chunk_id"])
            source = _source(chunk_id, request, index)
            text = source["quote"]
            lines = text.splitlines(True)
            start, end = selected["line_start"], selected["line_end"]
            if not 1 <= start <= end <= len(lines):
                raise DomainError("Un detalle selecciona líneas fuera de su soporte.")
            left = sum(len(line) for line in lines[: start - 1])
            right = left + sum(len(line) for line in lines[start - 1 : end])
            members = []
            for member in detail["members"]:
                quote, word_left, word_right = _word_quote(
                    text, member["word_start"], member["word_end"]
                )
                if word_left < left or word_right > right:
                    raise DomainError(
                        "Un miembro queda fuera del pasaje seleccionado para el detalle."
                    )
                members.append({"chunk_id": chunk_id, "quote": quote})
            details.append(
                {
                    "id": f"{unit['id']}-K{number}",
                    "kind": detail["kind"],
                    "citation": {"chunk_id": chunk_id, "quote": text[left:right]},
                    "members": members,
                    "reason": detail["reason"],
                }
            )
        unit.update(
            details_version=DETAILS_VERSION,
            details=details,
            no_details_reason=proposal["no_details_reason"],
        )
    return validate_units(units, request, index)


def detail_issues(units, checks, draft, *, require_current=True):
    """Require evidence per detail; names are lexical, alternatives remain semantic."""
    if require_current and not has_current_details(units):
        return [
            _issue(
                "detail_inventory_stale", "Actualizar el inventario de detalles antes de comprobar."
            )
        ]
    try:
        rows = _list(units, _Unit)
        if not isinstance(checks, list) or len(checks) > MAX_UNITS * MAX_DETAILS_PER_UNIT:
            raise DomainError("La revisión de detalles no tiene una lista válida.")
        reviewed = [DetailCheck.model_validate(row).model_dump() for row in checks]
    except (DomainError, ValidationError, TypeError):
        return [
            _issue("detail_review_invalid", "El inventario o su revisión de detalles es inválido.")
        ]
    expected = {detail["id"]: (unit, detail) for unit in rows for detail in unit.get("details", [])}
    ids = [row["detail_id"] for row in reviewed]
    if len(ids) != len(set(ids)) or set(ids) - set(expected):
        return [
            _issue("detail_review_invalid", "La revisión repite o desconoce detalles autorizados.")
        ]
    missing = {key for key, (unit, _) in expected.items() if unit["required"]} - set(ids)
    issues = []
    if missing:
        issues.append(
            _issue(
                "detail_review_incomplete",
                "Falta comprobar detalles obligatorios: " + ", ".join(sorted(missing)) + ".",
            )
        )
    if not isinstance(draft, dict) or not isinstance(draft.get("paragraphs"), list):
        return issues + [_issue("detail_review_invalid", "No existe un borrador comprobable.")]
    paragraphs, pending = draft["paragraphs"], draft.get("pending", [])
    for row in reviewed:
        unit, detail = expected[row["detail_id"]]
        evidence, seen, target = {}, set(), None
        valid = bool(row["explanation"].strip())
        try:
            for span in row["evidence"]:
                key = tuple(
                    span[k] for k in ("member_index", "paragraph_index", "word_start", "word_end")
                )
                pi, mi = span["paragraph_index"], span["member_index"]
                if (
                    key in seen
                    or pi >= len(paragraphs)
                    or not 1 <= mi <= len(detail["members"])
                    or detail["citation"]["chunk_id"]
                    not in paragraphs[pi].get("cited_chunk_ids", [])
                ):
                    raise DomainError("El detalle no tiene evidencia actual y citada.")
                quote = _detail_evidence_quote(paragraphs[pi]["text"], span, detail, mi)
                evidence.setdefault(mi, []).append(quote)
                seen.add(key)
                target = pi if target is None else target
        except (DomainError, KeyError, TypeError, AttributeError):
            valid = False
        pending_indexes = row["pending_indexes"]
        valid = (
            valid
            and isinstance(pending, list)
            and len(pending_indexes) == len(set(pending_indexes))
            and all(0 <= i < len(pending) for i in pending_indexes)
        )
        if row["status"] == "answered":
            valid = (
                valid
                and not pending_indexes
                and set(evidence) == set(range(1, len(detail["members"]) + 1))
            )
        elif row["status"] == "pending":
            valid = (
                valid
                and bool(pending_indexes)
                and all(_open_specific_gap(pending[i]) for i in pending_indexes)
            )
        elif row["status"] == "out_of_scope":
            valid = valid and not pending_indexes
        if not valid:
            issues.append(
                _issue(
                    "detail_review_invalid",
                    f"El detalle {detail['id']} no tiene "
                    "evidencia, explicación o vínculos de revisión válidos.",
                    target,
                )
            )
            continue
        lost_identity = (
            row["status"] == "answered"
            and detail["kind"] == "authority"
            and not any(
                _contains_identity(detail["members"][0]["quote"], text) for text in evidence[1]
            )
        )
        if unit["required"] and (row["status"] == "omitted" or lost_identity):
            label = "; ".join(m["quote"] for m in detail["members"])
            label = label if len(label) <= 1000 else label[:999] + "…"
            reason = (
                "La evidencia del borrador no conserva la identidad nombrada."
                if lost_identity
                else row["explanation"]
            )
            issues.append(
                _issue(
                    "answer_detail_omitted",
                    f"Falta conservar {detail['id']}: {label}. " + reason,
                    target,
                )
            )
    return issues


DETAIL_POLICY_HASH = hashlib.sha256(
    json.dumps(
        {
            "version": DETAILS_VERSION,
            "plan_schema": DetailedPlanUnitProposal.model_json_schema(),
            "check_schema": DetailCheck.model_json_schema(),
            "canonical_unit_schema": _Unit.model_json_schema(),
            "plan_guidance": DETAIL_PLAN_GUIDANCE,
            "check_guidance": DETAIL_CHECK_GUIDANCE,
            "unit_check_guidance": UNIT_CHECK_GUIDANCE,
            "normalization": "nfkc_casefold_edge_typography_letter_line_hyphens_preserve_ids_v2",
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf8")
).hexdigest()
