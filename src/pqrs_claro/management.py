"""Pilot work queue: one owner per case, independent of content revisions."""

import json
from datetime import date
from uuid import uuid4

from fastapi import APIRouter
from pydantic import Field

from .models import StrictModel
from .storage import Conflict, now


class ManagerInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)


class ManagementAction(StrictModel):
    revision: int = Field(ge=0)
    actor_id: str = Field(min_length=1, max_length=40)
    action: str
    manager_id: str | None = None
    subject: str | None = Field(default=None, max_length=240)
    reference: str | None = Field(default=None, max_length=100)
    received_date: date | None = None
    due_date: date | None = None
    state: str | None = None
    note: str = Field(default="", max_length=2000)


class ManagementStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS managers (id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS case_management (
                    case_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS management_events (
                    case_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(case_id, revision));
            """)
            for i in (1, 2):
                db.execute(
                    "INSERT OR IGNORE INTO managers VALUES (?,?)", (f"gestor-{i}", f"Gestor {i}")
                )

    def managers(self):
        with self.store.connect() as db:
            return [
                dict(id=i, name=n)
                for i, n in db.execute("SELECT id,name FROM managers ORDER BY name")
            ]

    def add_manager(self, name):
        name = name.strip()
        if not name:
            raise ValueError("Escribe el nombre del gestor.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for mid, existing in db.execute("SELECT id,name FROM managers"):
                if existing.casefold() == name.casefold():
                    return dict(id=mid, name=existing)
            mid = uuid4().hex
            db.execute("INSERT INTO managers VALUES (?,?)", (mid, name))
        return dict(id=mid, name=name)

    @staticmethod
    def default(case):
        origin = case.get("origin") or {}
        receipt = case.get("receipt") or {}
        started = bool(case.get("identification")) or case["status"] != "uploaded"
        return dict(
            revision=0,
            owner_id=None,
            state="in_progress" if started else "received",
            subject=receipt.get("subject") or origin.get("subject") or "",
            reference=receipt.get("reference") or origin.get("reported_case_number") or "",
            received_date=receipt.get("received_date")
            or (case.get("received_at") or case["created_at"])[:10],
            due_date=receipt.get("due_date"),
            started_at=case["created_at"] if started else None,
            updated_at=case["created_at"],
            note="",
        )

    def get(self, case_id, *, include_deleted=False):
        case = self.store.get(case_id, include_deleted=include_deleted)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT body FROM case_management WHERE case_id=?", (case_id,)
            ).fetchone()
        return json.loads(row[0]) if row else self.default(case)

    def enrich(self, items):
        names = {m["id"]: m["name"] for m in self.managers()}
        for item in items:
            management = self.get(item["id"], include_deleted=bool(item.get("deleted_at")))
            case = self.store.get(item["id"], include_deleted=bool(item.get("deleted_at")))
            item["last_activity"] = max(
                [
                    management["updated_at"],
                    *[
                        event["created_at"]
                        for event in case.get("events", [])
                        if event.get("created_at")
                    ],
                ]
            )
            item["management"] = {**management, "owner_name": names.get(management["owner_id"])}
            item["subject"] = management["subject"] or item["subject"]
            item["case_number"] = management["reference"] or item["case_number"]
            item["internal_number"] = "PQRS-" + item["id"][:12].upper()
        return items

    def require_started(self, case_id):
        record = self.get(case_id)
        if not record["started_at"] or not record["owner_id"]:
            raise Conflict("Toma el expediente e inicia su gestión desde la bandeja.")
        if record["state"] == "closed":
            raise Conflict("Reabre la gestión del expediente antes de analizarlo.")

    def change(self, case_id, action):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            raw = db.execute("SELECT body FROM cases WHERE id=?", (case_id,)).fetchone()
            if not raw:
                raise KeyError(case_id)
            deleted = db.execute(
                "SELECT deleted_at FROM case_lifecycle WHERE case_id=?", (case_id,)
            ).fetchone()
            if deleted and deleted[0]:
                raise Conflict("Restaura el expediente antes de gestionarlo.")
            case = json.loads(raw[0])
            row = db.execute(
                "SELECT body FROM case_management WHERE case_id=?", (case_id,)
            ).fetchone()
            record = json.loads(row[0]) if row else self.default(case)
            if record["revision"] != action.revision:
                raise Conflict("Otro gestor modificó el expediente. Actualiza la bandeja.")
            names = dict(db.execute("SELECT id,name FROM managers"))
            if action.actor_id not in names:
                raise ValueError("Selecciona un gestor válido para el piloto.")
            before = dict(record)
            if action.action == "claim":
                if record["owner_id"]:
                    raise Conflict("El expediente ya tiene un gestor asignado.")
                record["owner_id"] = action.actor_id
                if not record["started_at"]:
                    record["state"] = "assigned"
            elif action.action == "assign":
                if action.manager_id not in names or not action.note.strip():
                    raise ValueError(
                        "Selecciona el responsable e indica el motivo de la asignación."
                    )
                record["owner_id"] = action.manager_id
                if not record["started_at"]:
                    record["state"] = "assigned"
            elif action.action == "start":
                if record["owner_id"] != action.actor_id:
                    raise Conflict("Solo el gestor asignado puede iniciar esta gestión.")
                if record["started_at"]:
                    raise Conflict("La gestión ya se inició. Usa Continuar.")
                record.update(state="in_progress", started_at=now())
            elif action.action == "metadata":
                for key in ("subject", "reference", "received_date", "due_date"):
                    value = getattr(action, key)
                    if key in action.model_fields_set:
                        record[key] = (
                            value.isoformat()
                            if isinstance(value, date)
                            else (value or "").strip() or None
                        )
                if not record["received_date"]:
                    raise ValueError("Registra la fecha de recepción.")
                if record["due_date"] and record["due_date"] < record["received_date"]:
                    raise ValueError("La fecha límite no puede ser anterior a la recepción.")
            elif action.action == "state":
                if record["owner_id"] != action.actor_id or not record["started_at"]:
                    raise Conflict("El gestor asignado debe haber iniciado la gestión.")
                if action.state not in {"in_progress", "pending", "ready_review", "closed"}:
                    raise ValueError("Estado de gestión no válido.")
                if not action.note.strip():
                    raise ValueError("Registra el motivo o resultado de la gestión.")
                record["state"] = action.state
            else:
                raise ValueError("Acción de gestión no reconocida.")
            record.update(
                revision=record["revision"] + 1, updated_at=now(), note=action.note.strip()
            )
            event = dict(
                action=action.action,
                actor_id=action.actor_id,
                actor_name=names[action.actor_id],
                created_at=record["updated_at"],
                note=record["note"],
                before=before,
                after=record,
            )
            db.execute(
                "INSERT OR REPLACE INTO case_management VALUES (?,?)", (case_id, json.dumps(record))
            )
            db.execute(
                "INSERT INTO management_events VALUES (?,?,?)",
                (case_id, record["revision"], json.dumps(event)),
            )
        return record

    def history(self, case_id):
        self.store.get(case_id)
        with self.store.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT body FROM management_events WHERE case_id=? ORDER BY revision DESC",
                    (case_id,),
                )
            ]


def management_router(management, service):
    router = APIRouter()

    @router.get("/api/managers")
    def managers():
        return management.managers()

    @router.post("/api/managers", status_code=201)
    def add_manager(body: ManagerInput):
        return management.add_manager(body.name)

    @router.get("/api/cases/{case_id}/management")
    def get(case_id: str):
        return management.get(case_id)

    @router.get("/api/cases/{case_id}/management/history")
    def history(case_id: str):
        return management.history(case_id)

    @router.post("/api/cases/{case_id}/management")
    def change(case_id: str, body: ManagementAction):
        with service.lock:
            if case_id in service.active:
                raise Conflict("Espera a que termine el análisis antes de cambiar la gestión.")
            if (
                body.action == "start"
                and not service.settings.api_key
                and service.identifier is None
            ):
                raise ValueError(
                    "Falta configurar OpenAI; el expediente sigue pendiente de iniciar."
                )
            result = management.change(case_id, body)
            if body.action == "start":
                case = management.store.get(case_id)
                if case["status"] in {"uploaded", "error"}:
                    service.start(case_id)
            return result

    return router
