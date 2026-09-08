"""Versiones de oficio y estados durables; nunca sobrescribe versiones anteriores."""

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from .storage import Conflict, now


class OfficeStore:
    def __init__(self, data_dir):
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "oficios.sqlite"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS office_runs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS office_runs_case ON office_runs(case_id);
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

    def create(self, run):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO office_runs VALUES (?,?,?)",
                (run["id"], run["case_id"], json.dumps(run, ensure_ascii=False)),
            )
        return deepcopy(run)

    def get(self, case_id, run_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body FROM office_runs WHERE id=? AND case_id=?", (run_id, case_id)
            ).fetchone()
        if not row:
            raise KeyError("No se encontró el oficio en este expediente.")
        return json.loads(row[0])

    def list(self, case_id=None, *, limit=20):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM office_runs"
                + (" WHERE case_id=?" if case_id else "")
                + " ORDER BY rowid DESC LIMIT ?",
                (case_id, limit) if case_id else (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, case_id, run_id, *, expected_status=None, **changes):
        allowed = {
            "status",
            "stale",
            "completed_at",
            "error",
            "files",
            "page_count",
            "verification",
            "converter",
            "_manifest_sha256",
        }
        if set(changes) - allowed:
            raise ValueError("Los datos de una versión de oficio son inmutables.")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT body FROM office_runs WHERE id=? AND case_id=?", (run_id, case_id)
            ).fetchone()
            if not row:
                raise KeyError("No se encontró el oficio.")
            run = json.loads(row[0])
            if expected_status is not None and run["status"] != expected_status:
                raise Conflict("El estado de este oficio cambió antes de guardar el resultado.")
            run.update(changes)
            conn.execute(
                "UPDATE office_runs SET body=? WHERE id=? AND case_id=?",
                (json.dumps(run, ensure_ascii=False), run_id, case_id),
            )
        return run

    def matching_input(self, case_id, fingerprint):
        """El reuso no depende del límite de 20 entradas visibles en la interfaz."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM office_runs WHERE case_id=? "
                "AND json_extract(body, '$.input_hash')=? ORDER BY rowid DESC",
                (case_id, fingerprint),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def recover(self):
        for run in self.list(limit=1_000_000):
            if run["status"] == "generating":
                self.update(
                    run["case_id"],
                    run["id"],
                    expected_status="generating",
                    status="failed",
                    completed_at=now(),
                    error="La generación se interrumpió. Puedes crear de nuevo esta versión.",
                )
