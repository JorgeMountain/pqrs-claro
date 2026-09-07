"""Historial de borradores internos, separado de expedientes y biblioteca."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .storage import now


class DraftStore:
    def __init__(self, data_dir):
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "borradores.sqlite"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS draft_runs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS draft_runs_case ON draft_runs(case_id);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def save(self, run):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO draft_runs VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (run["id"], run["case_id"], json.dumps(run, ensure_ascii=False)),
            )

    def latest(self, case_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body FROM draft_runs WHERE case_id=? ORDER BY rowid DESC LIMIT 1",
                (case_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def recover(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT body FROM draft_runs").fetchall()
        for row in rows:
            run = json.loads(row[0])
            if run["status"] == "running":
                run.update(
                    status="failed",
                    current_step=None,
                    current_request_id=None,
                    finished_at=now(),
                    error="La preparación se interrumpió. Reintenta para recuperar el avance.",
                )
                self.save(run)
