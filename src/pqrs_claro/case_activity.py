"""Read timestamp projections without loading full reports into the inbox."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def latest_activity(store, *, case_ids=None):
    result = {}
    ids = list(case_ids) if case_ids is not None else None
    if ids == []:
        return result

    def collect(conn, table):
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            return
        fields = ("updated_at", "created_at", "started_at", "finished_at", "completed_at")
        body, case_column, source = "body", "case_id", f'"{table}"'
        if table == "source_runs" and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_run_progress'"
        ).fetchone():
            # Progress contains the entire run except its immutable, potentially huge
            # source_snapshot. It also has newer timestamps while a run is active.
            body, case_column = "COALESCE(p.body,r.body)", "r.case_id"
            source = "source_runs r LEFT JOIN source_run_progress p ON p.run_id=r.id"
        projection = ",".join(f"json_extract({body}, '$.{field}')" for field in fields)
        batches = [None] if ids is None else [ids[i:i + 500] for i in range(0, len(ids), 500)]
        for batch in batches:
            condition = (f" WHERE {case_column} IN ({','.join('?' for _ in batch)})"
                         if batch is not None else "")
            for case_id, *timestamps in conn.execute(
                f"SELECT {case_column},{projection} FROM {source}{condition}", batch or ()
            ):
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
