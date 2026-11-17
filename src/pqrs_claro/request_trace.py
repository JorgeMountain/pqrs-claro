"""A derived view of existing coverage links, not another semantic assessor.

This view cannot prove entailment or document absence. It reports validated links
and explicit omissions from the current review; unknown mappings remain unknown.
No source, pending control, resolution, or model response is changed here.
"""

import unicodedata

from .answer_coverage import detail_issues, unit_issues, validate_units
from .evidence_contract import _delivery_is_represented, request_scope, source_version
from .models import DomainError
from .request_requirements import build_requirements, draft_requirement_issues
from .source_retrieval import source_in_scope


def _unique(rows, key):
    """Duplicate identifiers are ambiguous, never resolved by last-write-wins."""
    result, duplicates = {}, set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str):
            continue
        identity = row[key]
        if identity in result:
            duplicates.add(identity)
        result[identity] = row
    return {key: row for key, row in result.items() if key not in duplicates}


def _indexes(values, size):
    return (isinstance(values, list)
            and all(type(i) is int and 0 <= i < size for i in values)
            and len(values) == len(set(values)))


def _specific_open(item):
    resolution = item.get("resolution") or {}
    return (bool(str(item.get("description") or "").strip())
            and item.get("basis") != "metadata_only"
            and item.get("stage", "evidence") == "evidence"
            and item.get("blocks_approval", True) is not False
            and item.get("state") not in {
                "closed", "resolved", "dismissed", "verified", "completed"}
            and resolution.get("status") in {None, "open"}
            and resolution.get("action") in {None, "open"})


def _current_fulfillment(item, request, requirement_id, finding, sources, registered):
    """A future action is an independent fact about the registry, never coverage."""
    key = item.get("check_key")
    original = registered.get(key)
    if not original or any(item.get(field) != original.get(field) for field in (
            "description", "affected_claim", "reason_code", "stage", "blocks_approval",
            "scope_key", "linked_chunk_ids", "source_versions")):
        return False
    for value in (item, original):
        resolution = value.get("resolution") or {}
        if (value.get("stage") != "fulfillment" or value.get("blocks_approval") is not False
                or resolution.get("status") not in {None, "open"}
                or resolution.get("action") not in {None, "open"}
                or value.get("state") in {"closed", "resolved", "dismissed", "completed"}):
            return False
    if (request["id"] not in original.get("request_ids", [])
            or original.get("scope_key") != request_scope(request)):
        return False
    chunks = set(original.get("linked_chunk_ids", []))
    if not chunks or not chunks <= sources.keys():
        return False
    versions = sorted({sources[c]["source_id"]: source_version(sources[c])
                       for c in chunks}.values(), key=lambda row: row["source_id"])
    if sorted(original.get("source_versions", []), key=lambda row: row["source_id"]) != versions:
        return False
    requirement_ids = original.get("requirement_ids", [])
    if requirement_ids:
        return requirement_id in requirement_ids
    sufficiency = finding.get("sufficiency") or {}
    review = _unique(sufficiency.get("requirement_checks", []), "requirement_id").get(
        requirement_id, {})
    gaps = sufficiency.get("evaluated_gaps", [])
    indexes = review.get("missing_indexes", [])
    if not _indexes(indexes, len(gaps)):
        return False
    if any(
        gap.get("stage") == "fulfillment"
        and gap.get("description") in {original.get("description"),
                                       original.get("original_description")}
        and gap.get("affected_claim") == original.get("affected_claim")
        and set(gap.get("source_chunk_ids", [])) == chunks
        for gap in (gaps[i] for i in indexes)
    ):
        return True
    if original.get("reason_code") == "document_delivery":
        from .request_intent import classify_request_intent

        requirements = request.get("request_requirements") or build_requirements(request)
        deliveries = [r["id"] for r in requirements if classify_request_intent(
            {"description": r["text"]})["document_delivery_requested"]]
        actions = [value for value in registered.values()
                   if value.get("stage") == "fulfillment"
                   and value.get("reason_code") == "document_delivery"]
        # Reuse the contract's exact supported-copy path, including its literal,
        # object, permission and version guards; no second semantic matcher.
        return (deliveries == [requirement_id] and len(actions) == 1
                and _delivery_is_represented(request, finding))
    return False


