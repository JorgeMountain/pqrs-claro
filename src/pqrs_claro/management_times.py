"""Elapsed case times from management transitions and observed work per manager."""

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import median
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from .management import BOGOTA
from .work_sessions import session_totals

State = Literal["received", "assigned", "in_progress", "pending", "ready_review", "closed"]
STATE_NAMES = dict(received="Recibida", assigned="Asignada", in_progress="En gestión",
                   pending="Pendiente", ready_review="Lista para revisión", closed="Finalizada")
COVERAGE_NAMES = dict(unmeasured="Sin medición", partial="Parcial", observed="Con medición")


def instant(timestamp):
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def case_metadata(db):
    # Keep pages, quotations, petition texts and the original PDF out of the report.
    query = db.execute("""
        SELECT c.id AS case_id, json_extract(c.body,'$.filename') AS filename,
            json_extract(c.body,'$.created_at') AS created_at,
            COALESCE(json_extract(m.body,'$.state'),
                CASE WHEN json_extract(c.body,'$.status') != 'uploaded'
                    OR json_extract(c.body,'$.identification') NOT IN ('{}','[]','',0)
                THEN 'in_progress' ELSE 'received' END) AS state,
            json_extract(m.body,'$.owner_id') AS owner_id,
            COALESCE(json_extract(m.body,'$.revision'),0) AS revision,
            COALESCE(NULLIF(CASE WHEN m.body IS NOT NULL THEN json_extract(m.body,'$.reference')
                ELSE json_extract(c.body,'$.receipt.reference') END,''),
                json_extract(c.body,'$.origin.reported_case_number'),'') AS reference,
            COALESCE(NULLIF(CASE WHEN m.body IS NOT NULL THEN json_extract(m.body,'$.subject')
                ELSE json_extract(c.body,'$.receipt.subject') END,''),
                NULLIF(json_extract(c.body,'$.identification.subject'),''),
                NULLIF(json_extract(c.body,'$.origin.subject'),''),
                json_extract(c.body,'$.filename'),'') AS subject,
            COALESCE(json_extract(c.body,'$.request_count'),0) AS request_count
        FROM cases c LEFT JOIN case_management m ON m.case_id=c.id
        LEFT JOIN case_lifecycle l ON l.case_id=c.id WHERE l.deleted_at IS NULL
        ORDER BY c.rowid DESC
    """)
    columns = [column[0] for column in query.description]
    return [dict(zip(columns, row)) for row in query]


def histories(db, case_ids, names):
    events = defaultdict(list)
    declarations = defaultdict(list)
    for start in range(0, len(case_ids), 500):
        batch = case_ids[start:start + 500]
        slots = ",".join("?" for _ in batch)
        query = db.execute(f"""
            SELECT case_id,revision,json_extract(body,'$.created_at') AS timestamp,
                json_extract(body,'$.actor_id') AS actor,
                json_extract(body,'$.before.state') AS old_state,
                json_extract(body,'$.before.owner_id') AS old_owner,
                json_extract(body,'$.after.state') AS new_state,
                json_extract(body,'$.after.owner_id') AS new_owner
            FROM management_events WHERE case_id IN ({slots}) ORDER BY case_id,revision
        """, batch)
        columns = [column[0] for column in query.description]
        for row in query:
            events[row[0]].append(dict(zip(columns, row)))
        for case_id, actor, minutes, reason, timestamp in db.execute(
            "SELECT case_id,actor_id,minutes,reason,declared_at FROM work_external "
            f"WHERE case_id IN ({slots}) ORDER BY declared_at DESC,id", batch
        ):
            declarations[case_id].append(dict(manager_name=names.get(actor, actor),
                                               minutes=minutes, reason=reason,
                                               declared_at=timestamp))
    return events, declarations


