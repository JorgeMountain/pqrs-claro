"""Expedientes y revisiones en SQLite, separados de los checkpoints de LangGraph."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def write_original(path, data):
    """Confirma los bytes en disco antes de registrar su existencia en SQLite."""
    with path.open("wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


class Conflict(ValueError):
    """Otra operación cambió la versión del expediente."""


class CaseStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "expedientes.sqlite"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    case_id TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY (case_id, version));
                CREATE TABLE IF NOT EXISTS case_lifecycle (
                    case_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    deleted_at TEXT);
                CREATE TABLE IF NOT EXISTS case_lifecycle_events (
                    case_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    action TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (case_id, revision));
                CREATE TABLE IF NOT EXISTS case_purges (
                    case_id TEXT PRIMARY KEY, started_at TEXT NOT NULL);
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

    def create(self, filename: str, pdf: bytes, *, case_id=None, origin=None, receipt=None):
        case_id = case_id or uuid4().hex
        folder = self.root / "files" / case_id
        folder.mkdir(parents=True, exist_ok=True)
        write_original(folder / "original.pdf", pdf)

        case = dict(
            id=case_id,
            filename=filename,
            status="uploaded",
            created_at=now(),
            received_at=None,
            version=1,
            pages=[],
            identification=None,
            error=None,
            events=[],
            mode="real",
            sha256=hashlib.sha256(pdf).hexdigest(),
            confirmed_at=None,
            request_count=0,
        )
        case["events"].append(
            dict(stage="uploaded", message="Original conservado.", created_at=now())
        )
        if origin is not None:
            case["origin"] = origin
        if receipt is not None:
            case["receipt"] = receipt
        with self.connect() as conn:
            conn.execute("INSERT INTO cases VALUES (?,?,?)", (case_id, 1, json.dumps(case)))
        return case

    def get(self, case_id, *, include_deleted=False):
        with self.connect() as conn:
            row = conn.execute("SELECT body FROM cases WHERE id=?", (case_id,)).fetchone()
            lifecycle = conn.execute(
                "SELECT deleted_at FROM case_lifecycle WHERE case_id=?", (case_id,)
            ).fetchone()
        if not row:
            raise KeyError("No se encontró el expediente.")
        if not include_deleted and lifecycle and lifecycle[0]:
            raise Conflict("Este expediente está en la papelera. Restáuralo para continuar.")
        return json.loads(row[0])

    def list(self, *, deleted=False):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT c.body, COALESCE(l.revision,0), l.deleted_at FROM cases c "
                "LEFT JOIN case_lifecycle l ON l.case_id=c.id "
                "WHERE (l.deleted_at IS NOT NULL)=? ORDER BY c.rowid DESC", (deleted,)
            ).fetchall()
        keys = ("id", "filename", "status", "created_at", "request_count", "version")
        result = []
        for raw, revision, deleted_at in rows:
            body = json.loads(raw)
            origin = body.get("origin") or {}
            result.append({**{key: body[key] for key in keys},
                           "subject": (body.get("identification") or {}).get("subject")
                           or origin.get("subject") or "",
                           "origin_kind": origin.get("kind", "pdf"),
                           "case_number": origin.get("reported_case_number", ""),
                           "lifecycle_revision": revision, "deleted_at": deleted_at})
        return result

    def set_deleted(self, case_id, *, version, lifecycle_revision, deleted):
        """Soft deletion preserves content versions, approvals and all original files."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            case = conn.execute("SELECT version FROM cases WHERE id=?", (case_id,)).fetchone()
            if not case:
                raise KeyError(case_id)
            row = conn.execute(
                "SELECT revision,deleted_at FROM case_lifecycle WHERE case_id=?", (case_id,)
            ).fetchone()
            if conn.execute("SELECT 1 FROM case_purges WHERE case_id=?", (case_id,)).fetchone():
                raise Conflict("El borrado definitivo está iniciado. "
                               "Reintenta eliminarlo desde la papelera.")
            revision, deleted_at = row or (0, None)
            if version != case[0] or lifecycle_revision != revision:
                raise Conflict("El expediente cambió. Actualiza la lista y vuelve a intentarlo.")
            if bool(deleted_at) == deleted:
                raise Conflict("El expediente ya está en ese estado. Actualiza la lista.")
            timestamp = now()
            conn.execute(
                "INSERT OR REPLACE INTO case_lifecycle VALUES (?,?,?)",
                (case_id, revision + 1, timestamp if deleted else None),
            )
            conn.execute("INSERT INTO case_lifecycle_events VALUES (?,?,?,?)",
                         (case_id, revision + 1, "deleted" if deleted else "restored", timestamp))
        return {"id": case_id, "deleted": deleted, "lifecycle_revision": revision + 1}

    def update(self, case_id, *, expected=None, event=None, **changes):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT version,body FROM cases WHERE id=?", (case_id,)).fetchone()
            if not row:
                raise KeyError("No se encontró el expediente.")
            lifecycle = conn.execute(
                "SELECT deleted_at FROM case_lifecycle WHERE case_id=?", (case_id,)
            ).fetchone()
            if lifecycle and lifecycle[0]:
                raise Conflict("Restaura el expediente desde la papelera antes de modificarlo.")
            version, body = row
            if expected is not None and expected != version:
                raise Conflict("El expediente cambió en otra ventana. Recargue antes de guardar.")
            case = json.loads(body)
            if "identification" in changes and case.get("identification"):
                conn.execute(
                    "INSERT OR IGNORE INTO revisions VALUES (?,?,?)",
                    (case_id, version, json.dumps(case["identification"])),
                )
            case.update(changes)
            case["version"] = version + 1
            case["request_count"] = len((case.get("identification") or {}).get("requests", []))
            if event:
                case["events"].append(dict(stage=case["status"], message=event, created_at=now()))
            conn.execute(
                "UPDATE cases SET version=?,body=? WHERE id=?",
                (case["version"], json.dumps(case), case_id),
            )
        return case

    def original(self, case_id):
        case = self.get(case_id)  # Solo IDs existentes pueden convertirse en rutas.
        path = self.root / "files" / case_id / "original.pdf"
        if not path.is_file():
            raise ValueError(
                "Falta el PDF original en este equipo. Restaura su copia antes de continuar."
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["sha256"]:
            raise ValueError(
                "El PDF original cambió en disco. Restaura la copia original antes de continuar."
            )
        return path

    def recover_interrupted(self):
        for case in self.list():
            if case["status"] in {"reading", "identifying", "confirming"}:
                self.update(
                    case["id"],
                    status="error",
                    error="El proceso se interrumpió. Puede continuar desde el avance guardado.",
                    event="Interrupción detectada al iniciar; avance conservado.",
                )
