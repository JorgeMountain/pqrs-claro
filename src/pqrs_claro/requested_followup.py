"""Requested future checks, tied to current literal coverage and never a missing file.

This conservative Spanish syntax guard recognizes explicit follow-up mandates or
requests to identify a check still pending. It is not a semantic classifier: an
unrecognized wording remains with the normal reader/reviewer instead of creating
a task from a future date or an informational rule alone.
"""

import re
import unicodedata
from copy import deepcopy

from .request_requirements import build_requirements
from .source_retrieval import source_in_scope


def _plain(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(value).casefold())
                            if not unicodedata.combining(c)).split())


_COMMAND = re.compile(
    r"\b(?:verifique[n]?|compruebe[n]?|confirme[n]?|vigile[n]?|controle[n]?|"
    r"registre[n]?|haga[n]?\s+seguimiento|de[n]?\s+seguimiento)\b"
)
_INFINITIVE = re.compile(
    r"\b(?:verificar|comprobar|confirmar|vigilar|controlar|registrar|"
    r"hacer\s+seguimiento|dar\s+seguimiento)\b"
)
_GOVERNOR = re.compile(r"\b(?:solicito|pido|requiero|necesito|quiero)\b")
_TEMPORAL_REQUEST = re.compile(
    r"\b(?:cuando|una vez|en cuanto|al publicarse|al emitirse|al conocerse)\b"
)
_PENDING_QUESTION = re.compile(
    r"\b(?:que|cual(?:es)?)\b[^.;?]{0,120}\b(?:queda[n]?|sigue[n]?|permanece[n]?|"
    r"esta[n]?)\s+(?:aun\s+)?(?:por\s+(?:comprobar|confirmar|verificar|conocer|"
    r"decidir|resolver)|pendiente[s]?\s+(?:de\s+)?(?:comprob\w*|confirm\w*|"
    r"verific\w*|resol\w*|decision\w*))\b"
)
_EXCLUDED = re.compile(
    r"\bno\s+(?:(?:le|les)\s+)?(?:solicito|pido|quiero|requiero|necesito)\b"
    r"[^.;!?]{0,90}\b(?:seguimiento|verifiquen?|comprueben?|confirmacion|verificacion)\b|"
    r"\b(?:no\s+(?:hagan?|den?)\s+seguimiento|"
    r"no\s+registren?\s+(?:un\s+)?(?:seguimiento|pendiente)|"
    r"sin\s+(?:registrar|crear|hacer|dar)\s+(?:un\s+)?seguimiento)\b"
)
_INFORMATION_PREFIX = re.compile(
    r"\b(?:expli\w*|describ\w*|informacion|procedimiento|en general|"
    r"como\s+(?:se\s+)?debe|quien\s+debe|que\s+debe|cuando\s+debe)\b"
)
_REPORTED_PREFIX = re.compile(
    r"\b(?:aviso|reglamento|documento|norma|oficio|comunicado|tercero|persona)\b"
    r"[^.;!?]{0,60}\b(?:dice|indica|establece|ordena|pide|solicita|senala)\b"
)
_FUTURE = re.compile(
    r"\b(?:se\s+)?(?:publicara[n]?|emitira[n]?|comunicara[n]?|notificara[n]?|"
    r"resolvera[n]?|decidira[n]?|anunciara[n]?|registrara[n]?|registraria[n]?|"
    r"estara[n]?\s+disponible[s]?|estaria[n]?\s+disponible[s]?|dara[n]?\s+a conocer)\b|"
    r"\b(?:pendiente[s]?\s+de\s+(?:publicacion|decision|resolucion)|"
    r"queda[n]?\s+por\s+(?:publicar|decidir|resolver|conocer))\b"
)
_CLOSED = re.compile(
    r"\b(?:se|ya|finalmente)\s+(?:se\s+)?"
    r"(?:publico|emitio|comunico|notifico|resolvio|decidio|anuncio|registro)\b|"
    r"\b(?:ya\s+)?(?:esta|estan|quedo|quedaron)\s+(?:publicad\w*|resuelt\w*)\b|"
    r"\bya\s+esta[n]?\s+disponible[s]?\b"
)