def timeline(case, events, as_of):
    created = instant(case["created_at"])
    cursor = created
    state = events[0]["old_state"] if events else case["state"]
    owner = events[0]["old_owner"] if events else case["owner_id"]
    complete = state == "received" and owner is None and len(events) == case["revision"]
    owners = set()
    pool = pending = 0.0
    transfers = 0
    closed_at = closed_by = first_assignment = None
    for revision, event in enumerate(events, 1):
        timestamp = instant(event["timestamp"])
        complete &= (event["revision"] == revision and event["old_state"] == state
                     and event["old_owner"] == owner and cursor <= timestamp)
        elapsed = max(0, (timestamp - cursor).total_seconds())
        if state == "received" and owner is None:
            pool += elapsed
        if state == "pending":
            pending += elapsed
        old_owner, owner = event["old_owner"], event["new_owner"]
        owners.update([old_owner, owner])
        if owner and owner != old_owner:
            first_assignment = first_assignment or event["timestamp"]
            transfers += int(old_owner is not None)
        if event["new_state"] == "closed" and event["old_state"] != "closed":
            closed_at, closed_by = event["timestamp"], event["actor"]
        elif event["new_state"] != "closed":
            closed_at = closed_by = None
        state, cursor = event["new_state"], timestamp
    complete &= state == case["state"] and owner == case["owner_id"]
    if case["state"] != "closed":
        closed_at = closed_by = None
    elapsed = max(0, (as_of - cursor).total_seconds())
    if state == "received" and owner is None:
        pool += elapsed
    if state == "pending":
        pending += elapsed
    end = instant(closed_at) if closed_at else as_of if case["state"] != "closed" else None
    owners.update([case["owner_id"], closed_by])
    owners.discard(None)
    return dict(
        closed_at=closed_at, closed_by_id=closed_by,
        first_assignment_at=first_assignment if complete else None,
        total_seconds=int(max(0, (end - created).total_seconds())) if end else None,
        pool_seconds=int(pool) if complete else None,
        pending_seconds=int(pending) if complete else None,
        transfers=transfers if complete else None,
    ), owners


def contribution(manager_id, names, entries):
    entry = entries.get(manager_id, {})
    measured = bool(entry.get("measured"))
    return dict(manager_id=manager_id, manager_name=names.get(manager_id, manager_id),
                active_seconds=entry["active_seconds"] if measured else None,
                unconfirmed_seconds=entry["unconfirmed_seconds"] if measured else None,
                external_seconds=entry.get("external_seconds", 0))


def manager_rows(cases, selected):
    groups = defaultdict(list)
    for case in cases:
        for person in case["contributors"]:
            mid = person["manager_id"]
            if not selected or mid == selected:
                groups[mid].append((case, person))
    rows = []
    for mid, entries in groups.items():
        measured = [person for _, person in entries if person["active_seconds"] is not None]
        closed = [case for case, _ in entries if case["closed_by_id"] == mid]
        resolutions = [case["total_seconds"] for case in closed
                       if case["total_seconds"] is not None]
        rows.append(dict(
            manager_id=mid, manager_name=entries[0][1]["manager_name"],
            case_count=len(entries), closed_count=len(closed), measured_case_count=len(measured),
            active_seconds=sum(p["active_seconds"] for p in measured) if measured else None,
            unconfirmed_seconds=(sum(p["unconfirmed_seconds"] for p in measured)
                                 if measured else None),
            external_seconds=sum(p["external_seconds"] for _, p in entries),
            median_active_seconds=(median(p["active_seconds"] for p in measured)
                                   if measured else None),
            median_resolution_seconds=median(resolutions) if resolutions else None,
        ))
    return sorted(rows, key=lambda row: (row["manager_name"].casefold(), row["manager_id"]))


