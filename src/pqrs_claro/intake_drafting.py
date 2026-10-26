"""Carry confirmed intake decisions into drafting without treating them as evidence."""

from copy import deepcopy

from .repetition_scope import optional_repetition


def drafting_context(review, request_id, request=None):
    """Select only this request and shared observations; omit global revision counters.

    The caller enforces current human confirmation. Stable per-request content lets
    unrelated requests reuse checkpoints after another decision changes.
    """
    report = review["report"]
    decision = next(r for r in review["decisions"] if r["request_id"] == request_id)
    assessment = next(r for r in report["requests"] if r["request_id"] == request_id)

    def observations(item, current_request=None):
        result = []
        for check in item.get("checks", []):
            value = {
                key: deepcopy(check.get(key))
                for key in ("key", "state", "summary", "reason", "pending")
            }
            if optional_repetition(check, decision, current_request):
                value.update(
                    pending=[], required_for_response=False,
                    reason="No se estableció reiteración. La consulta pide información general; "
                           "no requiere buscar antecedentes personales para responderla. "
                           "Esto no afirma que no existan consultas anteriores.",
                )
            result.append(value)
        return result

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
            "observations": observations(assessment, request),
        },
        "special_treatment": deepcopy(report.get("special_treatment")),
        "warnings": deepcopy(report.get("warnings", [])),
    }