def _has_future(text):
    text = _plain(text)
    future = [m for m in _FUTURE.finditer(text)
              if not re.search(r"\bno\s+(?:se\s+)?$", text[max(0, m.start() - 15):m.start()])]
    closed = [m for m in _CLOSED.finditer(text)
              if not re.search(r"\bno\s+(?:se\s+)?$", text[max(0, m.start() - 15):m.start()])]
    return bool(future) and not closed


def _mode(text):
    text = _plain(text)
    if _EXCLUDED.search(text):
        return None
    if _REPORTED_PREFIX.search(text):
        return None
    if _PENDING_QUESTION.search(text) and not re.search(r"\ben general\b", text):
        return "identified_pending_check"
    command = _COMMAND.search(text)
    governor = _GOVERNOR.search(text)
    if command is None and governor:
        command = _INFINITIVE.search(text, governor.end())
    if (command and _TEMPORAL_REQUEST.search(text)
            and not re.search(r"\bno\s+$", text[:command.start()])
            and not (governor and re.search(r"\bno\s+$", text[:governor.start()]))
            and not _INFORMATION_PREFIX.search(text[:command.start()])):
        return "explicit_followup"
    return None


def _same_source(item, task):
    if set(item.get("linked_chunk_ids", [])) != set(task["linked_chunk_ids"]):
        return False
    versions = sorted(item.get("source_versions", []), key=lambda row: row.get("source_id", ""))
    if versions and versions != task["source_versions"]:
        return False
    if item.get("resolution", {}).get("status") == "resolved" and not item.get("source_versions"):
        return False
    if item.get("followup_passages") and item["followup_passages"] != task["followup_passages"]:
        return False
    if item.get("followup_claims") and item["followup_claims"] != task["followup_claims"]:
        return False
    return True


def _existing_match(item, task):
    """Exact references may reuse an action; shared wording/documents alone may not."""
    if item.get("reason_code") != "requested_followup":
        return False
    if not _same_source(item, task):
        return False
    return _plain(item.get("affected_claim", "")) == _plain(task["affected_claim"])


def _mapped_existing(item, task, review, gaps):
    """Reuse only a temporal action linked by the reader to this exact requirement."""
    if item.get("stage") != "fulfillment" or not _same_source(item, task):
        return False
    for index in review.get("missing_indexes", []):
        if type(index) is not int or not 0 <= index < len(gaps):
            continue
        gap = gaps[index]
        text = _plain(gap.get("description", ""))
        if (gap.get("stage") != "fulfillment" or not _TEMPORAL_REQUEST.search(text)
                or not (_INFINITIVE.search(text) or _COMMAND.search(text))
                or _EXCLUDED.search(text)):
            continue
        if (gap.get("description") in (item.get("description"), item.get("original_description"))
                and gap.get("affected_claim") == item.get("affected_claim")
                and set(gap.get("source_chunk_ids", [])) == set(task["linked_chunk_ids"])):
            return True
    return False


def _only_followup(description, mode):
    """Do not replace supervision of any separately requested action."""
    if mode != "explicit_followup":
        return False
    clauses = [c for c in re.split(r"[.;!?]", _plain(description))
               if _COMMAND.search(c) or _INFINITIVE.search(c)]
    if len(clauses) != 1:
        return False
    clause = clauses[0]
    commands = sorted([*_COMMAND.finditer(clause), *_INFINITIVE.finditer(clause)],
                      key=lambda match: match.start())
    if len(commands) == 1:
        return True
    # "Hacer seguimiento ... y comprobar ... cuando ..." is one future mandate.
    return (len(commands) == 2 and "seguimiento" in commands[0].group()
            and commands[1].group().startswith(("comprob", "verifi", "confir"))
            and bool(_TEMPORAL_REQUEST.search(clause, commands[1].end())))


