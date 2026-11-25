"""Una transcripción opcional no debe impedir citar otra fuente suficiente."""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy

from .models import DomainError
from .performance_metrics import operation
from .request_intent import classify_request_intent
from .source_documents import numbered_document_references
from .source_retrieval import source_in_scope


def secondary_source_ids(finding):
    return {sid for c in finding.get("secondary_source_checks", [])
            for sid in c["linked_source_ids"]}


def _complete_coverage(request, finding):
    coverage = finding.get("sufficiency") or {}
    requirements = request.get("request_requirements") or []
    checks = coverage.get("requirement_checks") or []
    return bool(
        finding.get("request_id") == request["id"]
        and finding.get("status") in {"references_found", "needs_evidence"}
        and not finding.get("error")
        and requirements
        and coverage.get("request_requirements") == requirements
        and coverage.get("coverage_complete") is True
        and coverage.get("attribution_only_allowed") is True
        and not coverage.get("uncertainties")
        and not coverage.get("evaluated_gaps")
        and len(checks) == len(requirements)
        and {c["requirement_id"] for c in checks} == {r["id"] for r in requirements}
        and all(
            c["status"] == "supported"
            and c["coverage_indexes"]
            and not c.get("missing_indexes")
            and not c.get("uncertainty_indexes")
            for c in checks
        )
        and coverage.get("coverage")
        and all(
            row["use"] in {"attributed_content", "rule"}
            and row["application"]["status"] == "not_requested"
            and row.get("citations")
            for row in coverage["coverage"]
        )
    )


def _fallback_source(check, selected):
    chunks = check.get("linked_chunk_ids") or []
    source = selected.get(chunks[0]) if len(chunks) == 1 else None
    if (
        not source or not source.get("sha256") or not source.get("document_id")
        or not source.get("needs_review")
        or source.get("method") != "ocr"
        or check.get("linked_source_ids") != [source["source_id"]]
        or check.get("stage") != "evidence"
        or check.get("scope_key") != "passage"
        or check.get("reason_code") != "transcription"
        or check.get("kind") != "clarification"
        or check.get("basis") not in {None, "unspecified"}
        or check.get("affected_claim")
        or check.get("why_unresolved")
        or (check.get("resolution") or {}).get("status") != "open"
    ):
        return None
    location = "sección" if source.get("location_kind") == "section" else "página"
    title = source.get("title") or source.get("filename") or source["source_id"]
    expected = (
        f"Contrastar la transcripción de «{title}», {location} {source['page']}, con su original."
    )
    return source if check.get("description") == expected else None


def _document_name_tokens(value):
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", text))