def _literal_ids(citations, sources):
    if not citations:
        return []
    ids = []
    for citation in citations:
        source = sources.get(citation.get("chunk_id"))
        quote = citation.get("quote")
        if not source or not isinstance(quote, str) or not quote.strip():
            return []
        # Same NFC/whitespace equivalence as source_sufficiency._literal; retain
        # the original citation text and distinguish every actual word/number.
        literal = " ".join(unicodedata.normalize("NFC", quote).split())
        original = " ".join(unicodedata.normalize("NFC", source.get("quote", "")).split())
        if literal not in original:
            return []
        ids.append(citation["chunk_id"])
    return list(dict.fromkeys(ids))


def _source_links(requirement_id, sufficiency, sources):
    check = _unique(sufficiency.get("requirement_checks", []), "requirement_id").get(requirement_id)
    if not check:
        return [], [], False
    coverage = sufficiency.get("coverage", [])
    ci, mi = check.get("coverage_indexes", []), check.get("missing_indexes", [])
    ui = check.get("uncertainty_indexes", [])
    if (not _indexes(ci, len(coverage))
            or not _indexes(mi, len(sufficiency.get("evaluated_gaps", [])))
            or not _indexes(ui, len(sufficiency.get("uncertainties", [])))):
        return [], [], False
    citations = [_literal_ids(coverage[i].get("citations", []), sources) for i in ci]
    if any(not ids for ids in citations):
        return [], [], False
    valid = ((check.get("status") == "supported" and bool(ci) and not (mi or ui))
             or (check.get("status") == "pending" and bool(mi or ui)))
    if mi and not ui and not any(
        sufficiency["evaluated_gaps"][i].get("basis") != "metadata_only" for i in mi
    ):
        valid = False
    if not valid:
        return [], [], False
    return list(ci), list(dict.fromkeys(cid for ids in citations for cid in ids)), True


def _valid_requirement(requirement, row, draft):
    if not row or not all(key in row for key in
                          ("status", "paragraph_indexes", "pending_indexes", "explanation")):
        return False
    if row["status"] not in {"answered", "pending", "omitted"}:
        return False
    if (not _indexes(row["paragraph_indexes"], len(draft["paragraphs"]))
            or not _indexes(row["pending_indexes"], len(draft["pending"]))):
        return False
    issues = draft_requirement_issues(
        {"request_requirements": [requirement]}, {"requirement_checks": [row]}, draft,
    )
    if any(i["code"] != "request_component_omitted" for i in issues):
        return False
    if row["status"] == "pending":
        return all(_specific_open(draft["pending"][i]) for i in row["pending_indexes"])
    return bool(str(row["explanation"]).strip())


def _omission(kind, identity, description, ids, indexes, unit_id=None):
    return {
        "kind": kind, "id": identity, "unit_id": unit_id,
        "description": description, "evidence_chunk_ids": list(ids),
        "paragraph_indexes": list(indexes), "repair_paragraph_index": None,
    }


