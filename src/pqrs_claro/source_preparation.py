"""Resumable local lexical preparation; never changes originals or evidence status."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from .source_retrieval import TERMS_VERSION, terms_key, tokenize

logger = logging.getLogger(__name__)


def install(connection):
    # Triggers also cover imports/OCR applied by separate processes. Changes and
    # invalidation commit together, including deletes performed by case purge.
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS source_index_jobs (
            source_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 0,
            queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, started_at TEXT,
            completed_at TEXT, token TEXT, algorithm TEXT, payload TEXT,
            payload_hash TEXT, chunk_count INTEGER NOT NULL DEFAULT 0, error TEXT
        );
        CREATE INDEX IF NOT EXISTS source_index_pending
            ON source_index_jobs(status, priority DESC, queued_at, source_id);
        CREATE TRIGGER IF NOT EXISTS source_index_added AFTER INSERT ON sources BEGIN
            INSERT INTO source_index_jobs(source_id,priority) VALUES (NEW.id,1)
            ON CONFLICT(source_id) DO UPDATE SET revision=revision+1, status='queued',
                priority=1, queued_at=CURRENT_TIMESTAMP, token=NULL,
                payload=NULL, payload_hash=NULL, chunk_count=0, error=NULL;
        END;
        CREATE TRIGGER IF NOT EXISTS source_index_changed AFTER UPDATE ON sources BEGIN
            INSERT INTO source_index_jobs(source_id,priority) VALUES (NEW.id,1)
            ON CONFLICT(source_id) DO UPDATE SET revision=revision+1, status='queued',
                priority=1, queued_at=CURRENT_TIMESTAMP, token=NULL,
                payload=NULL, payload_hash=NULL, chunk_count=0, error=NULL;
        END;
        CREATE TRIGGER IF NOT EXISTS source_index_removed AFTER DELETE ON sources BEGIN
            DELETE FROM source_index_jobs WHERE source_id=OLD.id;
        END;
        INSERT OR IGNORE INTO source_index_jobs(source_id) SELECT id FROM sources;
    """)
    connection.execute(
        "UPDATE source_index_jobs SET status='queued', payload=NULL, payload_hash=NULL, "
        "chunk_count=0, token=NULL WHERE status IN ('ready','unreadable','error') "
        "AND COALESCE(algorithm,'')!=?", (TERMS_VERSION,))


def load_terms(library, chunks):
    """Only fetch selected sources; cached data never supplies citations or scope."""
    source_ids = sorted({c["source_id"] for c in chunks})
    result = {}
    try:
        with library.connect() as connection:
            for offset in range(0, len(source_ids), 200):
                batch = source_ids[offset:offset + 200]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "SELECT payload,payload_hash FROM source_index_jobs "
                    f"WHERE source_id IN ({placeholders}) AND status='ready' AND algorithm=?",
                    (*batch, TERMS_VERSION),
                )
                for payload, expected in rows:
                    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != expected:
                        continue
                    data = json.loads(payload)
                    if not isinstance(data, dict) or not all(
                        isinstance(key, str) and isinstance(counts, dict)
                        and all(isinstance(term, str) and type(count) is int and count > 0
                                for term, count in counts.items())
                        for key, counts in data.items()
                    ):
                        continue
                    result.update(data)
    except Exception:
        logger.warning("Índice preparado no disponible; se conserva el cálculo local.")
        return {}
    return result


@contextmanager
def worker_lock(path):
    """One background worker across processes; the OS releases the lock on exit."""
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


class SourcePreparation:
    def __init__(self, library):
        self.library = library
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="library-index", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def _loop(self):
        try:
            with worker_lock(self.library.db.with_suffix(".index.lock")) as acquired:
                if not acquired:
                    return
                # Only the lock owner may recover an interrupted worker's jobs.
                with self.library.connect() as connection:
                    connection.execute("UPDATE source_index_jobs SET status='queued', token=NULL "
                                       "WHERE status='preparing'")
                while not self.stop_event.is_set():
                    try:
                        worked = self.process_one()
                    except Exception:
                        logger.warning("Preparación del índice aplazada; se reintentará.")
                        worked = False
                    self.stop_event.wait(0.02 if worked else 2)
        except Exception:
            logger.warning("No se pudo iniciar el preparador local del índice.")

    def process_one(self):
        from .source_library import make_chunks

        token = uuid4().hex
        with self.library.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT j.source_id,j.revision,s.body,s.pages FROM source_index_jobs j "
                "JOIN sources s ON s.id=j.source_id WHERE j.status='queued' "
                "ORDER BY j.priority DESC,j.queued_at,j.source_id LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            source_id, revision, body, pages = row
            connection.execute("UPDATE source_index_jobs SET status='preparing', token=?, "
                               "started_at=CURRENT_TIMESTAMP WHERE source_id=?",
                               (token, source_id))
        status, error, counts, chunk_count = "ready", None, {}, 0
        try:
            source, pages = json.loads(body), json.loads(pages)
            if source.get("extraction_status", "ready") not in {"ready", "partial"}:
                status = "unreadable"
            else:
                for chunk in make_chunks(source, pages):
                    if self.stop_event.is_set():
                        status = "queued"
                        counts = {}
                        break
                    key = terms_key(chunk)
                    if key not in counts:
                        counts[key] = dict(Counter(tokenize(
                            f"{chunk.get('title', '')} {chunk['quote']}")))
                    chunk_count += 1
                if status == "ready" and not chunk_count:
                    status = "unreadable"
        except Exception as exc:
            status, error, counts, chunk_count = "error", type(exc).__name__, {}, 0
        payload = json.dumps(counts, ensure_ascii=False, separators=(",", ":"))
        with self.library.connect() as connection:
            # A newer OCR/title/version update or a deleted source wins over this job.
            connection.execute(
                "UPDATE source_index_jobs SET status=?,algorithm=?,payload=?,payload_hash=?, "
                "chunk_count=?,error=?,completed_at=?,token=NULL "
                "WHERE source_id=? AND revision=? AND token=? AND status='preparing'",
                (status, TERMS_VERSION, payload if status == "ready" else None,
                 hashlib.sha256(payload.encode("utf-8")).hexdigest() if status == "ready" else None,
                 chunk_count if status == "ready" else 0, error,
                 datetime.now(timezone.utc).isoformat() if status != "queued" else None,
                 source_id, revision, token),
            )
        return True

    def status(self):
        with self.library.connect() as connection:
            counts = dict(connection.execute(
                "SELECT status,count(*) FROM source_index_jobs GROUP BY status"))
            chunks = connection.execute(
                "SELECT COALESCE(sum(chunk_count),0) FROM source_index_jobs WHERE status='ready'"
            ).fetchone()[0]
        return {"algorithm": TERMS_VERSION, "total": sum(counts.values()),
                **{key: counts.get(key, 0) for key in
                   ("queued", "preparing", "ready", "unreadable", "error")},
                "prepared_chunks": chunks,
                "note": "Preparación local de texto; no aprueba fuentes ni vuelve a ejecutar OCR."}

    def retry_errors(self):
        with self.library.connect() as connection:
            connection.execute("UPDATE source_index_jobs SET status='queued',error=NULL, "
                               "priority=1,queued_at=CURRENT_TIMESTAMP WHERE status='error'")
        self.start()
        return self.status()
