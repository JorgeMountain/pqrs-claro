"""Contexto del escrito para buscar una solicitud sin cambiar su identificación.

Los padres resuelven referencias como «el profesor»; los descendientes completan
una lista; los numerales explícitos remiten a otros apartados del mismo escrito.
Este contexto describe lo pedido, nunca constituye evidencia de su cumplimiento.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from copy import deepcopy
from typing import Any

from .models import DomainError

CONTEXT_VERSION = 1
MAX_CONTEXT_CHARACTERS = 40000
MAX_CONTEXT_REQUESTS = 60
MAX_DESCRIPTION_CHARACTERS = 3000
MAX_REFERENCE_QUOTES = 2
MAX_QUOTE_CHARACTERS = 1000
_CONTEXT_GROUPS = ("ancestors", "children", "referenced_requests", "preceding_section")

_ORDINALS = (
    "primer segundo tercer cuarto quinto sexto septimo octavo noveno decimo "
    "undecimo duodecimo decimotercer decimocuarto decimoquinto decimosexto "
    "decimoseptimo decimoctavo decimonoveno vigesimo"
).split()


def _plain(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


def _ordinal(value: str) -> str | None:
    word = _plain(value).strip(" .:ºª°()-")
    if word.isdigit():
        return str(int(word))
    if word.endswith(("a", "o")):
        word = word[:-1]
    for index, name in enumerate(_ORDINALS, 1):
        stem = name[:-1] if name.endswith("o") else name
        if word == stem:
            return str(index)
    return None


_ORDINAL_TOKEN = (
    r"(?:decimotercer[oa]?|decimocuart[oa]|decimoquint[oa]|decimosext[oa]|"
    r"decimoseptim[oa]|decimoctav[oa]|decimonoven[oa]|"
    r"primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|"
    r"septim[oa]|octav[oa]|noven[oa]|decim[oa]|undecim[oa]|duodecim[oa]|"
    r"vigesim[oa]|\d{1,3}[ºª°]?)"
)
_ITEM = r"(?:petici(?:on|ones)|solicitud(?:es)?|numeral(?:es)?|apartado(?:s)?|punto(?:s)?)"
_ORDINAL_LIST = rf"{_ORDINAL_TOKEN}(?:\s*(?:,|y|e)\s*{_ORDINAL_TOKEN})*"
_REFERENCES = re.compile(
    rf"\b{_ITEM}\s+(?:numero\s+)?(?P<after>{_ORDINAL_LIST})\b|"
    rf"\b(?P<before>{_ORDINAL_LIST})\s+{_ITEM}\b"
)


def _request_text(request: dict[str, Any]) -> str:
    return _plain(" ".join(
        [str(request.get("description") or "")]
        + [str(ref.get("quote") or "") for ref in request.get("source_refs", [])]
    ))


def _references(request: dict[str, Any]) -> list[str]:
    # References are resolved only from the atomic question, not recursively
    # from general parents that might mention every other request in the case.
    text = _request_text(request)
    numbers: list[str] = []
    for match in _REFERENCES.finditer(text):
        values = match.group("after") or match.group("before")
        for token in re.findall(_ORDINAL_TOKEN, values):
            number = _ordinal(token)
            if number and number not in numbers:
                numbers.append(number)
    return numbers


def _entry(request: dict[str, Any]) -> dict[str, Any]:
    description = str(request.get("description") or "")
    references = request.get("source_refs", [])
    return {
        **{key: deepcopy(request.get(key)) for key in ("id", "label", "title", "parent_id")},
        "description": description[:MAX_DESCRIPTION_CHARACTERS],
        "description_truncated": len(description) > MAX_DESCRIPTION_CHARACTERS,
        "source_refs": [
            {**{key: ref.get(key) for key in ("page", "line_start", "line_end")},
             "quote": str(ref.get("quote") or "")[:MAX_QUOTE_CHARACTERS],
             "quote_truncated": len(str(ref.get("quote") or "")) > MAX_QUOTE_CHARACTERS}
            for ref in references[:MAX_REFERENCE_QUOTES]
        ],
        "additional_source_ref_count": max(0, len(references) - MAX_REFERENCE_QUOTES),
    }


def build_source_requests(
    case: dict[str, Any], *, allowed_collection_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """Devuelve copias atómicas enriquecidas, sin tocar caso ni ámbito de fuentes.

    Solo se resuelven referencias inequívocas a etiquetas de primer nivel. CUARTO
    se resuelve por label, sin suponer que necesariamente tiene el identificador P4.
    Los límites se señalan como contexto truncado; nunca generan missing ni estados.
    """
    requests = case["identification"]["requests"]
    by_id = {item["id"]: item for item in requests}
    if len(by_id) != len(requests):
        raise DomainError("Hay solicitudes con identificadores repetidos en el contexto.")
    children: dict[str, list[dict]] = defaultdict(list)
    labels: dict[str, list[dict]] = defaultdict(list)
    for item in requests:
        parent = item.get("parent_id")
        if parent:
            if parent not in by_id:
                raise DomainError("Una solicitud remite a un apartado padre que no existe.")
            children[parent].append(item)
        else:
            number = _ordinal(str(item.get("label") or ""))
            if number:
                labels[number].append(item)

    def ancestors(item: dict) -> list[dict]:
        result, visited = [], {item["id"]}
        while item.get("parent_id"):
            item = by_id[item["parent_id"]]
            if item["id"] in visited:
                raise DomainError("El contexto de solicitudes contiene un ciclo de apartados.")
            visited.add(item["id"])
            result.append(item)
        return result

    def descendants(identifier: str) -> list[dict]:
        result, pending, visited = [], list(children[identifier]), {identifier}
        while pending:
            item = pending.pop(0)
            if item["id"] in visited:
                raise DomainError("El contexto de solicitudes contiene un ciclo de apartados.")
            visited.add(item["id"])
            result.append(item)
            pending.extend(children[item["id"]])
        return result

    scopes = list(allowed_collection_ids if allowed_collection_ids is not None
                  else case.get("allowed_collection_ids", []))
    results = []
    for position, item in enumerate(requests):
        parents = ancestors(item)
        targets, unresolved = [], []
        for number in _references(item):
            matches = labels.get(number, [])
            if len(matches) == 1:
                target = matches[0]
                if target["id"] != item["id"]:
                    targets.append(target)
            else:
                unresolved.append({"label_number": number,
                                   "reason": "ambiguous" if matches else "not_identified",
                                   "candidate_request_ids": [m["id"] for m in matches]})
        previous_section = []
        text = _request_text(item)
        if not parents and not targets and re.search(
            r"\bpreguntas\s+(?:anteriormente\s+)?(?:formuladas|anteriores)\b", text
        ):
            previous = next((candidate for candidate in reversed(requests[:position])
                             if not candidate.get("parent_id")), None)
            if previous and children[previous["id"]]:
                # Grounded in document order, not asserted as a resolved reference.
                previous_section = [previous, *descendants(previous["id"])]
        context: dict[str, Any] = {
            "version": CONTEXT_VERSION, "target_request_id": item["id"],
            "origin": "same_petition", "subject": case["identification"].get("subject"),
            "document_date": case["identification"].get("document_date"),
            "ancestors": [], "children": [], "referenced_requests": [], "preceding_section": [],
            "preceding_section_basis": (
                "document_order_for_back_reference" if previous_section else None
            ),
            "unresolved_references": unresolved, "omitted_request_ids": [],
        }
        # Direct headings are included before long lists of referenced children.
        groups = [("ancestors", parents), ("referenced_requests", targets),
                  ("children", descendants(item["id"])),
                  ("referenced_requests", [child for target in targets
                                           for child in descendants(target["id"])]),
                  ("preceding_section", previous_section)]
        seen, characters = {item["id"]}, 0
        for key, group in groups:
            for related in group:
                if related["id"] in seen:
                    continue
                seen.add(related["id"])
                entry = _entry(related)
                size = len(entry["description"]) + sum(
                    len(ref["quote"]) for ref in entry["source_refs"]
                )
                count = sum(len(context[name]) for name in _CONTEXT_GROUPS)
                if count >= MAX_CONTEXT_REQUESTS or characters + size > MAX_CONTEXT_CHARACTERS:
                    context["omitted_request_ids"].append(related["id"])
                    continue
                characters += size
                context[key].append(entry)
        context["truncated"] = bool(context["omitted_request_ids"]) or any(
            entry["description_truncated"] or entry["additional_source_ref_count"]
            or any(ref["quote_truncated"] for ref in entry["source_refs"])
            for name in _CONTEXT_GROUPS for entry in context[name]
        )
        # A separate channel lets retrieval weight context below the atomic query.
        # It consists of original request texts, not generated facts or new demands.
        queries = list(dict.fromkeys(
            f"{entry.get('title') or ''} {entry['description']}"[:1200].strip()
            for name in _CONTEXT_GROUPS for entry in context[name]
        ))[:12]
        results.append({
            **deepcopy(item), "case_id": case["id"], "allowed_collection_ids": list(scopes),
            "context": context, "retrieval_queries": queries,
            "retrieval_context": "\n".join(queries)[:10000],
        })
    return results
