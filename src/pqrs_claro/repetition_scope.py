"""Keep an unverified repetition search from becoming a universal requirement.

This narrow rule does not close saved checks or infer that prior petitions do not
exist. Concrete antecedents, comparisons requested by the person, human notes,
contradictions and incomplete source coverage retain their existing controls.
"""

import json
import re
import unicodedata


def plain(value):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", str(value).lower())
            if not unicodedata.combining(c)
        ).split()
    )


def mentions_history(value):
    return bool(
        re.search(
            r"\b(?:anterior(?:es)?|previas?|previos?|reiter\w*|historial|antecedentes?|"
            r"previamente|ya (?:respond\w*|solicit\w*|consult\w*|pregunt\w*))\b",
            plain(value),
        )
    )


def optional_repetition(check, decision, request):
    from .request_intent import classify_request_intent

    return bool(
        request
        and decision.get("route") == "continue"
        and classify_request_intent(request)["intents"] == ["information"]
        and check.get("key") == "repetition"
        and check.get("state") in {"unverified", "unavailable", "not_checked"}
        and not check.get("sources")
        and not mentions_history(
            json.dumps(
                {k: request.get(k) for k in ("title", "description", "context", "source_refs")},
                ensure_ascii=False,
            )
        )
        and not mentions_history(decision.get("note", ""))
    )


def optional_history_proposal(request, finding, proposal, paragraphs):
    """Filter only NEW generic proposals matching a known non-required check."""
    initial = request.get("initial_review", {}).get("request", {})
    if not any(
        c.get("key") == "repetition" and c.get("required_for_response") is False
        for c in initial.get("observations", [])
    ):
        return False
    if finding.get("sufficiency", {}).get("coverage_complete") is not True:
        return False
    if not paragraphs or mentions_history(" ".join(p.get("text", "") for p in paragraphs)):
        return False
    if proposal.get("basis") in {"contradiction", "unreadable"} or any(
        proposal.get(key)
        for key in ("linked_source_ids", "linked_chunk_ids", "existing_check_keys")
    ):
        return False
    description = plain(proposal.get("description", ""))
    return bool(
        proposal.get("kind") in {"document", "clarification"}
        and re.match(r"^(?:revisar|verificar|comparar|comprobar|buscar|confirmar)\b", description)
        and re.search(r"\b(?:solicitud|consulta)\b", description)
        and "respuesta" in description
        and "misma persona" in description
        and mentions_history(description)
    )