def management_report(store, *, date_from=None, date_to=None, manager_id=None, state=None,
                      as_of=None):
    if date_from and date_to and date_from > date_to:
        raise ValueError("La fecha inicial debe ser anterior o igual a la final.")
    as_of = as_of or datetime.now(timezone.utc)
    with store.connect() as db:
        db.execute("BEGIN")
        names = dict(db.execute("SELECT id,name FROM managers"))
        installed_at = db.execute(
            "SELECT value FROM work_tracking_config WHERE key='installed_at'"
        ).fetchone()[0]
        cases = []
        for case in case_metadata(db):
            day = instant(case["created_at"]).astimezone(BOGOTA).date()
            if ((not state or state == case["state"]) and (not date_from or day >= date_from)
                    and (not date_to or day <= date_to)):
                cases.append(case)
        history, declarations = histories(db, [case["case_id"] for case in cases], names)
        work = defaultdict(dict)
        for (cid, actor), totals in session_totals(db).items():
            work[cid][actor] = totals
    results = []
    for case in cases:
        cid = case["case_id"]
        durations, participants = timeline(case, history[cid], as_of)
        participants.update(work[cid])
        if manager_id and manager_id not in participants:
            continue
        people = [contribution(mid, names, work[cid]) for mid in sorted(participants)]
        measured = [p for p in people if p["active_seconds"] is not None]
        coverage = "unmeasured"
        if measured:
            predates_tracking = instant(case["created_at"]) < instant(installed_at)
            coverage = "partial" if predates_tracking else "observed"
        case.pop("revision")
        results.append(dict(
            **case, **durations, internal_number="PQRS-" + cid[:12].upper(),
            owner_name=names.get(case["owner_id"]), contributors=people,
            external_entries=declarations[cid],
            active_seconds=sum(p["active_seconds"] for p in measured) if measured else None,
            unconfirmed_seconds=(sum(p["unconfirmed_seconds"] for p in measured)
                                 if measured else None),
            external_seconds=sum(p["external_seconds"] for p in people), measurement=coverage,
        ))
    return dict(as_of=as_of.isoformat(), tracking_started_at=installed_at, cases=results,
                managers=manager_rows(results, manager_id))


CASE_COLUMNS = {
    "case_id": "ID expediente", "internal_number": "Número interno", "reference": "Radicado",
    "subject": "Asunto", "state": "Estado",
    "owner_name": "Gestor actual", "created_at": "Alta (Bogotá)",
    "first_assignment_at": "Primera asignación (Bogotá)", "closed_at": "Cierre (Bogotá)",
    "total_seconds": "Tiempo total (s)", "pool_seconds": "En el pool sin asignar (s)",
    "pending_seconds": "En estado pendiente (s)", "active_seconds": "Activo estimado (s)",
    "unconfirmed_seconds": "Sin confirmar (s)", "external_seconds": "Externo declarado (s)",
    "transfers": "Reasignaciones", "request_count": "Peticiones", "measurement": "Medición activa",
}
MANAGER_COLUMNS = {
    "manager_name": "Gestor", "case_count": "Expedientes",
    "closed_count": "Finalizados por el gestor",
    "measured_case_count": "Expedientes con actividad medida",
    "active_seconds": "Activo estimado (s)", "unconfirmed_seconds": "Sin confirmar (s)",
    "external_seconds": "Externo declarado (s)", "median_active_seconds": "Mediana activa (s)",
    "median_resolution_seconds": "Mediana alta a cierre (s)",
}


def csv_value(key, value):
    if value is None:
        return ""
    if key.endswith("_at"):
        return instant(value).astimezone(BOGOTA).isoformat(timespec="seconds")
    if key == "state":
        return STATE_NAMES.get(value, value)
    if key == "measurement":
        return COVERAGE_NAMES[value]
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def management_times_router(store):
    router = APIRouter()

    def report(date_from: date | None = None, date_to: date | None = None,
               manager_id: str | None = None, state: State | None = None):
        return management_report(store, date_from=date_from, date_to=date_to,
                                 manager_id=manager_id, state=state)

    @router.get("/api/management-times")
    def read(data=Depends(report)):
        return data

    @router.get("/api/management-times.csv")
    def export(view: Literal["cases", "managers"] = "cases", data=Depends(report)):
        columns = CASE_COLUMNS if view == "cases" else MANAGER_COLUMNS
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(columns.values())
        for row in data[view]:
            writer.writerow(csv_value(key, row[key]) for key in columns)
        name = "expedientes" if view == "cases" else "gestores"
        disposition = f'attachment; filename="tiempos-{name}.csv"'
        return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv",
                        headers={"Content-Disposition": disposition})

    return router
