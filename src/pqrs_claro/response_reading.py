"""Acknowledgment of the exact saved responses; independent of approval."""

from .source_library import digest


def open_gaps(row):
    has_answer = any((p.get("text") or "").strip() for p in row.get("paragraphs", []))
    return list(
        dict.fromkeys(
            item["description"]
            for item in row.get("pending", [])
            if item.get("description")
            and (item.get("blocks_approval", True) or not has_answer)
            and (item.get("resolution") or {}).get("action")
            not in {"resolved", "not_applicable"}
        )
    )


def reading_state(case, rows, saved=None, *, fiaga_prepared=None):
    ids = [r["id"] for r in (case.get("identification") or {}).get("requests", [])]
    by_id = {row["request_id"]: row for row in rows}
    eligible = (
        bool(ids)
        and case.get("status") == "confirmed"
        and fiaga_prepared is not False
        and all(
            key in by_id
            and not by_id[key].get("stale")
            and by_id[key].get("status") not in {"checking", "error", "stale"}
            and (
                (
                    not by_id[key].get("pre_draft")
                    and by_id[key].get("paragraphs")
                    and all(p.get("text", "").strip() for p in by_id[key]["paragraphs"])
                )
                or (fiaga_prepared and not by_id[key].get("paragraphs") and open_gaps(by_id[key]))
            )
            for key in ids
        )
    )
    contents = []
    for key in ids:
        row = by_id.get(key, {})
        paragraphs = row.get("paragraphs", [])
        citations = {cid for p in paragraphs for cid in p.get("cited_chunk_ids", [])}
        facts = {fid for p in paragraphs for fid in p.get("cited_fact_ids", [])}
        contents.append(
            {
                "request_id": key,
                "paragraphs": paragraphs,
                "supports": [
                    {
                        k: s.get(k)
                        for k in (
                            "chunk_id",
                            "source_id",
                            "version",
                            "sha256",
                            "quote",
                            "extraction_revision",
                        )
                    }
                    for s in row.get("available_supports", [])
                    if s["chunk_id"] in citations
                ],
                "facts": [f for f in row.get("facts", []) if f["id"] in facts],
            }
        )
        if fiaga_prepared is not None:
            contents[-1]["gaps"] = open_gaps(row)
    fingerprint = digest({"version": 1, "case_version": case["version"], "contents": contents})
    confirmed = bool(eligible and saved and saved["content_hash"] == fingerprint)
    return {
        "eligible": eligible,
        "content_hash": fingerprint,
        "confirmed": confirmed,
        "response_count": len(ids),
        "changed_since_confirmation": bool(saved and saved["content_hash"] != fingerprint),
        "reviewed_by": saved["reviewed_by"] if confirmed else None,
        "reviewed_at": saved["reviewed_at"] if confirmed else None,
    }
