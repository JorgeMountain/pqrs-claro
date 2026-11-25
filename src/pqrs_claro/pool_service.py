"""Trámites FIAGA ligados a peticiones, con un solo turno activo por expediente."""

import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .extraction import PDFExtractor
from .image_ocr import IMAGE_FORMATS
from .office_models import xml_text
from .pool_document import office_layouts
from .pool_text import reply_text
from .source_library import MAX_SOURCE_BYTES, read_source
from .storage import Conflict, now


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _admin(actor):
    if actor != "admin":
        raise Conflict("La revisión del borrador corresponde al administrador.")


def _manager(db, actor):
    if actor == "admin" or not db.execute(
        "SELECT 1 FROM managers WHERE id=?", (actor,)
    ).fetchone():
        raise ValueError("Selecciona un tramitador registrado.")


def _current_task(state):
    return next((t for t in state["tasks"] if t["status"] in {"available", "claimed"}), None)


def _turn(state, actor, task_id, expected_status):
    task = _current_task(state)
    if state["stage"] != "pool" or not task or task["id"] != task_id:
        raise Conflict("Este trámite todavía no tiene el turno o ya se completó.")
    if task["status"] != expected_status:
        raise Conflict("El trámite cambió de estado. Actualiza la bolsa.")
    if task["manager_id"] and task["manager_id"] != actor:
        raise Conflict("Este turno está habilitado para el tramitador designado.")
    if expected_status == "claimed" and task["owner_id"] != actor:
        raise Conflict("Solo quien tomó el turno puede entregar su aporte.")
    return task


def _event(state, action, actor_id=None, **details):
    state["events"].append(dict(action=action, actor_id=actor_id, created_at=now(), **details))


def _has_gap(request):
    return bool(request.get("gaps") or (request.get("gap") or "").strip())