def _native_candidates(request, finding, candidates):
    checks = finding.get("missing") or []
    if (
        not checks
        or not _complete_coverage(request, finding)
    ):
        return []
    own_texts = [
        str(request.get("title") or ""), str(request.get("description") or ""),
        *(r["text"] for r in request.get("request_requirements", [])),
        *(r.get("quote") or "" for r in request.get("source_refs", [])),
    ]
    # A shortened identification may omit a separate mandate in the original.
    # Do not inherit mandates from other requests in the case context.
    if any(classify_request_intent({"description": text})["intents"] != ["information"]
           for text in own_texts if text):
        return []
    question = " ".join(own_texts)
    # A guide cannot substitute for the text of an explicitly requested authority.
    # «De acuerdo con» introduces a reference; its object may itself name an Acuerdo.
    authority_text = re.sub(r"\bde\s+acuerdo\s+con\b", " ", question, flags=re.I)
    if numbered_document_references(question) or re.search(
        r"\b(resoluci[oó]n|acuerdo|decreto|ley|circular|acto administrativo)\b",
        authority_text, re.I,
    ):
        return []
    if re.search(
        r"\b(?:original|adjunt[oa]|anex[oa]|firmad[oa]|autenticidad|transcripci[oó]n|"
        r"cotej(?:ar|o|e)|firma)\b",
        question, re.I,
    ):
        return []
    selected = {s["chunk_id"]: s for s in finding["supports"]}
    transcription_sources = [_fallback_source(c, selected) for c in checks]
    if not all(transcription_sources):
        return []
    explicit_names = {
        _document_name_tokens(s[k])
        for s in transcription_sources for k in ("title", "filename") if s.get(k)
    }
    if any(f" {name} " in f" {_document_name_tokens(text)} "
           for text in own_texts for name in explicit_names if text and name):
        return []
    excluded = {s["source_id"] for s in transcription_sources}
    documents = {s.get("document_id") for s in transcription_sources}
    hashes = {s.get("sha256") for s in transcription_sources}
    available = {
        c["chunk_id"]: c
        for c in candidates
        if c.get("document_id") and c.get("sha256")
        and c["sha256"] not in hashes
        and c["source_id"] not in excluded
        and c.get("document_id") not in documents
        and source_in_scope(request, c)
        and c.get("method") == "native"
        and c.get("needs_review") is False
        and c.get("is_latest") is True
        and c.get("review_status") == "reviewed"
        and (
            (c.get("category") in {"institutional_norm", "national_norm"}
             and c.get("validity") == "current")
            or (c.get("category") == "case_evidence" and request.get("case_id")
                and c.get("case_id") == request["case_id"]
                and c.get("validity") in {"current", "not_applicable"})
        )
    }
    coverage = finding["sufficiency"]["coverage"]
    citations = [{c["chunk_id"] for c in row["citations"]} & available.keys() for row in coverage]
    if all(citations):
        used = set.union(*citations)
        return [c for key, c in available.items() if key in used]
    # A first reading can cite only the scan even when another candidate
    # answers the same question. Let the reader assess the authorized native
    # passages in retrieval order; every requirement must still be supported.
    return list(available.values())


_ATTRIBUTION_VERBS = (
    r"consignaba|consigna|indicaba|indica|señalaba|señala|"
    r"establecía|establece|fijaba|fija|disponía|dispone|preveía|prevé"
)
_PERIOD_TOKEN = re.compile(r"\b\d{4}-[1-4]\b")
_PERIOD_MODIFIER = (
    r"(?:\s+(?:de|del|para|en)\s+"
    r"(?:(?:el|la)\s+)?(?:(?:periodo|semestre|convocatoria|proceso(?:\s+de\s+admisión)?)"
    r"(?:\s+académic[oa])?\s+)?"
    r"\d{4}-[1-4])?"
)
_GENERIC_FRAME = re.compile(
    r"^(?:según\s+(?:la\s+guía(?:\s+técnica)?|el\s+calendario)(?:\s+de\s+admisión)?"
    + _PERIOD_MODIFIER
    + r",\s*"
    r"|(?:el\s+calendario|la\s+guía(?:\s+técnica)?)(?:\s+de\s+admisión)?"
    + _PERIOD_MODIFIER
    + r"\s+(?:"
    + _ATTRIBUTION_VERBS
    + r")\s+(?:que\s+)?)"
)
_PERIOD_CLAUSE = re.compile(
    r"\b(?:en|para|de|del)\s+"
    r"(?:(?:el|la)\s+)?(?:(?:periodo|semestre|convocatoria|proceso(?:\s+de\s+admisión)?)"
    r"(?:\s+académic[oa])?\s+)?"
    r"(\d{4}-[1-4])\b,?"
)
_PERIOD_BOUNDARY_WORDS = frozenset({
    "antes", "después", "partir", "desde", "hasta", "fuera",
    "salvo", "excepto", "distinto", "distinta", "diferente", "no",
})


def _normalize_claim_text(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split()).replace(
        "período", "periodo"
    )