def requested_followups(request, finding, *, include_existing=False):
    """Return only missing future tasks; never mutate controls or claim execution.

    Call after literal coverage validation and before normalizing controls. A
    selected requirement, its coverage and its current authorized passage must
    all agree. Model summaries or other requests' clauses cannot create a task.
    ``include_existing`` preserves a matched record and its resolution for callers
    that also need to suppress a newly derived generic supervision action.
    """
    description = str(request.get("description") or request.get("title") or "")
    if _EXCLUDED.search(_plain(description)):
        return []
    requirements = request.get("request_requirements") or build_requirements(request)
    sufficiency = finding.get("sufficiency") or {}
    coverage = sufficiency.get("coverage", [])
    reviews = sufficiency.get("requirement_checks", [])
    gaps = sufficiency.get("evaluated_gaps", [])
    sources = {s["chunk_id"]: s for s in finding.get("supports", [])
               if s.get("chunk_id") and source_in_scope(request, s)
               and s.get("is_latest") is not False and s.get("validity") != "superseded"
               and s.get("category") != "historical_petition"
               and s.get("extraction_status", "ready") == "ready"}
    known = [*finding.get("checks", []), *finding.get("missing", []),
             *finding.get("actions", [])]
    candidates = []
    for requirement in requirements:
        text = requirement.get("text", "")
        mode = _mode(text)
        if not mode or _plain(text) not in _plain(description):
            continue
        matching = [r for r in reviews if r.get("requirement_id") == requirement.get("id")]
        if len(matching) != 1:
            continue
        indexes = matching[0].get("coverage_indexes", [])
        if (not indexes or len(indexes) != len(set(indexes))
                or any(type(i) is not int or not 0 <= i < len(coverage) for i in indexes)):
            continue
        for index in indexes:
            row = coverage[index]
            if row.get("use") != "attributed_content" or not _has_future(row.get("claim", "")):
                continue
            citations = row.get("citations", [])
            if not citations:
                continue
            valid, chunks = True, []
            for citation in citations:
                source = sources.get(citation.get("chunk_id"))
                quote = citation.get("quote")
                if (not source or source.get("role") == "rule" or not isinstance(quote, str)
                        or not quote.strip() or quote not in source.get("quote", "")
                        or not _has_future(quote)):
                    valid = False
                    break
                chunks.append(citation["chunk_id"])
            if not valid:
                continue
            task = {
                "kind": "clarification", "reason_code": "requested_followup",
                "stage": "fulfillment", "blocks_approval": False,
                "description": "Dar seguimiento a la comprobación solicitada cuando "
                               "esté disponible el resultado anunciado: " + row["claim"],
                "affected_claim": row["claim"],
                "followup_claims": [row["claim"]],
                "why_unresolved": "La petición identifica una comprobación futura y el pasaje "
                                  "conserva su anuncio. No se exige que el resultado exista hoy "
                                  "ni se afirma que la actuación esté realizada.",
                "basis": "content_gap", "request_quote": text,
                "requirement_ids": [requirement["id"]], "coverage_indexes": [index],
                "linked_chunk_ids": list(dict.fromkeys(chunks)),
                "followup_passages": sorted(
                    ({"chunk_id": c["chunk_id"], "quote": c["quote"]} for c in citations),
                    key=lambda c: (c["chunk_id"], c["quote"])),
                "linked_source_ids": list(dict.fromkeys(sources[c]["source_id"] for c in chunks)),
                "source_versions": sorted({sources[c]["source_id"]: {
                    "source_id": sources[c]["source_id"],
                    **{key: sources[c].get(key) for key in
                       ("document_id", "version", "sha256", "extraction_revision")},
                } for c in chunks}.values(), key=lambda source: source["source_id"]),
                "replaces_generic_supervision": _only_followup(description, mode),
            }
            # One requested mandate may describe its future result in multiple
            # coverage rows. Only identical literal passages can share this task;
            # merely sharing a document, date or similar wording is insufficient.
            previous = next((t for t in candidates
                             if t["requirement_ids"] == task["requirement_ids"]
                             and t["followup_passages"] == task["followup_passages"]
                             and t["source_versions"] == task["source_versions"]), None)
            if previous is None:
                candidates.append(task)
            else:
                previous["coverage_indexes"].append(index)
                if row["claim"] not in previous["followup_claims"]:
                    previous["followup_claims"].append(row["claim"])
                    previous["description"] += " " + row["claim"]
    result = []
    for task in candidates:
        review = next(r for r in reviews if r.get("requirement_id") == task["requirement_ids"][0])
        existing = next((item for item in known if _existing_match(item, task)
                         or _mapped_existing(item, task, review, gaps)), None)
        if existing is not None:
            if include_existing:
                kept = deepcopy(existing)
                kept["replaces_generic_supervision"] = task["replaces_generic_supervision"]
                if kept not in result:
                    result.append(kept)
        elif not any(_existing_match(item, task) for item in result):
            result.append(task)
    return result
