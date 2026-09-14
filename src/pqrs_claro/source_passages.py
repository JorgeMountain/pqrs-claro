"""Resolve closed, chunk-local line ranges without asking the model to copy text."""

from pydantic import Field, StrictInt

from .models import DomainError, StrictModel

PASSAGE_SELECTION_VERSION = 1


class PassageRange(StrictModel):
    chunk_id: str = Field(min_length=1)
    line_start: StrictInt = Field(ge=1)
    line_end: StrictInt = Field(ge=1)


class SourceAnalysisError(DomainError):
    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic


def numbered_lines(quote):
    # Keep line endings in the original. Numbers refer to this chunk, not PDF lines.
    return [{"number": i, "text": text} for i, text in enumerate(quote.splitlines(True), 1)]


def resolve_passages(selection, candidates):
    """Return the legacy internal contract plus auditable source locations.

    No fuzzy matching, clipping, joining separate passages or accepting unknown IDs.
    The evidence contract still checks roles, scope and coverage after resolution.
    """
    data = selection.model_dump()
    selected = {s["chunk_id"] for s in data["supports"]}
    locations, errors = [], []

    def resolve(item, *, kind, index, citation_index=None):
        alias = item["chunk_id"]
        source = candidates.get(alias)
        lines = source["quote"].splitlines(True) if source else []
        start, end = item.pop("line_start"), item.pop("line_end")
        error = {"kind": kind, "aspect_index": index, "chunk_id": alias,
                 "line_start": start, "line_end": end, "line_count": len(lines)}
        if source is None:
            reason = "unknown_candidate"
        elif alias not in selected:
            reason = "candidate_not_selected_in_supports"
        elif not 1 <= start <= end <= len(lines):
            reason = "invalid_passage_range"
        else:
            quote = "".join(lines[start - 1:end])
            limit = 6000 if kind == "declaration" else 10000
            reason = ("empty_passage" if not quote.strip() else
                      "passage_too_long" if len(quote) > limit else None)
        if reason:
            errors.append({**error, "reason": reason})
            return
        item["declaration_quote" if kind == "declaration" else "quote"] = quote
        locations.append({"kind": kind, "aspect_index": index,
                          "citation_index": citation_index, "chunk_id": source["chunk_id"],
                          "source_id": source["source_id"], "page": source["page"],
                          "chunk_line_start": source["line_start"],
                          "chunk_line_end": source["line_end"],
                          "passage_line_start": start, "passage_line_end": end})

    for index, coverage in enumerate(data["coverage"]):
        for citation_index, citation in enumerate(coverage["citations"]):
            resolve(citation, kind="coverage", index=index, citation_index=citation_index)
    for index, check in enumerate(data["declared_checks"]):
        resolve(check, kind="declaration", index=index)
    return data, locations, errors


def diagnostic(code, *, attempts=0, errors=(), history=()):
    # Deliberately exclude provider responses, credentials and copied source bodies.
    allowed = {"reason", "kind", "aspect_index", "chunk_id", "line_start", "line_end",
               "line_count", "use", "selected_role", "effective_role", "allowed_uses"}
    def clean(items):
        return [{k: v for k, v in e.items() if k in allowed} for e in items]

    return {"code": code, "stage": "source_assessment", "attempts": attempts,
            "passage_selection_version": PASSAGE_SELECTION_VERSION,
            "errors": clean(errors),
            "attempt_history": [{"attempt": h["attempt"], "errors": clean(h["errors"])}
                                for h in history]}