def _strip_attribution_prefixes(text, source_titles):
    prefixes = []
    for _ in range(2):
        attributed = re.match(r"^según (?:la |el )?([^,]+),\s*", text)
        if attributed and attributed[1] in source_titles:
            prefixes.append(attributed[0])
            text = text[attributed.end() :]
            continue
        verb_attr = re.match(
            rf"^(?:la |el )?(.+?)\s+(?:{_ATTRIBUTION_VERBS})\s+(?:que\s+)?",
            text,
        )
        if verb_attr and verb_attr[1] in source_titles:
            prefixes.append(verb_attr[0])
            text = text[verb_attr.end() :]
            continue
        generic = _GENERIC_FRAME.match(text)
        if generic:
            prefixes.append(generic[0])
            text = text[generic.end() :]
            continue
        break
    return " ".join(prefixes), text


def _claim_words(claim, source_titles):
    """Only normalize simple attribution and scheduling paraphrases.

    Keep the event, actor, periods, conditions, negation, time values and their
    order. A rescheduling, an actual occurrence, or another event must differ.
    """
    text = _normalize_claim_text(claim)
    prefixes, text = _strip_attribution_prefixes(text, source_titles)
    if "de admisión" in prefixes:
        text = re.sub(
            r"\bel examen(?=\s+(?:para|se|estaba|está|tendr|en|el|los|días?|\d)|$)",
            "el examen de admisión",
            text,
        )
    prefix_periods = _PERIOD_TOKEN.findall(prefixes)
    body_periods = _PERIOD_TOKEN.findall(text)
    extracted_periods = list(prefix_periods)
    if len(set(prefix_periods) | set(body_periods)) == 1:
        def _extract_period(match):
            before = text[: match.start()].rstrip().rsplit(None, 1)
            prev_word = before[-1].strip(",.;:") if before else ""
            if prev_word in _PERIOD_BOUNDARY_WORDS:
                return match[0]
            extracted_periods.append(match[1])
            return ""

        text = _PERIOD_CLAUSE.sub(_extract_period, text)
    # Equivalencia acotada a una previsión (se efectuaría el 26). Fechas
    # anteriores, cancelaciones, cambios de sede o de sujeto conservan su léxico.
    text = re.sub(r"\ben(?=\s+(?:(?:el|los)\s+)?días?\s+\d)", "", text)
    day = r"(?=\s+(?:(?:el|los)\s+)?(?:días?\s+)?\d)"
    text = re.sub(
        r"\b(?:se (?:efectuar|realizar|celebrar|presentar)(?:á|ía)"
        r"|se llevar(?:á|ía) a cabo|tendr(?:á|ía) lugar"
        r"|est(?:á|aba) programad[oa] para|para)" + day,
        "",
        text,
    )
    text = re.sub(r"\b(?:(?:el|los)\s+(?:días?\s+)?|días?\s+)(?=\d)", "", text)
    tokens = tuple(re.findall(r"\d+(?:[.,:]\d+)?|[^\W\d_]+|[%$€£+−<>=/–-]", text))
    return (tokens, tuple(sorted(set(extracted_periods))))


def _claim_values(finding):
    """Compare whole assertions individually inside each requirement."""
    sufficiency = finding["sufficiency"]
    titles = {_normalize_claim_text(str(s.get("title") or "")) for s in finding["supports"]}
    titles.update(re.sub(r"\s*[-–·]\s*v\d+\s*$", "", title) for title in list(titles))
    values = {}
    for check in sufficiency["requirement_checks"]:
        assertions = []
        for index in check["coverage_indexes"]:
            row = sufficiency["coverage"][index]
            assertions.append((row["use"], _claim_words(row["claim"], titles)))
        values[check["requirement_id"]] = sorted(assertions)
    return values


def _native_citations_match(finding, native):
    by_id = {c["chunk_id"]: c for c in native}
    citations = [c for row in finding["sufficiency"]["coverage"] for c in row["citations"]]
    cited = {c["chunk_id"] for c in citations}
    selected = {s["chunk_id"] for s in finding["supports"]}
    if not cited or not cited <= selected <= by_id.keys():
        return False

    def literal(value):
        return " ".join(unicodedata.normalize("NFC", value).split())

    return all(
        literal(c["quote"]) and literal(c["quote"]) in literal(by_id[c["chunk_id"]]["quote"])
        for c in citations
    ) and all(
        s.get(key) == by_id[s["chunk_id"]].get(key)
        for s in finding["supports"]
        for key in ("source_id", "document_id", "version", "sha256", "extraction_revision",
                    "method", "page", "line_start", "line_end", "quote")
    )


