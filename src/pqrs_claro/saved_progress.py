"""Read durable work for navigation without recomputing or approving it."""

from datetime import datetime


def saved_stages(case_ids, *, drafts, reviews, offices):
    """Highest stage with stored artifacts; not a freshness/completion verdict.

    Older cases may have responses but no intake_review or preparation record.
    Query only their IDs, never the large source snapshots or response bodies.
    """
    ids = list(case_ids)
    result = {case_id: 0 for case_id in ids}
    if not ids:
        return result
    for store, tables in (
        (drafts, (("draft_runs", 2),)),
        (reviews, (("review_requests", 2), ("office_workspace", 3))),
        (offices, (("office_runs", 3),)),
    ):
        with store.connect() as conn:
            existing = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                slots = ",".join("?" for _ in batch)
                for table, stage in tables:
                    if table not in existing:
                        continue
                    for (case_id,) in conn.execute(
                        f"SELECT DISTINCT case_id FROM {table} WHERE case_id IN ({slots})", batch
                    ):
                        result[case_id] = max(result[case_id], stage)
    return result


def saved_offices(cases, *, reviews, offices):
    """Compact recorded export state; full validation remains at open/download.

    Read only the latest export and revision metadata in batches. Do not scan
    source catalogs, render documents or change management/approval decisions.
    """
    cases = {case["id"]: case for case in cases}
    result = {case_id: None for case_id in cases}
    ids = list(cases)
    if not ids:
        return result
    with offices.connect() as conn, reviews.connect() as review_db:
        has_workspace = review_db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='office_workspace'"
        ).fetchone()
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            slots = ",".join("?" for _ in batch)
            runs = conn.execute(
                "SELECT case_id,id,json_extract(body,'$.status'),"
                "json_extract(body,'$.stale'),json_extract(body,'$.created_at') "
                "FROM office_runs WHERE rowid IN (SELECT MAX(rowid) FROM office_runs "
                f"WHERE case_id IN ({slots}) GROUP BY case_id)", batch,
            ).fetchall()
            if not runs:
                continue
            batch = [row[0] for row in runs]
            slots = ",".join("?" for _ in batch)
            records = {}
            for cid, status, stale, updated, version in review_db.execute(
                "SELECT r.case_id,json_extract(r.body,'$.status'),"
                "json_extract(r.body,'$.stale'),json_extract(r.body,'$.updated_at'),"
                "json_extract(a.body,'$.case_version') FROM review_requests r "
                "LEFT JOIN review_approvals a ON a.id=json_extract(r.body,'$.approval.id') "
                f"AND a.case_id=r.case_id WHERE r.case_id IN ({slots})", batch,
            ):
                records.setdefault(cid, []).append((status, stale, updated, version))
            workspace = dict(review_db.execute(
                "SELECT case_id,json_extract(body,'$.updated_at') FROM office_workspace "
                f"WHERE case_id IN ({slots})", batch,
            )) if has_workspace else {}
            for cid, run_id, status, stale, created in runs:
                case, rows = cases[cid], records.get(cid, [])
                if status in {"ready", "generating"} and not stale:
                    # Any subsequent edit or replaced approval means the recorded
                    # export cannot complete the progress of the current content.
                    stale = not rows or len(rows) != case.get("request_count") or any(
                        state != "approved" or old or version != case["version"]
                        or not _at_or_before(updated, created)
                        for state, old, updated, version in rows
                    ) or (cid in workspace and not _at_or_before(workspace[cid], created))
                result[cid] = {"id": run_id, "status": "stale" if stale else status}
    return result


def _at_or_before(value, limit):
    try:
        return datetime.fromisoformat(value) <= datetime.fromisoformat(limit)
    except (TypeError, ValueError):
        return False
