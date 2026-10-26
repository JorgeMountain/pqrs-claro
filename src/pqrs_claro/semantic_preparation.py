"""Completa la caché semántica por documento sin bloquear una consulta activa."""

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .source_library import make_chunks
from .source_preparation import worker_lock
from .source_semantic import MODEL_KEY, SemanticIndex, _load_model

logger = logging.getLogger(__name__)


class SemanticPreparation:
    def __init__(self, library, cache_dir=None, *, model_factory=None, model_key=MODEL_KEY):
        self.library = library
        self.cache_dir = Path(cache_dir or library.db.parent / "semantic")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db = self.cache_dir / "preparation.sqlite"
        self.model_key = model_key
        self.model_factory = model_factory or (lambda path: _load_model(path, threads=1))
        self.model = None
        self.stop_event = threading.Event()
        self.thread = None
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (source_id TEXT, model_key TEXT, "
                         "revision INTEGER, status TEXT, prepared INTEGER DEFAULT 0, "
                         "total INTEGER DEFAULT 0, error TEXT, updated_at TEXT DEFAULT "
                         "CURRENT_TIMESTAMP, PRIMARY KEY(source_id,model_key))")
            conn.execute("CREATE INDEX IF NOT EXISTS pending_jobs ON jobs(model_key,status)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def enqueue(self, snapshot):
        """Sólo se admiten fuentes del alcance de la consulta que llamó al servicio."""
        ids = sorted({source["id"] for source in snapshot})
        revisions = []
        with self.library.connect() as conn:
            for offset in range(0, len(ids), 200):
                batch = ids[offset:offset + 200]
                marks = ",".join("?" for _ in batch)
                revisions.extend(conn.execute(
                    "SELECT source_id,revision FROM source_index_jobs "
                    f"WHERE source_id IN ({marks})",
                    batch).fetchall())
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO jobs(source_id,model_key,revision,status) VALUES (?,?,?,'queued') "
                "ON CONFLICT(source_id,model_key) DO UPDATE SET revision=excluded.revision, "
                "status='queued',prepared=0,total=0,error=NULL,updated_at=CURRENT_TIMESTAMP "
                "WHERE jobs.revision!=excluded.revision",
                ((source_id, self.model_key, revision) for source_id, revision in revisions))
        return len(revisions)

    def _model(self, path):
        if self.model is None:
            self.model = self.model_factory(path)
        return self.model

    def _source(self, source_id):
        with self.library.connect() as conn:
            return conn.execute(
                "SELECT j.revision,s.body,s.pages FROM source_index_jobs j "
                "JOIN sources s ON s.id=j.source_id WHERE s.id=?", (source_id,)).fetchone()

    def _save(self, source_id, revision, status, progress, error=None):
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET status=?,prepared=?,total=?,error=?, "
                         "updated_at=CURRENT_TIMESTAMP WHERE source_id=? AND model_key=? "
                         "AND revision=?", (status, progress.get("prepared", 0),
                         progress.get("total", 0), error, source_id, self.model_key, revision))

    def process_one(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute("SELECT source_id,revision FROM jobs WHERE model_key=? "
                               "AND status='queued' ORDER BY updated_at,source_id LIMIT 1",
                               (self.model_key,)).fetchone()
            if not job:
                return False
            source_id, revision = job
            conn.execute("UPDATE jobs SET status='preparing' WHERE source_id=? AND model_key=?",
                         (source_id, self.model_key))
        source_row = self._source(source_id)
        if not source_row:
            self._save(source_id, revision, "removed", {})
            return True
        current_revision, body, pages = source_row
        if current_revision != revision:
            self.enqueue([{"id": source_id}])
            return True
        progress = {}
        try:
            source = json.loads(body)
            if source.get("extraction_status", "ready") not in {"ready", "partial"}:
                self._save(source_id, revision, "unreadable", progress)
                return True
            chunks = make_chunks(source, json.loads(pages))
            if not chunks:
                self._save(source_id, revision, "unreadable", progress)
                return True
            index = SemanticIndex(self.cache_dir, model_factory=self._model,
                                  model_key=self.model_key, threads=1,
                                  stop_event=self.stop_event, matrix_cache_bytes=0)
            last_saved = 0.0

            def report(value):
                nonlocal last_saved, progress
                progress = value
                if time.monotonic() - last_saved >= 2:
                    self._save(source_id, revision, "preparing", value)
                    last_saved = time.monotonic()

            ready = index.prepare(chunks, progress=report)
            status = "ready" if ready else "queued" if self.stop_event.is_set() else "error"
            self._save(source_id, revision, status, index.diagnostics, index.warning)
        except Exception as exc:
            self._save(source_id, revision, "error", progress, type(exc).__name__)
        # Una actualización o eliminación durante ONNX no se promueve como preparada.
        current = self._source(source_id)
        if current is None:
            self._save(source_id, revision, "removed", {})
        elif current[0] != revision:
            self.enqueue([{"id": source_id}])
        return True

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="semantic-backfill", daemon=True)
        self.thread.start()

    def _loop(self):
        try:
            with worker_lock(self.db.with_suffix(".lock")) as acquired:
                if not acquired:
                    return
                with self.connect() as conn:
                    conn.execute("UPDATE jobs SET status='queued' WHERE status='preparing' "
                                 "AND model_key=?", (self.model_key,))
                while not self.stop_event.is_set():
                    try:
                        worked = self.process_one()
                    except Exception:
                        logger.warning("Preparación semántica aplazada; se reintentará.")
                        worked = False
                    self.stop_event.wait(0.1 if worked else 2)
        except Exception:
            logger.warning("No se pudo iniciar la preparación semántica en segundo plano.")

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def status(self):
        with self.connect() as conn:
            counts = dict(conn.execute("SELECT status,COUNT(*) FROM jobs WHERE model_key=? "
                                       "GROUP BY status", (self.model_key,)))
            prepared, total = conn.execute(
                "SELECT COALESCE(SUM(prepared),0),COALESCE(SUM(total),0) FROM jobs "
                "WHERE model_key=? AND status NOT IN ('removed','unreadable')",
                (self.model_key,)).fetchone()
        return {"model": self.model_key, "documents": counts,
                "prepared_fragments": prepared, "known_fragments": total,
                "note": "Caché semántica por documento; no constituye una búsqueda ni aprobación."}
