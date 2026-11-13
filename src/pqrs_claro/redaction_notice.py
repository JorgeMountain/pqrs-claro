"""Lightweight, transactionally persisted signals for a Redacción tab in another client."""

from .source_library import digest


def install_source_notices(conn):
    # Only group revisions are kept. A watch reads two indexed rows per allowed
    # collection regardless of the number or size of the sources in that scope.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS redaction_scope_revisions (
            case_id TEXT NOT NULL, collection_id TEXT NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY(case_id,collection_id)
        ) WITHOUT ROWID
    """)
    # The catalog uses the latest version of each document. Editing an archived
    # version or rewriting identical data cannot change the displayed evidence.
    latest = """NOT EXISTS (SELECT 1 FROM sources
                WHERE document_id={row}.document_id AND version>{row}.version)"""
    for operation, sides, condition in (
        ("insert", ("NEW",), "NEW.version > 1"),
        ("update", ("OLD", "NEW"), "(OLD.body IS NOT NEW.body OR OLD.pages IS NOT NEW.pages) "
         "AND " + latest.format(row="NEW")),
        ("delete", ("OLD",), latest.format(row="OLD")),
    ):
        scopes = " UNION ".join(
            f"SELECT COALESCE(json_extract({side}.body,'$.case_id'),''),"
            f"COALESCE(json_extract({side}.body,'$.collection_id'),''),1 "
            f"WHERE COALESCE(json_extract({side}.body,'$.category'),'') != 'previous_response'"
            for side in sides
        )
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS redaction_source_{operation}
            AFTER {operation} ON sources WHEN {condition} BEGIN
                INSERT INTO redaction_scope_revisions(case_id,collection_id,revision)
                {scopes} ON CONFLICT(case_id,collection_id) DO UPDATE SET revision=revision+1;
            END
        """)
    install_publication_notices(conn, "source_runs")


def install_publication_notices(conn, table):
    # Both stores publish terminal states. Raw progress, including per-petition
    # writes while a batch runs, must not cause ongoing full screen refreshes.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS redaction_publications (
            case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL
        ) WITHOUT ROWID
    """)
    for operation in ("insert", "update"):
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS redaction_{table}_{operation}
            AFTER {operation} ON {table}
            WHEN json_extract(NEW.body,'$.status') NOT IN ('starting','running') BEGIN
                INSERT INTO redaction_publications VALUES(NEW.case_id,1)
                ON CONFLICT(case_id) DO UPDATE SET revision=revision+1;
            END
        """)


def redaction_notice(library, cases, case_id):
    with library.connect() as conn:
        # Include the shared/collectionless scope and only collections linked
        # to this case. Read links, scope counters and source publication in one
        # SQLite snapshot so a concurrent revocation cannot leave mixed state.
        rows = conn.execute("""
            WITH permitted(id) AS (
                SELECT '' UNION ALL
                SELECT collection_id FROM case_source_collections WHERE case_id=?
            )
            SELECT p.id,COALESCE(shared.revision,0),COALESCE(own.revision,0),
                   (SELECT revision FROM redaction_publications WHERE case_id=?)
            FROM permitted p
            LEFT JOIN redaction_scope_revisions shared
                ON shared.case_id='' AND shared.collection_id=p.id
            LEFT JOIN redaction_scope_revisions own
                ON own.case_id=? AND own.collection_id=p.id
            ORDER BY p.id
        """, (case_id, case_id, case_id)).fetchall()
    with cases.connect() as conn:
        prepared = conn.execute(
            "SELECT revision FROM redaction_publications WHERE case_id=?", (case_id,)
        ).fetchone()
    return {
        "collection_ids": [row[0] for row in rows if row[0]],
        "correction_revision": digest([row[:3] for row in rows]),
        "result_revision": digest([rows[0][3] or 0, prepared[0] if prepared else 0]),
    }