def _native_conflicts(request, alternate, native):
    """Keep evidenced disagreements auditable outside the primary finding's citations."""
    coverage = alternate.get("sufficiency") or {}
    conflicts = [
        item for item in alternate.get("missing", []) if item.get("basis") == "contradiction"
    ]
    if (not conflicts or alternate.get("request_id") != request["id"]
            or coverage.get("request_requirements") != request.get("request_requirements")
            or not _native_citations_match(alternate, native)):
        return []
    sources = {c["chunk_id"]: c for c in native}
    records = []
    for check in conflicts:
        linked = set(check.get("linked_chunk_ids") or [])
        quotes = dict.fromkeys(
            (c["chunk_id"], c["quote"])
            for row in coverage["coverage"] for c in row["citations"] if c["chunk_id"] in linked
        )
        if len(quotes) < 2 or {key for key, _ in quotes} != linked:
            continue
        records.append({
            "affected_claim": check.get("affected_claim"),
            "reason": check.get("why_unresolved"),
            "required_check": check["description"],
            "requirement_ids": check.get("requirement_ids", []),
            "citations": [
                {**{k: sources[cid][k] for k in ("source_id", "document_id", "version", "sha256",
                                                  "page", "line_start", "line_end")},
                 "chunk_id": cid, "quote": quote}
                for cid, quote in quotes
            ],
        })
    return records


def assess_with_independent_support(request, candidates, assess, *, check_scope=None):
    primary = assess(request, candidates)
    native = _native_candidates(request, primary, candidates)
    if not native:
        return primary
    if check_scope:
        check_scope()
    sufficiency = primary["sufficiency"]
    targets = [
        {"requirement_id": check["requirement_id"],
         "claims": [{"claim": sufficiency["coverage"][index]["claim"],
                     "use": sufficiency["coverage"][index]["use"]}
                    for index in check["coverage_indexes"]]}
        for check in sufficiency["requirement_checks"]
    ]
    try:
        with operation("sources.read_independent"):
            alternate = assess({**request, "_claims_to_verify": targets}, native)
    except DomainError:
        # A failed optional reading cannot invalidate the completed primary one.
        return {**primary, "independent_read_status": "error"}
    finally:
        if check_scope:
            check_scope()
    if (
        alternate.get("missing")
        or alternate.get("status") != "references_found"
        or not _complete_coverage(request, alternate)
        or _claim_values(alternate) != _claim_values(primary)
        or not _native_citations_match(alternate, native)
    ):
        retained = {**primary, "independent_read_status": "insufficient"}
        conflicts = _native_conflicts(request, alternate, native)
        if conflicts:
            retained["independent_read_conflicts"] = conflicts
        return retained
    checks = [{**deepcopy(c), "blocks_approval": False} for c in primary["missing"]]
    # Retain the primary candidate inventory for audit. The review cannot cite
    # an excluded transcription through the manual candidate picker.
    documents = deepcopy(primary.get("candidate_documents", []))
    selected_docs = {s["source_id"] for s in alternate["supports"]}
    excluded_docs = {sid for check in checks for sid in check["linked_source_ids"]}
    for doc in documents:
        doc["selected_as_support"] = doc["source_id"] in selected_docs
    return {
        **alternate,
        "independent_read_status": "supported",
        "candidate_documents": documents,
        "secondary_source_checks": checks,
        "selection_status": (
            "additional_candidates_available"
            if any(d["source_id"] not in selected_docs | excluded_docs for d in documents)
            else "all_candidates_selected"
        ),
    }
