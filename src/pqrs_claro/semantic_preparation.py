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
from .source_retrieval import _EVIDENCE_CATEGORIES, HISTORICAL_CATEGORIES
from .source_semantic import MODEL_FILE, MODEL_KEY, SemanticIndex, _load_model, _model_path

logger = logging.getLogger(__name__)

# Existential version of the retrieval scope: at least one case could search
# this source. A link belonging to a different owner cannot authorize it.
_SCOPE_STATE = f"""
    CASE
      WHEN json_extract(s.body,'$.category') NOT IN ({','.join('?' for _ in _EVIDENCE_CATEGORIES)})
        OR json_extract(s.body,'$.category') IS NULL
        OR json_extract(s.body,'$.validity')='superseded'
        OR NOT COALESCE(s.version=(SELECT max(v.version) FROM sources v
                                   WHERE v.document_id=s.document_id),0)
        THEN 'inactive'
      WHEN COALESCE(json_extract(s.body,'$.collection_id'),'')=''
        AND json_extract(s.body,'$.category') IN ({','.join('?' for _ in HISTORICAL_CATEGORIES)})
        THEN 'inactive'
      WHEN COALESCE(json_extract(s.body,'$.collection_id'),'')!='' AND NOT EXISTS (
        SELECT 1 FROM case_source_collections link
        WHERE link.collection_id=json_extract(s.body,'$.collection_id')
          AND (json_extract(s.body,'$.case_id') IS NULL
               OR link.case_id=json_extract(s.body,'$.case_id')))
        THEN 'inactive'
      WHEN json_type(s.body,'$.extraction_status') IS NOT NULL
        AND COALESCE(json_extract(s.body,'$.extraction_status'),'') NOT IN ('ready','partial')
        THEN 'unreadable'
      ELSE 'eligible'
    END"""
_SCOPE_PARAMS = (*sorted(_EVIDENCE_CATEGORIES), *sorted(HISTORICAL_CATEGORIES))
_QUEUE_REVISION = """
    INSERT INTO jobs(source_id,model_key,generation,revision,status,priority)
    VALUES (?,?,?,?,'queued',?)
    ON CONFLICT(source_id,model_key) DO UPDATE SET
        generation=excluded.generation,revision=excluded.revision,
        status=CASE WHEN jobs.generation=0 AND jobs.revision=excluded.revision
                         AND jobs.status='error'
                    THEN 'error' ELSE 'queued' END,
        priority=excluded.priority,prepared=0,total=0,error=CASE WHEN jobs.generation=0 AND
        jobs.revision=excluded.revision AND jobs.status='error' THEN jobs.error END,
        updated_at=CURRENT_TIMESTAMP
    WHERE (jobs.generation,jobs.revision)<(excluded.generation,excluded.revision)
       OR (jobs.status IN ('inactive','removed') AND
           (jobs.generation,jobs.revision)=(excluded.generation,excluded.revision))"""


class _JobStop:
    """Observe revocations between local ONNX batches, without interrupting one in flight."""

    def __init__(self, worker, source_id, version):
        self.worker, self.source_id, self.version = worker, source_id, version
        self.catalog_revision = None
        self.revoked = False

    def is_set(self):
        if self.worker.stop_event.is_set() or self.revoked:
            return True
        try:
            revision = self.worker.library.catalog_revision()
            if revision != self.catalog_revision:
                self.revoked = self.worker._source(self.source_id) != (*self.version, "eligible")
                self.catalog_revision = revision
        except sqlite3.OperationalError:
            # Missing a current scope check postpones work until the next claim.
            self.revoked = True
        return self.revoked