def build_request_trace(request, finding, plan, draft=None, checks=None):
    """Connect existing R/U/detail IDs to current sources and reviewed paragraphs.

    ``reviewed_answer`` means the existing review linked an answer, not that this
    deterministic function established semantic correctness. ``retrieval_gap``
    means no cited coverage was selected for an explicitly evaluated gap, never
    that the document does not exist. Missing/invalid mappings are not_evaluated.
    """
    requirements = request.get("request_requirements") or build_requirements(request)
    checks = checks or {}
    draft = draft or {"paragraphs": [], "pending": []}
    paragraphs, pending = draft.get("paragraphs", []), draft.get("pending", [])
    sources = _unique([
        source for source in finding.get("supports", [])
        if source_in_scope(request, source)
        and source.get("is_latest") is not False
        and source.get("validity") != "superseded"
        and source.get("category") != "historical_petition"
    ], "chunk_id")
    inventory_valid = True
    try:
        units = validate_units(plan.get("coverage_units", []), request, sources)
    except DomainError:
        inventory_valid = False
        units = []  # Stale/revoked/unvalidated inventory never supplies repair evidence.
    unit_reviews = _unique(checks.get("unit_checks", []), "unit_id")
    requirement_reviews = _unique(checks.get("requirement_checks", []), "requirement_id")
    detail_reviews = _unique(checks.get("detail_checks", []), "detail_id")
    registered = _unique(finding.get("checks") or finding.get("actions", []), "check_key")
    sufficiency = finding.get("sufficiency") or {}
    result = {"version": 1, "requirements": [], "missing_unit_ids": []}
    for requirement in requirements:
        rid = requirement["id"]
        ci, source_ids, source_evaluated = _source_links(rid, sufficiency, sources)
        relevant = [unit for unit in units if unit["requirement_id"] == rid and unit["required"]]
        ids = list(dict.fromkeys([*source_ids, *[
            citation["chunk_id"] for unit in relevant for citation in unit["citations"]
        ]]))
        row = {
            "requirement_id": rid, "text": requirement["text"], "status": "not_evaluated",
            "coverage_indexes": ci, "evidence_chunk_ids": ids,
            "unit_ids": [unit["id"] for unit in relevant],
            "paragraph_indexes": [], "pending_check_keys": [], "fulfillment_check_keys": [],
            "omissions": [],
        }
        review = requirement_reviews.get(rid)
        fulfillment_indexes = {
            i for i, item in enumerate(pending)
            if _current_fulfillment(item, request, rid, finding, sources, registered)
        }
        row["fulfillment_check_keys"] = list(dict.fromkeys(
            pending[i]["check_key"] for i in sorted(fulfillment_indexes)
        ))
        # A review may mix an evidenced answer with its future execution. Keep
        # evidence gaps separate; only the complete unit/detail review below can
        # establish reviewed content when every linked pending is fulfillment.
        operational_review = bool(
            review and review.get("status") == "pending"
            and _indexes(review.get("paragraph_indexes"), len(paragraphs))
            and _indexes(review.get("pending_indexes"), len(pending))
            and review["pending_indexes"]
            and str(review.get("explanation", "")).strip()
            and all(i in fulfillment_indexes or _specific_open(pending[i])
                    for i in review["pending_indexes"])
            and any(i in fulfillment_indexes for i in review["pending_indexes"])
        )
        content_review = review
        if operational_review:
            content_review = {**review, "pending_indexes": [
                i for i in review["pending_indexes"] if i not in fulfillment_indexes
            ]}
        review_valid = _valid_requirement(requirement, content_review, draft)
        if review_valid:
            row["paragraph_indexes"] = list(content_review["paragraph_indexes"])
            row["pending_check_keys"] = list(dict.fromkeys(
                pending[i]["check_key"] for i in content_review["pending_indexes"]
                if pending[i].get("check_key") and _specific_open(pending[i])
            ))
            if review["status"] == "omitted":
                row["omissions"].append(_omission(
                    "requirement", rid, requirement["text"] + " " + review["explanation"],
                    ids, review["paragraph_indexes"],
                ))
            elif review["status"] == "pending":
                row["status"] = "pending"
            elif ids and review["paragraph_indexes"]:
                row["status"] = "reviewed_answer"

        answered_indexes = set()
        unit_review_complete = inventory_valid
        all_material_answered = inventory_valid and bool(relevant)
        for unit in relevant:
            unit_review = unit_reviews.get(unit["id"])
            unit_valid = bool(unit_review) and not any(
                issue["code"] != "answer_unit_omitted"
                for issue in unit_issues([unit], [unit_review], draft)
            )
            unit_review_complete = unit_review_complete and unit_valid
            all_material_answered = (all_material_answered and unit_valid
                                     and unit_review["status"] == "answered")
            if unit_valid:
                if unit_review["status"] == "omitted":
                    row["omissions"].append(_omission(
                        "unit", unit["id"], unit["claim"] + " " + unit_review["explanation"],
                        [c["chunk_id"] for c in unit["citations"]],
                        unit_review["paragraph_indexes"], unit["id"],
                    ))
                elif unit_review["status"] == "answered":
                    answered_indexes.update(unit_review["paragraph_indexes"])
                elif unit_review["status"] == "pending":
                    row["status"] = "pending"
                    row["pending_check_keys"].extend(
                        pending[i]["check_key"] for i in unit_review["pending_indexes"]
                        if pending[i].get("check_key")
                    )
            # Use the existing detail validator, including its lexical identity check.
            detail_rows = [detail_reviews[detail["id"]] for detail in unit.get("details", [])
                           if detail["id"] in detail_reviews]
            issues = detail_issues([unit], detail_rows, draft, require_current=False)
            all_material_answered = (all_material_answered and not issues
                                     and len(detail_rows) == len(unit.get("details", []))
                                     and all(r.get("status") == "answered" for r in detail_rows))
            unit_review_complete = unit_review_complete and not any(
                i["code"] in {"detail_review_invalid", "detail_review_incomplete"} for i in issues
            )
            if not any(i["code"] in {"detail_review_invalid", "detail_review_incomplete"}
                       for i in issues):
                for detail in unit.get("details", []):
                    matches = [i for i in issues if i["code"] == "answer_detail_omitted"
                               and i["description"].startswith(f"Falta conservar {detail['id']}:")]
                    for issue in matches:
                        targets = ([] if issue["paragraph_index"] is None
                                   else [issue["paragraph_index"]])
                        row["omissions"].append(_omission(
                            "detail", detail["id"], issue["description"],
                            [detail["citation"]["chunk_id"]], targets, unit["id"],
                        ))
        for omission in row["omissions"]:
            # A source shared by different procedures is insufficient to select a
            # destination. Reuse only a reviewed unit of the SAME request component.
            targets = omission["paragraph_indexes"] or sorted(answered_indexes)
            targets = [i for i in targets if 0 <= i < len(paragraphs)
                       and set(omission["evidence_chunk_ids"]).intersection(
                           paragraphs[i].get("cited_chunk_ids", []))]
            if len(targets) == 1:
                omission["repair_paragraph_index"] = targets[0]
            if (omission["kind"] == "unit" and not omission["paragraph_indexes"]
                    and omission["repair_paragraph_index"] is None):
                result["missing_unit_ids"].append(omission["unit_id"])
        if (operational_review and all_material_answered and not row["omissions"]
                and not row["pending_check_keys"] and source_evaluated):
            row["status"] = "reviewed_answer"
            row["paragraph_indexes"] = sorted(answered_indexes)
        if row["omissions"] and any(o["evidence_chunk_ids"] for o in row["omissions"]):
            row["status"] = "evidence_not_used"
        elif not unit_review_complete:
            row["status"] = "not_evaluated"
        elif not ids and source_evaluated and row["status"] == "not_evaluated":
            row["status"] = "retrieval_gap"
        if (row["status"] == "reviewed_answer" and row["fulfillment_check_keys"]
                and not relevant):
            row["status"] = "not_evaluated"
        row["pending_check_keys"] = list(dict.fromkeys(row["pending_check_keys"]))
        result["requirements"].append(row)
    return result


def trace_repair_issues(trace, draft):
    """Give the existing bounded repair explicit, unambiguous paragraph targets."""
    codes = {"requirement": "request_component_omitted", "unit": "answer_unit_omitted",
             "detail": "answer_detail_omitted"}
    result = []
    for row in trace.get("requirements", []):
        specific = any(o["kind"] in {"unit", "detail"} for o in row["omissions"])
        for omission in row["omissions"]:
            # A parent request omission must not repair the same content in an
            # existing paragraph while its specific unit is separately appended.
            if specific and omission["kind"] == "requirement":
                continue
            index = omission["repair_paragraph_index"]
            if (type(index) is int and 0 <= index < len(draft.get("paragraphs", []))
                    and omission["evidence_chunk_ids"]):
                result.append({
                    "code": codes[omission["kind"]], "paragraph_index": index,
                    "description": f"{row['requirement_id']} / {omission['id']}: "
                                   + omission["description"],
                })
    return result
