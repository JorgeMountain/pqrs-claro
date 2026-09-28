"""Read timestamp projections without loading full reports into the inbox."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def latest_activity(store):
    result = {}

    def collect(conn, table):
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            return
        fields = ("updated_at", "created_at", "started_at", "finished_at", "completed_at")
        projection = ",".join(f"json_extract(body, '$.{field}')" for field in fields)
        for case_id, *timestamps in conn.execute(f'SELECT case_id,{projection} FROM "{table}"'):
            for value in timestamps:
                if not value:
                    continue
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                normalized = (
                    stamp.replace(tzinfo=stamp.tzinfo or timezone.utc)
                    .astimezone(timezone.utc)
                    .isoformat()
                )
                result[case_id] = max(result.get(case_id, ""), normalized)

    with store.connect() as conn:
        for table in ("intake_reviews", "preparations"):
            collect(conn, table)
    for filename, tables in (
        ("biblioteca.sqlite", ("source_runs",)),
        ("borradores.sqlite", ("draft_runs",)),
        ("revisiones.sqlite", ("review_requests", "response_proposals", "office_workspace")),
        ("oficios.sqlite", ("office_runs",)),
    ):
        path = store.root / filename
        if path.exists():
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)) as conn:
                for table in tables:
                    collect(conn, table)
    return result
