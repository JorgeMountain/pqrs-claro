"""Server-timed, foreground work estimates for the local manager pilot."""

from dataclasses import dataclass
from time import time_ns
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from .models import StrictModel
from .storage import Conflict, now

HEARTBEAT_SECONDS = 15
IDLE_SECONDS = 120
MAX_GAP_MS = 3 * HEARTBEAT_SECONDS * 1000


class WorkEvent(StrictModel):
    actor_id: str = Field(min_length=1, max_length=40)
    session_id: UUID
    sequence: int = Field(ge=0, le=2**31 - 1)
    event: Literal["start", "heartbeat", "confirm", "stop"]
    activity: bool = False


class ExternalWork(StrictModel):
    actor_id: str = Field(min_length=1, max_length=40)
    entry_id: UUID
    minutes: int = Field(ge=1, le=1440)
    reason: str = Field(min_length=3, max_length=500)


@dataclass
class Window:
    case_id: str
    actor_id: str
    sequence: int
    last_ms: int
    interaction_ms: int
    ended: int

    @property
    def deadline_ms(self):
        return self.interaction_ms + IDLE_SECONDS * 1000

    def status(self):
        if self.ended:
            return "ended"
        return "unconfirmed" if self.last_ms >= self.deadline_ms else "active"


def _window(db, sid):
    row = db.execute(
        "SELECT case_id,actor_id,sequence,last_ms,interaction_ms,ended "
        "FROM work_sessions WHERE id=?", (sid,),
    ).fetchone()
    return Window(*row) if row else None


def _require_owner(db, case_id, actor):
    row = db.execute(
        "SELECT l.deleted_at,json_extract(m.body,'$.owner_id'),json_extract(m.body,'$.state') "
        "FROM cases c LEFT JOIN case_lifecycle l ON l.case_id=c.id "
        "LEFT JOIN case_management m ON m.case_id=c.id WHERE c.id=?", (case_id,),
    ).fetchone()
    if not row:
        raise KeyError(case_id)
    if row[0] or row[2] == "closed":
        raise Conflict("El expediente está finalizado o en la papelera.")
    if row[1] != actor:
        raise Conflict("Solo el gestor asignado puede registrar trabajo en este expediente.")


def _advance(db, sid, window, tick, *, event, sequence, activity=False):
    """Only account for intervals bracketed by two timely server observations."""
    elapsed = tick - window.last_ms
    continuous = 0 <= elapsed <= MAX_GAP_MS
    active = min(elapsed, max(0, window.deadline_ms - window.last_ms)) if continuous else 0
    unconfirmed = elapsed - active if continuous else 0
    window.ended = int(event == "stop" or not continuous)
    if event == "confirm" or (activity and tick < window.deadline_ms):
        window.interaction_ms = tick
    window.last_ms = tick
    db.execute(
        "UPDATE work_sessions SET sequence=?,last_ms=?,interaction_ms=?,ended=?,"
        "active_ms=active_ms+?,unconfirmed_ms=unconfirmed_ms+? WHERE id=?",
        (sequence, tick, window.interaction_ms, window.ended, active, unconfirmed, sid),
    )
    return window.status()


