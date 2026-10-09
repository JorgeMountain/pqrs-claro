"""Carry confirmed intake decisions into drafting without treating them as evidence."""

from copy import deepcopy


def drafting_context(review, request_id):
    """Select only this request and shared observations; omit global revision counters.

    The caller enforces current human confirmation. Stable per-request content lets
    unrelated requests reuse checkpoints after another decision changes.
    """
    report = review["report"]
    decision = next(r for r in review["decisions"] if r["request_id"] == request_id)
    assessment = next(r for r in report["requests"] if r["request_id"] == request_id)

    def observations(item):
        return [
            {
                key: deepcopy(check.get(key))
                for key in ("key", "state", "summary", "reason", "pending")
            }
            for check in item.get("checks", [])
        ]

    def choice(item):
        return {
            key: deepcopy(item.get(key))
            for key in ("route", "note", "communication", "petition_type")
            if key in item
        }

    return {
        "origin": "confirmed_initial_review",
        "is_documentary_evidence": False,
        "reviewed_by": review["reviewed_by"],
        "document": {
            "decision": choice(review["document_decision"]),
            "observations": observations(report["document"]),
        },
        "request": {
            "request_id": request_id,
            "decision": choice(decision),
            "observations": observations(assessment),
        },
        "special_treatment": deepcopy(report.get("special_treatment")),
        "warnings": deepcopy(report.get("warnings", [])),
    }
