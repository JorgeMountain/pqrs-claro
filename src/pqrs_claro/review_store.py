"""Revisiones optimistas, historial y aprobaciones inmutables en SQLite."""

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from .storage import Conflict, now


class ReviewStore:
    def __init__(self, data_dir):
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "revisiones.sqlite"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS review_requests (
                    case_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(case_id, request_id));
                CREATE TABLE IF NOT EXISTS review_history (
                    case_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(case_id, request_id, revision));
                CREATE TABLE IF NOT EXISTS review_approvals (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, body TEXT NOT NULL);
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

    def get(self, case_id, request_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body FROM review_requests WHERE case_id=? AND request_id=?",
                (case_id, request_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, case_id=None):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM review_requests" + (" WHERE case_id=?" if case_id else ""),
                (case_id,) if case_id else (),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save(self, value, *, expected, event, actor=None, snapshot=None):
        """CAS y snapshot se confirman juntos; el historial nunca se sobrescribe."""
        row = deepcopy(value)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT revision FROM review_requests WHERE case_id=? AND request_id=?",
                (row["case_id"], row["request_id"]),
            ).fetchone()
            revision = previous[0] if previous else 0
            if expected != revision:
                raise Conflict("La revisión cambió en otra ventana. Recarga antes de guardar.")
            row.update(revision=revision + 1, updated_at=now())
            encoded = json.dumps(row, ensure_ascii=False)
            conn.execute(
                "INSERT INTO review_requests VALUES (?,?,?,?) "
                "ON CONFLICT(case_id,request_id) DO UPDATE SET "
                "revision=excluded.revision,body=excluded.body",
                (row["case_id"], row["request_id"], row["revision"], encoded),
            )
            history = dict(
                event=event,
                actor=actor,
                created_at=row["updated_at"],
                revision=row["revision"],
                body=row,
            )
            conn.execute(
                "INSERT INTO review_history VALUES (?,?,?,?)",
                (
                    row["case_id"],
                    row["request_id"],
                    row["revision"],
                    json.dumps(history, ensure_ascii=False),
                ),
            )
            if snapshot is not None:
                conn.execute(
                    "INSERT INTO review_approvals VALUES (?,?,?,?)",
                    (
                        snapshot["id"],
                        row["case_id"],
                        row["request_id"],
                        json.dumps(snapshot, ensure_ascii=False),
                    ),
                )
        return row

    def history(self, case_id, request_id):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM review_history WHERE case_id=? AND request_id=? "
                "ORDER BY revision DESC LIMIT 100",
                (case_id, request_id),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def approval(self, approval_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body FROM review_approvals WHERE id=?",
                (approval_id,),
            ).fetchone()
        if not row:
            raise KeyError("No se encontró la versión aprobada.")
        return json.loads(row[0])

    def recover(self):
        for row in self.list():
            if row["status"] == "checking":
                row.update(
                    status="error",
                    assessment=None,
                    approval=None,
                    error="La comprobación se interrumpió. "
                    "Puedes reintentarlo; tu texto se conservó.",
                )
                self.save(row, expected=row["revision"], event="interrupted")
