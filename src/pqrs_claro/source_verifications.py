"""Comprobaciones atribuidas y aplicaciones explícitas, con historial inmutable.

Una declaración de un antecedente conserva su atribución documental. Nunca se
convierte en revisión humana por haberla extraído o seleccionado una IA.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import DomainError
from .source_context import build_source_requests
from .source_library import digest
from .storage import Conflict, now


def source_signature(source):
    return {
        "source_id": source.get("id") or source.get("source_id"),
        "document_id": source.get("document_id"),
        "version": source.get("version"),
        "source_sha256": source.get("sha256"),
        "extraction_revision": source.get("extraction_revision") or 0,
    }


def request_fingerprint(case, request_id):
    """Sólo cambia por el original o la pregunta y su contexto pertinente."""
    requests = build_source_requests(case)
    request = next((item for item in requests if item["id"] == request_id), None)
    if request is None:
        raise DomainError("No se encontró una de las preguntas de la comprobación.")
    request.pop("allowed_collection_ids", None)
    # Los límites de lectura para la IA no deben ocultar cambios al invalidar una aplicación.
    context = request.get("context", {})
    related_ids = set(context.get("omitted_request_ids", []))
    for name in ("ancestors", "children", "referenced_requests", "preceding_section"):
        related_ids.update(item["id"] for item in context.get(name, []))
    related = [item for item in case["identification"]["requests"]
               if item["id"] in related_ids]
    return digest({"original": case.get("sha256"), "request": request, "related": related})


def _text(value, name, limit, *, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise DomainError(f"Indica {name} válido, de hasta {limit} caracteres.")
    return value.strip() or None


class SourceVerificationStore:
    def __init__(self, data_dir, library, cases):
        self.library, self.cases = library, cases
        self.db = Path(data_dir) / "comprobaciones.sqlite"
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS verifications(
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, source_id TEXT,
                    kind TEXT NOT NULL, dedup_key TEXT UNIQUE, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS verification_applications(
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
                    verification_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS verification_events(
                    id TEXT PRIMARY KEY, target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS verification_source ON verifications(source_id);
                CREATE INDEX IF NOT EXISTS application_case ON verification_applications(case_id);
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

    def _case(self, case_id, version=None):
        case = self.cases.get(case_id)
        if version is not None and case["version"] != version:
            raise Conflict("El expediente cambió. Recarga antes de registrar la comprobación.")
        return case

    def _requests(self, case, request_ids):
        if (not isinstance(request_ids, list) or not request_ids
                or len(request_ids) > 100 or len(set(request_ids)) != len(request_ids)):
            raise DomainError("Selecciona las preguntas concretas, sin repetirlas.")
        valid = {item["id"] for item in (case.get("identification") or {}).get("requests", [])}
        if not set(request_ids) <= valid:
            raise DomainError("Una pregunta no pertenece a este expediente.")
        return sorted(request_ids)

    def _source_passage(self, case_id, source_id, passage):
        eligible = {source["id"] for source in self.library.eligible(case_id)}
        if source_id not in eligible:
            raise DomainError("La fuente no está disponible en el ámbito actual del expediente.")
        detail = self.library.get(source_id, case_id)
        self.library.original(source_id, case_id)  # Comprueba los bytes del original.
        source, pages = detail["source"], detail["pages"]
        if not isinstance(passage, dict):
            raise DomainError("Selecciona el pasaje literal que sustenta la comprobación.")
        page_number = passage.get("page")
        start, end = passage.get("line_start"), passage.get("line_end")
        if any(type(value) is not int for value in (page_number, start, end)):
            raise DomainError("La cita requiere página y líneas válidas.")
        page = next((item for item in pages if item["number"] == page_number), None)
        lines = page["text"].splitlines() if page else []
        if not 1 <= start <= end <= len(lines):
            raise DomainError("El pasaje seleccionado no existe en la fuente.")
        quote = "\n".join(lines[start - 1:end])
        if quote != passage.get("quote") or not quote.strip():
            raise DomainError("La cita debe coincidir literalmente con las líneas del documento.")
        chunk_id = f"{source_id}:{page_number}:{start}:{end}"
        if passage.get("chunk_id") != chunk_id:
            raise DomainError("El identificador del pasaje no coincide con su ubicación.")
        return source, {
            "chunk_id": chunk_id, "page": page_number, "line_start": start,
            "line_end": end, "quote": quote,
        }

    def _record(self, case_id, version, *, kind, fact, source_id, passage, basis,
                attributed_to, recorded_by, scope, request_ids):
        case = self._case(case_id, version)
        request_ids = self._requests(case, request_ids)
        fact = _text(fact, "el hecho comprobado", 3000)
        basis = _text(basis, "cómo y con qué se comprobó", 6000)
        attributed_to = _text(attributed_to, "la atribución disponible", 500, required=False)
        recorded_by = _text(recorded_by, "quién registra la comprobación", 200)
        if not isinstance(scope, dict) or set(scope) - {"person", "period", "subject"}:
            raise DomainError("El alcance admite persona, periodo y asunto.")
        scope = {key: _text(scope.get(key), f"el alcance de {key}", 1000, required=False)
                 for key in ("person", "period", "subject")}
        with self.lock, self.library.lock:
            if source_id:
                source, passage = self._source_passage(case_id, source_id, passage)
                signature = source_signature(source)
            else:
                if kind != "human_review" or passage is not None:
                    raise DomainError("Un antecedente declarado requiere documento y pasaje.")
                signature = dict(source_id=None, document_id=None, version=None,
                                 source_sha256=None, extraction_revision=0)
            body = {
                "id": uuid4().hex, "kind": kind, "fact": fact, **signature,
                "passage": passage, "basis": basis, "attributed_to": attributed_to,
                "recorded_by": recorded_by, "recorded_at": now(), "scope": scope,
                "request_ids": request_ids, "case_id": case_id,
                "case_version": case["version"],
                "recording_method": "human_form" if kind == "human_review" else "model_extraction",
            }
            # Una extracción repetida no crea una revisión adicional ni altera el antecedente.
            dedup_key = None
            if kind == "antecedent_declared":
                dedup_key = digest({key: body[key] for key in (
                    "kind", "fact", "source_id", "document_id", "version", "source_sha256",
                    "extraction_revision", "passage", "basis", "attributed_to", "case_id",
                    "request_ids", "scope",
                )})
            self._case(case_id, version)
            with self.connect() as conn:
                if dedup_key:
                    previous = conn.execute(
                        "SELECT body FROM verifications WHERE dedup_key=?", (dedup_key,)
                    ).fetchone()
                    if previous:
                        return json.loads(previous[0])
                conn.execute("INSERT INTO verifications VALUES (?,?,?,?,?,?)", (
                    body["id"], case_id, source_id, kind, dedup_key, json.dumps(body),
                ))
            return body

    def record_human(self, case_id, version, *, fact, basis, recorded_by, request_ids,
                     source_id=None, passage=None, attributed_to=None, scope=None):
        return self._record(
            case_id, version, kind="human_review", fact=fact, source_id=source_id,
            passage=passage, basis=basis, attributed_to=attributed_to, recorded_by=recorded_by,
            scope=scope or {}, request_ids=request_ids,
        )

    def record_antecedent(self, case, source, passage, fact, basis, attributed_to=None,
                          request_ids=None, scope=None):
        """Entrada interna del evaluador; no existe endpoint para asignar este origen."""
        return self._record(
            case["id"], case["version"], kind="antecedent_declared", fact=fact,
            source_id=source.get("source_id") or source["id"], passage=passage, basis=basis,
            attributed_to=attributed_to, recorded_by="Extracción automática del antecedente",
            scope=scope or {}, request_ids=request_ids or [],
        )

    def get(self, verification_id):
        with self.connect() as conn:
            row = conn.execute("SELECT body FROM verifications WHERE id=?",
                               (verification_id,)).fetchone()
        if not row:
            raise KeyError("No se encontró la comprobación.")
        return json.loads(row[0])

    def _revocations(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT body FROM verification_events ORDER BY rowid").fetchall()
        return {(event["target_type"], event["target_id"]): event
                for event in (json.loads(row[0]) for row in rows)
                if event["action"] == "revoke"}

    def _record_problem(self, record, case_id, eligible, revocations):
        if ("verification", record["id"]) in revocations:
            return "revoked"
        if not record["source_id"]:
            return None if record["case_id"] == case_id else "outside_scope"
        current = eligible.get(record["source_id"])
        if current is None:
            return "source_unavailable_or_replaced"
        if any(record[key] != value for key, value in source_signature(current).items()):
            return "source_changed"
        return None

    def list(self, case_id):
        case = self._case(case_id)
        sources = self.library.eligible(case_id)
        eligible = {source["id"]: source for source in sources}
        doc_ids = {source["document_id"] for source in sources}
        revocations = self._revocations()
        with self.connect() as conn:
            rows = conn.execute("SELECT body FROM verifications ORDER BY rowid DESC").fetchall()
            application_rows = conn.execute(
                "SELECT body FROM verification_applications WHERE case_id=? ORDER BY rowid DESC",
                (case_id,),
            ).fetchall()
        records = []
        for row in rows:
            record = json.loads(row[0])
            if (record["case_id"] != case_id and record["document_id"] not in doc_ids):
                continue
            problem = self._record_problem(record, case_id, eligible, revocations)
            records.append({**record, "active": problem is None, "inactive_reason": problem})
        applications = []
        by_id = {record["id"]: record for record in records}
        for row in application_rows:
            application = json.loads(row[0])
            record = by_id.get(application["verification_id"])
            problem = self._application_problem(application, record, case, revocations)
            active_ids = self._active_request_ids(application, case) if problem is None else []
            applications.append({**application, "active": problem is None,
                                 "inactive_reason": problem, "active_request_ids": active_ids,
                                 "inactive_request_ids": [rid for rid in application["request_ids"]
                                                          if rid not in active_ids]})
        return {"records": records, "applications": applications}

    def _active_request_ids(self, application, case):
        active = []
        for request_id, previous in application["request_fingerprints"].items():
            try:
                current = request_fingerprint(case, request_id)
            except DomainError:
                continue
            if current == previous:
                active.append(request_id)
        return active

    def _application_problem(self, application, record, case, revocations):
        if ("application", application["id"]) in revocations:
            return "revoked"
        if not record or not record.get("active", True):
            return "verification_unavailable"
        if not self._active_request_ids(application, case):
            return "question_changed"
        return None

    def apply(self, case_id, verification_id, version, *, request_ids, check_key, basis,
              recorded_by, check_reason=None, scope_key=None):
        """El router valida la comprobación pendiente concreta antes de llamar aquí."""
        with self.lock, self.library.lock:
            case = self._case(case_id, version)
            request_ids = self._requests(case, request_ids)
            record = self.get(verification_id)
            eligible = {source["id"]: source for source in self.library.eligible(case_id)}
            if self._record_problem(record, case_id, eligible, self._revocations()):
                raise Conflict(
                    "La comprobación cambió, fue retirada o su fuente ya no está vigente."
                )
            if record["source_id"]:
                self._source_passage(case_id, record["source_id"], record["passage"])
            body = {
                "id": uuid4().hex, "case_id": case_id, "verification_id": verification_id,
                "check_key": _text(check_key, "la comprobación pendiente", 100),
                "request_ids": request_ids,
                "basis": _text(basis, "por qué aplica a estas preguntas", 6000),
                "recorded_by": _text(recorded_by, "quién confirma su aplicación", 200),
                "recorded_at": now(), "case_version": case["version"],
                "request_fingerprints": {
                    rid: request_fingerprint(case, rid) for rid in request_ids
                },
                "check_reason": check_reason, "scope_key": scope_key,
            }
            self._case(case_id, version)
            with self.connect() as conn:
                conn.execute("INSERT INTO verification_applications VALUES (?,?,?,?)", (
                    body["id"], case_id, verification_id, json.dumps(body),
                ))
            return body

    def active_applications(self, case, eligible_sources=None):
        case = self._case(case) if isinstance(case, str) else case
        sources = (self.library.eligible(case["id"]) if eligible_sources is None
                   else eligible_sources)
        eligible = {source["id"]: source for source in sources}
        revocations = self._revocations()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT a.body,v.body FROM verification_applications a JOIN verifications v "
                "ON v.id=a.verification_id WHERE a.case_id=? ORDER BY a.rowid", (case["id"],),
            ).fetchall()
        active = []
        for row in rows:
            application, record = (json.loads(value) for value in row)
            if self._record_problem(record, case["id"], eligible, revocations):
                continue
            if self._application_problem(application, record, case, revocations):
                continue
            active_ids = self._active_request_ids(application, case)
            active.append({**application, "request_ids": active_ids,
                           "original_request_ids": application["request_ids"], "record": record})
        return active

    def fingerprint(self, case_id, eligible_sources=None):
        """Guardar un registro sin aplicarlo no invalida una búsqueda ni obliga a repetir la IA."""
        with self.connect() as conn:
            applications = [json.loads(row[0]) for row in conn.execute(
                "SELECT body FROM verification_applications WHERE case_id=? ORDER BY id", (case_id,)
            )]
            records = [json.loads(row[0]) for row in conn.execute(
                "SELECT DISTINCT v.body FROM verifications v JOIN verification_applications a "
                "ON a.verification_id=v.id WHERE a.case_id=? ORDER BY v.id", (case_id,),
            )]
        ids = {("verification", item["verification_id"]) for item in applications}
        ids.update(("application", item["id"]) for item in applications)
        events = [value for key, value in self._revocations().items() if key in ids]
        return digest({"records": records, "applications": applications,
                       "revocations": sorted(events, key=lambda item: item["id"])})

    def revoke(self, case_id, target_type, target_id, version, *, reason, recorded_by):
        if target_type not in {"verification", "application"}:
            raise DomainError("Tipo de registro desconocido.")
        with self.lock:
            self._case(case_id, version)
            if target_type == "verification":
                record = self.get(target_id)
            else:
                with self.connect() as conn:
                    row = conn.execute("SELECT body FROM verification_applications WHERE id=?",
                                       (target_id,)).fetchone()
                if not row:
                    raise KeyError("No se encontró la aplicación.")
                record = json.loads(row[0])
            if record["case_id"] != case_id:
                raise KeyError("El registro pertenece a otro expediente.")
            body = {
                "id": uuid4().hex, "action": "revoke", "target_type": target_type,
                "target_id": target_id, "case_id": case_id,
                "reason": _text(reason, "por qué se retira", 3000),
                "recorded_by": _text(recorded_by, "quién retira la comprobación", 200),
                "recorded_at": now(),
            }
            with self.connect() as conn:
                conn.execute("INSERT INTO verification_events VALUES (?,?,?,?)", (
                    body["id"], target_type, target_id, json.dumps(body),
                ))
            return body