class SemanticPreparation:
    def __init__(self, library, cache_dir=None, *, model_factory=None, model_key=MODEL_KEY):
        self.library = library
        self.cache_dir = Path(cache_dir or library.db.parent / "semantic")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db = self.cache_dir / "preparation.sqlite"
        self.model_key = model_key
        self.model_factory = model_factory or (lambda path: _load_model(path, threads=1))
        self._injected_model = model_factory is not None
        self._catalog_revision = None
        self._priority_streak = 0
        self.model = None
        self.stop_event = threading.Event()
        self.thread = None
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (source_id TEXT, model_key TEXT, "
                         "revision INTEGER, status TEXT, prepared INTEGER DEFAULT 0, "
                         "total INTEGER DEFAULT 0, error TEXT, updated_at TEXT DEFAULT "
                         "CURRENT_TIMESTAMP, PRIMARY KEY(source_id,model_key))")
            conn.execute("CREATE INDEX IF NOT EXISTS pending_jobs ON jobs(model_key,status)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "priority" not in columns:
                # Jobs predating discovery were all requested by interactive runs.
                conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 1")
            if "generation" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN generation INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_by_priority ON jobs("
                         "model_key,status,priority,updated_at,source_id)")

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
                    "SELECT source_id,generation,revision FROM source_index_jobs "
                    "JOIN source_generations USING(source_id) "
                    f"WHERE source_id IN ({marks})",
                    batch).fetchall())
        with self.connect() as conn:
            conn.executemany(_QUEUE_REVISION, (
                (source_id, self.model_key, generation, revision, 1)
                for source_id, generation, revision in revisions))
            conn.executemany("UPDATE jobs SET priority=1 WHERE source_id=? AND model_key=? "
                             "AND generation=? AND revision=? AND status='queued' AND priority=0",
                             ((source_id, self.model_key, generation, revision)
                              for source_id, generation, revision in revisions))
        return len(revisions)

    def _model_available(self):
        if self._injected_model:
            return True
        folder = _model_path(self.cache_dir)
        required = (MODEL_FILE, "config.json", "tokenizer.json", "tokenizer_config.json",
                    "special_tokens_map.json")
        return all((folder / name).is_file() for name in required)

    def sync_catalog(self):
        """Discover changes without loading pages, originals or embeddings."""
        if not self._model_available():
            return
        with self.library.connect() as conn:
            conn.execute("BEGIN")
            current = conn.execute(
                "SELECT revision FROM source_catalog_revision WHERE id=1").fetchone()[0]
            if current == self._catalog_revision:
                return
            # A deletion may remove the greatest live generation.
            highest = conn.execute("SELECT COALESCE((SELECT seq FROM sqlite_sequence "
                                   "WHERE name='source_generations'),0)").fetchone()[0]
            rows = conn.execute(
                f"SELECT s.id,g.generation,j.revision,{_SCOPE_STATE} FROM sources s "
                "JOIN source_index_jobs j ON j.source_id=s.id JOIN source_generations g "
                "ON g.source_id=s.id", _SCOPE_PARAMS).fetchall()
        states = {source_id: (generation, revision, state)
                  for source_id, generation, revision, state in rows}
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(_QUEUE_REVISION, (
                (source_id, self.model_key, generation, revision, 0)
                for source_id, generation, revision, state in rows if state == "eligible"))
            # An unchanged, eligible failure remains terminal. Dropped or
            # revoked sources stop contributing even partial progress.
            tracked = conn.execute(
                "SELECT source_id,generation,revision,status FROM jobs WHERE model_key=?",
                (self.model_key,)).fetchall()
            for source_id, generation, revision, status in tracked:
                prior = generation, revision
                snapshot = states.get(source_id)
                if snapshot is None:
                    if generation > highest:
                        continue
                    state = "removed"
                else:
                    if (generation, revision) > snapshot[:2]:
                        continue
                    generation, revision, state = snapshot
                if state != "eligible" and (status != state or prior != (generation, revision)):
                    conn.execute("UPDATE jobs SET status=?,prepared=0,total=0,error=NULL,"
                                 "generation=?,revision=? WHERE source_id=? AND model_key=?",
                                 (state, generation, revision, source_id, self.model_key))
        self._catalog_revision = current

    def _model(self, path):
        if self.model is None:
            self.model = self.model_factory(path)
        return self.model

    def _source(self, source_id, *, load_pages=False):
        with self.library.connect() as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                f"SELECT g.generation,j.revision,{_SCOPE_STATE} FROM source_index_jobs j "
                "JOIN sources s ON s.id=j.source_id "
                "JOIN source_generations g ON g.source_id=s.id WHERE s.id=?",
                (*_SCOPE_PARAMS, source_id)).fetchone()
            if load_pages and row and row[2] == "eligible":
                return (*row, *conn.execute("SELECT body,pages FROM sources WHERE id=?",
                                            (source_id,)).fetchone())
            return row

    def _save(self, source_id, version, status, progress, error=None):
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET status=?,prepared=?,total=?,error=?, "
                         "updated_at=CURRENT_TIMESTAMP WHERE source_id=? AND model_key=? "
                         "AND generation=? AND revision=?", (status, progress.get("prepared", 0),
                         progress.get("total", 0), error, source_id, self.model_key, *version))

    def process_one(self):
        if not self._model_available():
            return False
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Prefer interactive misses; regularly yield a turn to catalog work
            # even if queries keep adding new high-priority documents.
            preferred = 0 if self._priority_streak >= 4 else 1
            for priority in (preferred, 1 - preferred):
                job = conn.execute(
                    "SELECT source_id,generation,revision FROM jobs WHERE model_key=? "
                    "AND status='queued' AND priority=? ORDER BY updated_at,source_id LIMIT 1",
                    (self.model_key, priority)).fetchone()
                if job:
                    break
            if not job:
                return False
            source_id, generation, revision = job
            conn.execute("UPDATE jobs SET status='preparing' WHERE source_id=? AND model_key=?",
                         (source_id, self.model_key))
        self._priority_streak = min(4, self._priority_streak + 1) if priority else 0
        try:
            return self._prepare_job(source_id, (generation, revision))
        except Exception:
            # A transient database failure after claiming a job must not strand
            # it until the next restart. Model/encoding errors are saved below.
            with self.connect() as conn:
                conn.execute("UPDATE jobs SET status='queued' WHERE source_id=? AND model_key=? "
                             "AND generation=? AND revision=? AND status='preparing'",
                             (source_id, self.model_key, generation, revision))
            raise

    def _prepare_job(self, source_id, version):
        source_row = self._source(source_id, load_pages=True)
        if not source_row:
            self._save(source_id, version, "removed", {})
            return True
        current_version, state = source_row[:2], source_row[2]
        if state != "eligible":
            self._save(source_id, version, state, {})
            return True
        if current_version != version:
            self.enqueue([{"id": source_id}])
            return True
        progress = {}
        try:
            body, pages = source_row[3:]
            source = json.loads(body)
            chunks = make_chunks(source, json.loads(pages))
            if not chunks:
                self._save(source_id, version, "unreadable", progress)
                return True
            index = SemanticIndex(self.cache_dir, model_factory=self._model,
                                  model_key=self.model_key, threads=1, matrix_cache_bytes=0,
                                  stop_event=_JobStop(self, source_id, version))
            last_saved = 0.0

            def report(value):
                nonlocal last_saved, progress
                progress = value
                if time.monotonic() - last_saved >= 2:
                    self._save(source_id, version, "preparing", value)
                    last_saved = time.monotonic()

            ready = index.prepare(chunks, progress=report)
            status = "ready" if ready else "queued" if index.diagnostics["cancelled"] else "error"
            progress = index.diagnostics
            error = index.warning
        except Exception as exc:
            status, error = "error", type(exc).__name__
        # Una actualización o eliminación durante ONNX no se promueve como preparada.
        current = self._source(source_id)
        if current is None:
            self._save(source_id, version, "removed", {})
        elif current[2] != "eligible":
            self._save(source_id, version, current[2], {})
        elif current[:2] != version:
            self.enqueue([{"id": source_id}])
        else:
            self._save(source_id, version, status, progress, error)
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
                        self.sync_catalog()
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
                "WHERE model_key=? AND status NOT IN ('removed','unreadable','inactive')",
                (self.model_key,)).fetchone()
        return {"model": self.model_key, "documents": counts,
                "prepared_fragments": prepared, "known_fragments": total,
                "note": "Caché semántica por documento; no constituye una búsqueda ni aprobación."}