class WorkSessions:
    def __init__(self, store, clock_ms=None):
        self.store = store
        self.clock_ms = clock_ms or (lambda: time_ns() // 1_000_000)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS work_sessions (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                    started_ms INTEGER, last_ms INTEGER NOT NULL, interaction_ms INTEGER NOT NULL,
                    sequence INTEGER NOT NULL, ended INTEGER NOT NULL,
                    active_ms INTEGER NOT NULL DEFAULT 0, unconfirmed_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS work_one_window_per_actor
                    ON work_sessions(actor_id) WHERE ended=0;
                CREATE INDEX IF NOT EXISTS work_sessions_by_case ON work_sessions(case_id);
                CREATE TABLE IF NOT EXISTS work_external (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                    minutes INTEGER NOT NULL, reason TEXT NOT NULL, declared_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS work_external_by_case ON work_external(case_id);
                CREATE TABLE IF NOT EXISTS work_tracking_config (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
            """)
            db.execute("INSERT OR IGNORE INTO work_tracking_config VALUES ('installed_at',?)",
                       (now(),))

    def _end(self, db, sid, tick):
        window = _window(db, sid)
        _advance(db, sid, window, tick, event="stop", sequence=window.sequence)

    def close_case(self, db, case_id):
        """Called in the same transaction as closing, transferring or trashing a case."""
        tick = self.clock_ms()
        for (sid,) in db.execute(
            "SELECT id FROM work_sessions WHERE case_id=? AND ended=0", (case_id,),
        ).fetchall():
            self._end(db, sid, tick)

    def record(self, case_id, body):
        sid = str(body.session_id)
        if (body.event == "start") != (body.sequence == 0):
            raise ValueError("Usa la secuencia cero al iniciar y una mayor al continuar.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            tick = self.clock_ms()
            window = _window(db, sid)
            if window and (window.case_id, window.actor_id) != (case_id, body.actor_id):
                raise Conflict("La sesión ya pertenece a otro expediente o gestor.")
            if window and (window.ended or body.sequence <= window.sequence):
                status = window.status()
            elif body.event == "start":
                _require_owner(db, case_id, body.actor_id)
                previous = db.execute(
                    "SELECT id FROM work_sessions WHERE actor_id=? AND ended=0", (body.actor_id,),
                ).fetchone()
                if previous:
                    self._end(db, previous[0], tick)
                db.execute(
                    "INSERT INTO work_sessions "
                    "(id,case_id,actor_id,started_ms,last_ms,interaction_ms,sequence,ended) "
                    "VALUES (?,?,?,?,?,?,0,0)", (sid, case_id, body.actor_id, tick, tick, tick),
                )
                status = "active"
            elif window:
                _require_owner(db, case_id, body.actor_id)
                status = _advance(db, sid, window, tick, event=body.event,
                                  sequence=body.sequence, activity=body.activity)
            else:
                _require_owner(db, case_id, body.actor_id)
                if body.event == "stop":
                    # A pagehide beacon can overtake the initial POST. Never resurrect it.
                    db.execute(
                        "INSERT INTO work_sessions "
                        "(id,case_id,actor_id,last_ms,interaction_ms,sequence,ended) "
                        "VALUES (?,?,?,?,?,?,1)", (sid, case_id, body.actor_id, tick, tick,
                                                   body.sequence),
                    )
                status = "ended"
        return dict(status=status, idle_after_seconds=IDLE_SECONDS,
                    heartbeat_seconds=HEARTBEAT_SECONDS)

    def declare(self, case_id, body):
        reason = body.reason.strip()
        if len(reason) < 3:
            raise ValueError("Describe el motivo del trabajo externo.")
        entry = str(body.entry_id)
        values = (case_id, body.actor_id, body.minutes, reason)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT case_id,actor_id,minutes,reason FROM work_external WHERE id=?", (entry,),
            ).fetchone()
            if saved and saved != values:
                raise Conflict("El identificador ya se usó para una declaración diferente.")
            if not saved:
                _require_owner(db, case_id, body.actor_id)
                db.execute("INSERT INTO work_external VALUES (?,?,?,?,?,?)",
                           (entry, *values, now()))
        return dict(entry_id=entry, minutes=body.minutes, reason=reason)


def session_totals(db):
    """Measured zero is meaningful. External-only rows retain measured=False."""
    rows = db.execute("""
        SELECT case_id,actor_id,SUM(active_ms)/1000,SUM(unconfirmed_ms)/1000,
               SUM(external_seconds),MAX(measured) FROM (
            SELECT case_id,actor_id,active_ms,unconfirmed_ms,0 AS external_seconds,1 AS measured
              FROM work_sessions WHERE started_ms IS NOT NULL
            UNION ALL
            SELECT case_id,actor_id,0,0,minutes*60,0 FROM work_external
        ) GROUP BY case_id,actor_id
    """)
    return {(cid, actor): dict(active_seconds=active, unconfirmed_seconds=unconfirmed,
                               external_seconds=external, measured=bool(measured))
            for cid, actor, active, unconfirmed, external, measured in rows}


def work_sessions_router(sessions):
    router = APIRouter()

    @router.post("/api/cases/{case_id}/work-session")
    def record(case_id: str, body: WorkEvent):
        return sessions.record(case_id, body)

    @router.post("/api/cases/{case_id}/external-work")
    def declare(case_id: str, body: ExternalWork):
        return sessions.declare(case_id, body)

    return router