class PoolService:
    def __init__(self, store, pdf_extractor=None, *, library=None):
        self.store = store
        self.pdf_extractor = pdf_extractor or PDFExtractor()
        self.library = library
        self.on_initial = None
        self.on_integration = None
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS case_pool (
                    case_id TEXT PRIMARY KEY, stage TEXT NOT NULL, revision INTEGER NOT NULL,
                    body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS case_pool_files (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, filename TEXT NOT NULL,
                    original BLOB NOT NULL, extracted TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS case_pool_files_by_case ON case_pool_files(case_id);
                CREATE TABLE IF NOT EXISTS case_pool_progress (
                    case_id TEXT PRIMARY KEY, worker TEXT, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS case_pool_work_results (
                    case_id TEXT NOT NULL, step TEXT NOT NULL, request_id TEXT NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(case_id,step,request_id));
                CREATE TABLE IF NOT EXISTS case_pool_previous_review (
                    case_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS delete_pool_previous_review
                AFTER DELETE ON case_pool BEGIN
                    DELETE FROM case_pool_previous_review WHERE case_id=OLD.case_id;
                END;
                CREATE TRIGGER IF NOT EXISTS delete_pool_work_results
                AFTER DELETE ON case_pool_progress BEGIN
                    DELETE FROM case_pool_work_results WHERE case_id=OLD.case_id;
                END;
                CREATE TRIGGER IF NOT EXISTS delete_pool_progress AFTER DELETE ON case_pool BEGIN
                    DELETE FROM case_pool_progress WHERE case_id=OLD.case_id;
                END;
                CREATE TRIGGER IF NOT EXISTS delete_case_pool AFTER DELETE ON cases BEGIN
                    DELETE FROM case_pool_files WHERE case_id=OLD.id;
                    DELETE FROM case_pool WHERE case_id=OLD.id;
                END;
            """)

    @staticmethod
    def _case(db, case_id):
        row = db.execute(
            """SELECT json_extract(c.body,'$.filename'),
                COALESCE(NULLIF(json_extract(c.body,'$.receipt.subject'),''),
                         json_extract(c.body,'$.origin.subject')),
                COALESCE(NULLIF(json_extract(c.body,'$.receipt.reference'),''),
                         json_extract(c.body,'$.origin.reported_case_number')),
                json_extract(c.body,'$.receipt.workflow'),
                l.deleted_at, json_extract(c.body,'$.origin.kind'),
                json_extract(c.body,'$.origin.subject'), json_extract(c.body,'$.origin.sender'),
                json_extract(c.body,'$.origin.primary'), json_extract(c.body,'$.receipt.channel')
                FROM cases c LEFT JOIN case_lifecycle l ON l.case_id=c.id
                WHERE c.id=?""", (case_id,)
        ).fetchone()
        if not row:
            raise KeyError("No se encontró el expediente.")
        if row[4]:
            raise Conflict("El expediente está en la papelera.")
        return dict(filename=row[0], subject=row[1] or "", case_number=row[2] or "",
                    workflow=row[3], origin=dict(kind=row[5] or "pdf", subject=row[6],
                                                 sender=row[7], primary=row[8]),
                    receipt=dict(channel=row[9]))

    @staticmethod
    def _stored(db, case_id):
        row = db.execute("SELECT body FROM case_pool WHERE case_id=?", (case_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def exists(self, case_id):
        with self.store.connect() as db:
            return bool(db.execute(
                "SELECT 1 FROM case_pool WHERE case_id=?", (case_id,)
            ).fetchone())

    def enroll(self, case_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case = self._case(db, case_id)
            if case["workflow"] != "fiaga":
                raise Conflict("Este expediente conserva su recorrido de gestión original.")
            if not self._stored(db, case_id):
                state = dict(case_id=case_id, stage="admin_review", revision=1, round=0,
                             initial_draft="", snapshot={}, tasks=[], events=[], error=None,
                             approved_at=None)
                _event(state, "enrolled")
                db.execute("INSERT INTO case_pool VALUES (?,?,?,?)",
                           (case_id, state["stage"], 1, _dump(state)))
        return self.get(case_id)

    @contextmanager
    def _change(self, case_id, revision, *stages):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._case(db, case_id)
            state = self._stored(db, case_id)
            if not state or state["stage"] not in stages or state["revision"] != revision:
                raise Conflict("El expediente cambió. Actualiza la pantalla antes de continuar.")
            yield db, state
            state["revision"] += 1
            db.execute("UPDATE case_pool SET stage=?,revision=?,body=? WHERE case_id=?",
                       (state["stage"], state["revision"], _dump(state), case_id))

    def _working_snapshot(self, db, case_id):
        # Save each completed output once. Frequent progress updates need only write statuses.
        outputs = {(step, rid): json.loads(body) for step, rid, body in db.execute(
            "SELECT step, request_id, body FROM case_pool_work_results WHERE case_id=?", (case_id,)
        )}
        snapshot = dict(outputs.get(("identification", ""), {}))
        snapshot["checks"] = outputs.get(("checks", ""), {})
        snapshot["reading"] = outputs.get(("reading", ""), {})
        # Findings, summaries and generated answers can all quote a withdrawn collection.
        # Keep the petition and its original references available independently.
        scope = outputs.get(("library", ""), {}).get("allowed_collection_ids")
        if scope is None:
            snapshot["scope_revoked"] = any(step in {"sources", "drafting"} for step, _ in outputs)
        else:
            snapshot["scope_revoked"] = bool(
                scope and (self.library is None or self.library.scope_revoked(case_id, scope)))
        if snapshot["scope_revoked"]:
            return snapshot
        for request in snapshot.get("requests", []):
            for step in ("sources", "drafting"):
                request.update(outputs.get((step, request["id"]), {}))
        return snapshot

    def get(self, case_id):
        with self.store.connect() as db:
            db.execute("BEGIN")
            case = self._case(db, case_id)
            state = self._stored(db, case_id)
            progress = db.execute("SELECT body FROM case_pool_progress WHERE case_id=?",
                                  (case_id,)).fetchone()
            snapshot = state.pop("snapshot") if state else {}
            if state and state["stage"] == "preparing":
                snapshot = self._working_snapshot(db, case_id)
        if not state:
            return dict(**case, case_id=case_id, stage="legacy", revision=0, progress=None)
        case["subject"] = case["subject"] or snapshot.get("subject", "")
        state.setdefault("review_imported", False)
        state.setdefault("previous_draft", "")
        return dict(**state, **case, draft=snapshot.get("text", ""),
                    office_layouts=office_layouts(snapshot, state, self.store.root),
                    progress=json.loads(progress[0]) if progress else None,
                    requests=snapshot.get("requests", []), checks=snapshot.get("checks", {}),
                    reading=snapshot.get("reading", {}),
                    scope_revoked=snapshot.get("scope_revoked", False),
                    identification_warnings=snapshot.get("identification_warnings", []),
                    document_url=(f"/api/cases/{case_id}/pool/document.docx"
                                  if state["stage"] == "approved" else None))

    def record_progress(self, case_id, stage, revision, worker, progress, *, begin, output=None):
        body = _dump(dict(**progress, updated_at=now()))
        with self.store.connect() as db:
            if begin:
                result = db.execute("""
                    INSERT INTO case_pool_progress (case_id,worker,body)
                    SELECT case_id,?,? FROM case_pool WHERE case_id=? AND stage=? AND revision=?
                    ON CONFLICT(case_id) DO UPDATE SET worker=excluded.worker,body=excluded.body
                    """, (worker, body, case_id, stage, revision))
            else:
                result = db.execute("UPDATE case_pool_progress SET body=? "
                                    "WHERE case_id=? AND worker=?", (body, case_id, worker))
            if not result.rowcount:
                raise Conflict("El avance ya corresponde a otra ejecución.")
            if begin:
                db.execute("DELETE FROM case_pool_work_results WHERE case_id=?", (case_id,))
            if output is not None:
                name, request_id, value = output
                db.execute("INSERT INTO case_pool_work_results VALUES (?,?,?,?) "
                           "ON CONFLICT(case_id,step,request_id) DO UPDATE SET body=excluded.body",
                           (case_id, name, request_id, _dump(value)))

    @staticmethod
    def _finish_progress(db, case_id, worker, status):
        result = db.execute("""
            UPDATE case_pool_progress SET worker=NULL,
                body=json_set(body,'$.status',?,'$.updated_at',?)
            WHERE case_id=? AND (? IS NULL OR worker=?)""",
            (status, now(), case_id, worker, worker))
        if worker and not result.rowcount:
            raise Conflict("Otra ejecución está a cargo del borrador.")

    def list(self):
        # Avoid loading case PDFs, entire drafts or old contributions to poll the inbox.
        with self.store.connect() as db:
            rows = db.execute("""
                SELECT p.case_id,p.revision,p.stage,json_extract(c.body,'$.filename'),
                    COALESCE(NULLIF(json_extract(c.body,'$.receipt.subject'),''),
                             NULLIF(json_extract(c.body,'$.origin.subject'),''),
                             json_extract(p.body,'$.snapshot.subject')),
                    COALESCE(NULLIF(json_extract(c.body,'$.receipt.reference'),''),
                             json_extract(c.body,'$.origin.reported_case_number')),
                    json_extract(p.body,'$.error'),(
                        SELECT value FROM json_each(p.body,'$.tasks')
                        WHERE json_extract(value,'$.status') IN ('available','claimed') LIMIT 1)
                FROM case_pool p JOIN cases c ON c.id=p.case_id
                LEFT JOIN case_lifecycle l ON l.case_id=c.id WHERE l.deleted_at IS NULL
                ORDER BY c.rowid DESC""").fetchall()
        return [dict(case_id=r[0], id=r[0], revision=r[1], stage=r[2], filename=r[3],
                     subject=r[4] or "", case_number=r[5] or "", error=r[6],
                     task=json.loads(r[7]) if r[7] else None) for r in rows]

    def unenrolled_receipts(self):
        """Recepciones cuyo proceso se interrumpió antes de inscribir el expediente."""
        with self.store.connect() as db:
            missing = db.execute("""
                SELECT c.id FROM cases c LEFT JOIN case_pool p ON p.case_id=c.id
                LEFT JOIN case_lifecycle l ON l.case_id=c.id
                WHERE p.case_id IS NULL AND l.deleted_at IS NULL
                AND json_extract(c.body,'$.receipt.workflow')='fiaga'""").fetchall()
        return [case_id for (case_id,) in missing]

    def pending_jobs(self):
        with self.store.connect() as db:
            rows = db.execute("""
                SELECT p.case_id,p.stage,p.revision,json_extract(p.body,'$.error')
                FROM case_pool p LEFT JOIN case_lifecycle l ON l.case_id=p.case_id
                WHERE l.deleted_at IS NULL AND p.stage IN ('preparing','integration')""").fetchall()
        return [dict(case_id=r[0], stage=r[1], revision=r[2], error=r[3]) for r in rows]

    def recover_orphaned_progress(self, active_case_ids=()):
        """Marca como interrumpido cualquier progreso 'running' sin trabajador activo."""
        keep = set(active_case_ids)
        with self.store.connect() as db:
            rows = db.execute("""
                SELECT case_id FROM case_pool_progress
                WHERE json_extract(body,'$.status')='running'""").fetchall()
            for (case_id,) in rows:
                if case_id not in keep:
                    self._finish_progress(db, case_id, None, "interrupted")

    def _save_snapshot(self, case_id, snapshot, revision, stage, worker):
        with self._change(case_id, revision, stage) as (db, state):
            requests = snapshot.get("requests") or []
            ids = [r["id"] for r in requests]
            if not (snapshot.get("text") or "").strip() or not ids or len(set(ids)) != len(ids):
                raise ValueError("El borrador necesita texto y peticiones identificadas.")
            if stage == "preparing":
                state["initial_draft"] = snapshot["text"]
                state["stage"] = "initial_review"
            else:
                if ids != [r["id"] for r in state["snapshot"]["requests"]]:
                    raise ValueError("El borrador integrado debe conservar todas las peticiones.")
                state["stage"] = "final_review"
            state.update(snapshot=snapshot, error=None)
            _event(state, state["stage"])
            self._finish_progress(db, case_id, worker, "done")
            db.execute("DELETE FROM case_pool_work_results WHERE case_id=?", (case_id,))
        return self.get(case_id)

    def set_initial(self, case_id, snapshot, *, revision, worker=None):
        return self._save_snapshot(case_id, snapshot, revision, "preparing", worker)

    def open_admin_review(self, case_id, actor, revision):
        _admin(actor)
        with self._change(case_id, revision, "initial_review", "preparing") as (db, state):
            if state.get("review_imported"):
                raise Conflict("Este borrador ya fue revisado en las cuatro etapas.")
            # Retain the automatic snapshot and any prior corrections for consultation.
            if state["stage"] == "preparing":
                state["snapshot"] = self._working_snapshot(db, case_id)
                self._finish_progress(db, case_id, None, "interrupted")
            state.update(stage="admin_review", error=None)
            _event(state, "review_opened", actor)
        return self.get(case_id)

    def import_admin_review(self, case_id, actor, revision, snapshot):
        _admin(actor)
        with self._change(case_id, revision, "admin_review") as (db, state):
            if state["snapshot"]:
                db.execute("INSERT OR IGNORE INTO case_pool_previous_review VALUES (?,?)",
                           (case_id, _dump(state["snapshot"])))
                state["previous_draft"] = state["snapshot"].get("text", "")
            state.update(stage="initial_review", snapshot=snapshot, review_imported=True,
                         initial_draft=state["initial_draft"] or snapshot["text"], error=None)
            _event(state, "review_imported", actor)
        return self.get(case_id)

    def set_integrated(self, case_id, snapshot, *, revision, worker=None):
        return self._save_snapshot(case_id, snapshot, revision, "integration", worker)

    def set_error(self, case_id, message, *, revision, worker=None):
        with self._change(case_id, revision, "preparing", "integration") as (db, state):
            self._finish_progress(db, case_id, worker, "error")
            state["error"] = str(message)[:1200]
            _event(state, "error")

    def review_request(self, case_id, request_id, actor, revision, answer, gaps, reason):
        _admin(actor)
        answer, reason = answer.strip(), reason.strip()
        gaps = list(dict.fromkeys(gap.strip() for gap in gaps if gap.strip()))
        if not reason:
            raise ValueError("Explica por qué corriges la respuesta o sus faltantes.")
        if not answer and not gaps:
            raise ValueError("Escribe una respuesta o indica qué falta para completarla.")
        with self._change(case_id, revision, "initial_review", "final_review") as (_, state):
            snapshot = state["snapshot"]
            row = next((r for r in snapshot["requests"] if r["id"] == request_id), None)
            if row is None:
                raise ValueError("La petición seleccionada no pertenece a este expediente.")
            previous = dict(answer=row["answer"], gaps=row["gaps"])
            revised = dict(answer=answer, gaps=gaps)
            if previous == revised:
                raise ValueError("Modifica la respuesta o sus faltantes antes de guardar.")
            if previous["answer"] != answer:
                # The old paragraph spans describe the superseded wording.
                row.pop("paragraphs", None)
            row.update(**revised, gap="\n".join(gaps))
            row["human_review"] = dict(actor_id=actor, reason=reason, created_at=now())
            snapshot["text"] = reply_text(snapshot["requests"], snapshot.get("letter"))
            _event(state, "request_reviewed", actor, request_id=request_id,
                   before=previous, after=revised, reason=reason)
        return self.get(case_id)

    def start(self, case_id, actor):
        _admin(actor)
        state = self.enroll(case_id)
        if state["stage"] == "preparing":
            raise Conflict("Abre la revisión administrativa para continuar con las cuatro etapas.")
        if state["stage"] != "integration":
            raise Conflict("El borrador ya está disponible para revisión.")
        if state["error"]:
            with self._change(case_id, state["revision"], state["stage"]) as (db, updated):
                updated["error"] = None
                db.execute("DELETE FROM case_pool_progress WHERE case_id=?", (case_id,))
                _event(updated, "retry", actor)
        callback = self.on_integration
        if callback:
            callback(case_id)
        return self.get(case_id)

    def publish(self, case_id, actor, revision, specs, *, returned=False):
        _admin(actor)
        with self._change(case_id, revision, "final_review" if returned else "initial_review"
                          ) as (db, state):
            if not returned and not state.get("review_imported"):
                raise Conflict("Confirma las cuatro etapas del expediente antes de publicar.")
            requests = {r["id"]: r for r in state["snapshot"]["requests"]}
            covered = set()
            round_number = state["round"] + 1
            for position, spec in enumerate(specs):
                req = spec["request_id"]
                department = spec["department"].strip()
                instruction = spec["instruction"].strip()
                if req not in requests or not department or not instruction:
                    raise ValueError("Cada trámite necesita una petición, dependencia y encargo.")
                assigned = spec.get("manager_id") or None
                if assigned:
                    _manager(db, assigned)
                state["tasks"].append(dict(
                    id=uuid4().hex, request_id=req, department=department, instruction=instruction,
                    round=round_number, position=position + 1, manager_id=assigned, owner_id=None,
                    status="available" if position == 0 else "waiting", contributions=[],
                ))
                covered.add(req)
            missing = [rid for rid, req in requests.items() if _has_gap(req) and rid not in covered]
            if missing:
                raise ValueError("Asigna un trámite a los faltantes de " + ", ".join(missing) + ".")
            if returned and not specs:
                raise ValueError("Indica la corrección y la petición que se devuelve a la bolsa.")
            state["round"] = round_number
            state["stage"] = "pool" if specs else "final_review"
            _event(state, "returned" if returned else "published", actor, round=round_number)
        return self.get(case_id)

    def claim(self, case_id, task_id, actor, revision):
        with self._change(case_id, revision, "pool") as (db, state):
            _manager(db, actor)
            task = _turn(state, actor, task_id, "available")
            task.update(status="claimed", owner_id=actor)
            _event(state, "claimed", actor, task_id=task_id)
        return self.get(case_id)

    def _prepare_files(self, uploads):
        if len(uploads) > 20:
            raise ValueError("Cada aporte admite como máximo 20 archivos adjuntos.")
        result = []
        remaining = MAX_SOURCE_BYTES
        for filename, stream in uploads:
            name = Path(filename.replace("\\", "/")).name
            suffix = Path(name).suffix.lower()
            if suffix not in {".pdf", ".docx", ".txt", *IMAGE_FORMATS} or len(name) > 255:
                raise ValueError("Adjunta archivos PDF, DOCX, TXT, PNG o JPG.")
            data = stream.read(remaining + 1)
            if not data or len(data) > remaining:
                raise ValueError("El aporte admite hasta 20 MB en total y archivos con contenido.")
            remaining -= len(data)
            with TemporaryDirectory() as temp:
                path = Path(temp) / ("original" + suffix)
                path.write_bytes(data)
                try:
                    pages, _ = read_source(path, self.pdf_extractor)
                    extracted = "\n".join(p["text"] for p in pages)
                    error = None
                except ValueError as exc:
                    # Keep the actual signed original even when OCR cannot read it.
                    extracted, error = "", str(exc)[:500]
            result.append((name, data, extracted, error))
        return result

    def complete(self, case_id, task_id, actor, revision, note, uploads):
        note = note.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not note and not uploads:
            raise ValueError("Escribe la respuesta de la dependencia o adjunta su soporte.")
        current = self.get(case_id)
        if current["revision"] != revision:
            raise Conflict("El turno cambió. Actualiza la bolsa.")
        _turn(current, actor, task_id, "claimed")
        prepared = self._prepare_files(uploads)
        with self._change(case_id, revision, "pool") as (db, state):
            task = _turn(state, actor, task_id, "claimed")
            files = []
            for filename, original, extracted, error in prepared:
                fid = uuid4().hex
                db.execute("INSERT INTO case_pool_files VALUES (?,?,?,?,?)",
                           (fid, case_id, filename, original, extracted))
                files.append(dict(id=fid, filename=filename, url=f"/api/cases/{case_id}/pool/"
                                  f"files/{fid}", extraction_error=error))
            task["contributions"].append(dict(actor_id=actor, note=note,
                                              files=files, created_at=now()))
            task["status"] = "completed"
            following = next((t for t in state["tasks"] if t["status"] == "waiting"), None)
            if following:
                following["status"] = "available"
            else:
                state["stage"] = "integration"
                db.execute("DELETE FROM case_pool_progress WHERE case_id=?", (case_id,))
            _event(state, "completed", actor, task_id=task_id)
        if not following and self.on_integration:
            self.on_integration(case_id)
        return self.get(case_id)

    def integration_input(self, case_id):
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._case(db, case_id)
            state = self._stored(db, case_id)
            if not state or state["stage"] != "integration":
                raise Conflict("El expediente no está pendiente de integración.")
            tasks = [t for t in state["tasks"] if t["round"] == state["round"]]
            for task in tasks:
                for contribution in task["contributions"]:
                    for file in contribution["files"]:
                        row = db.execute(
                            "SELECT extracted FROM case_pool_files WHERE case_id=? AND id=?",
                            (case_id, file["id"]),
                        ).fetchone()
                        if not row:
                            raise Conflict("Falta un adjunto registrado en el trámite.")
                        file["text"] = row[0]
            return state["revision"], state["snapshot"], tasks

    def attachment(self, case_id, file_id):
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._case(db, case_id)
            row = db.execute("SELECT filename,original FROM case_pool_files WHERE case_id=? "
                             "AND id=?", (case_id, file_id)).fetchone()
        if not row:
            raise KeyError("No se encontró el soporte en este expediente.")
        return row

    def approve(self, case_id, actor, revision):
        _admin(actor)
        with self._change(case_id, revision, "final_review") as (_, state):
            if any(_has_gap(r) for r in state["snapshot"]["requests"]):
                raise Conflict("Quedan faltantes en el borrador. Devuelve los puntos a la bolsa.")
            if any(not (r.get("answer") or "").strip() for r in state["snapshot"]["requests"]):
                raise Conflict("Cada petición necesita una respuesta antes de aprobar el borrador.")
            xml_text(state["snapshot"]["text"])
            state.update(stage="approved", approved_at=now())
            _event(state, "approved", actor)
        return self.get(case_id)
