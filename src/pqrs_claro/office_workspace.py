"""Borrador editable sin aprobación ficticia; el exportador mantiene su contrato."""

import json
from copy import deepcopy
from datetime import date

from pydantic import Field, field_validator

from .models import StrictModel
from .office_models import OfficeMetadata
from .office_renderer import _blocks
from .office_structure import request_fragments
from .review_models import Actor, ReviewEdit, ReviewParagraph
from .storage import Conflict, now


class WorkingMetadata(OfficeMetadata):
    institution: str = Field(default="", max_length=200)
    city: str = Field(default="Medellín", max_length=120)
    issue_date: date = Field(default_factory=date.today)
    recipient: str = Field(default="", max_length=300)
    subject: str = Field(default="", max_length=500)
    signer_name: str = Field(default="", max_length=200)
    signer_role: str = Field(default="", max_length=200)

    @field_validator("city")
    @classmethod
    def default_city(cls, value: str) -> str:
        return value.strip() or "Medellín"


class WorkingRow(StrictModel):
    request_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1, strict=True)
    paragraphs: list[ReviewParagraph] = Field(max_length=30)


class WorkingInput(StrictModel):
    revision: int = Field(ge=0, strict=True)
    metadata: WorkingMetadata
    requests: list[WorkingRow] = Field(max_length=300)
    edited_by: Actor
    attachment_source_ids: list[str] = Field(default_factory=list, max_length=20)


def _table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS office_workspace (case_id TEXT PRIMARY KEY, "
        "revision INTEGER NOT NULL, body TEXT NOT NULL)"
    )


def get_workspace(service, case_id):
    case = service.cases.get(case_id)
    with service.reviews_service.store.connect() as conn:
        _table(conn)
        saved = conn.execute(
            "SELECT body FROM office_workspace WHERE case_id=?", (case_id,)
        ).fetchone()
    state = json.loads(saved[0]) if saved else {"revision": 0}
    identification = case.get("identification") or {}
    metadata = WorkingMetadata.model_validate(
        state.get("metadata")
        or {
            "institution": "Universidad de Antioquia",
            "department": "Facultad de Ingeniería",
            "recipient": identification.get("requester") or "",
            "subject": identification.get("subject") or "",
            "petition_number": case.get("origin", {}).get("reported_case_number", ""),
        }
    ).model_dump(mode="json")
    letterhead = service._letterhead()
    if letterhead:
        service._letterhead_metadata(metadata, letterhead)
    rows = service.reviews_service.get(case_id)["requests"]
    # Las referencias internas permiten reunir el mismo contexto exactamente como
    # en el oficio; esta vista no certifica ni aprueba ese respaldo.
    requests, refs = [], {}
    for row in rows:
        paragraphs = []
        for p in row["paragraphs"]:
            ids = [("source", k) for k in p.get("cited_chunk_ids", [])]
            ids += [(row["request_id"], k) for k in p.get("cited_fact_ids", [])]
            numbers = [refs.setdefault(k, len(refs) + 1) for k in ids]
            paragraphs.append({**p, "reference_numbers": numbers})
        if not paragraphs:
            paragraphs = [{"text": "[Respuesta pendiente de preparar]", "reference_numbers": []}]
        request = row.get("request_snapshot") or {}
        fragments = request_fragments(request)
        requests.append(
            {
                **{k: row[k] for k in ("request_id", "label", "title", "description")},
                "parent_id": request.get("parent_id"),
                "original_fragments": fragments,
                "original_text": "\n\n".join(f["text"] for f in fragments) or row["description"],
                "paragraphs": paragraphs,
            }
        )
    display = deepcopy(metadata)
    for key, label in {
        "city": "Ciudad",
        "recipient": "Destinatario",
        "subject": "Asunto",
        "signer_name": "Nombre de quien suscribe",
        "signer_role": "Cargo",
    }.items():
        display[key] = display[key] or f"[{label}]"
    options = {}
    for row in rows:
        cited = {c for p in row["paragraphs"] for c in p.get("cited_chunk_ids", [])}
        for support in row.get("available_supports", []):
            if support["chunk_id"] in cited:
                try:
                    source = service.library.get(support["source_id"], case_id=case_id)["source"]
                    options[source["id"]] = {
                        **{k: source[k] for k in ("title", "filename", "sha256")},
                        "source_id": source["id"],
                        "size": service.library.original(source["id"], case_id).stat().st_size,
                    }
                except (KeyError, ValueError):
                    continue
    selected = state.get("attachment_source_ids", [])
    document = {
        "metadata": display,
        "petition_subject": identification.get("subject") or "",
        "requests": requests,
        "references": [{"number": n} for n in refs.values()],
        "attachments": [options[sid] for sid in selected if sid in options],
    }
    if letterhead:
        document["letterhead"] = letterhead.public()
    blocks = _blocks(document, working=True) if requests else []
    return {
        **state,
        "case_id": case_id,
        "metadata": metadata,
        "requests": rows,
        "blocks": blocks,
        "letterhead": letterhead.public() if letterhead else None,
        "attachment_options": list(options.values()),
        "attachment_source_ids": selected,
    }


def save_workspace(service, case_id, body):
    reviews = service.reviews_service
    with reviews.lock, service.library.lock:
        service.cases.assert_open(case_id)
        service.cases.get(case_id)
        ids = [r.request_id for r in body.requests]
        if len(ids) != len(set(ids)):
            raise ValueError("Hay solicitudes repetidas en el documento.")
        current = reviews.get(case_id)["requests"]
        if set(ids) != {r["request_id"] for r in current}:
            raise Conflict("La composición del oficio cambió. Recarga el borrador.")
        if any((case_id, rid) in reviews.active for rid in ids):
            raise Conflict("Espera a que termine la comprobación en curso antes de guardar.")
        prepared = []
        for item in body.requests:
            old = reviews._row(case_id, item.request_id, item.revision, fresh=False)
            row = reviews.edit(
                case_id,
                item.request_id,
                ReviewEdit(
                    revision=item.revision,
                    edited_by=body.edited_by,
                    paragraphs=item.paragraphs,
                ),
                prepare_only=True,
            )
            if old != row:
                prepared.append((row, item.revision))
        metadata = body.metadata.model_dump(mode="json")
        letterhead = service._letterhead()
        if letterhead:
            service._letterhead_metadata(metadata, letterhead)
        options = {s["source_id"] for s in get_workspace(service, case_id)["attachment_options"]}
        if (
            len(set(body.attachment_source_ids)) != len(body.attachment_source_ids)
            or not set(body.attachment_source_ids) <= options
        ):
            raise ValueError("Selecciona anexos disponibles entre las fuentes citadas.")
        state = {
            "revision": body.revision + 1,
            "metadata": metadata,
            "attachment_source_ids": body.attachment_source_ids,
            "edited_by": body.edited_by,
            "updated_at": now(),
        }
        with reviews.store.connect() as conn:
            _table(conn)
            conn.execute("BEGIN IMMEDIATE")
            saved = conn.execute(
                "SELECT revision FROM office_workspace WHERE case_id=?", (case_id,)
            ).fetchone()
            if (saved[0] if saved else 0) != body.revision:
                raise Conflict(
                    "Otra ventana guardó este oficio. Tu edición local se conserva; "
                    "recarga antes de guardar."
                )
            # Comprobar todas las revisiones antes de escribir; todo se confirma junto.
            for item in body.requests:
                found = conn.execute(
                    "SELECT revision FROM review_requests WHERE case_id=? AND request_id=?",
                    (case_id, item.request_id),
                ).fetchone()
                if not found or found[0] != item.revision:
                    raise Conflict("Una respuesta cambió. Recarga el oficio antes de guardar.")
            for row, expected in prepared:
                row.update(revision=expected + 1, updated_at=state["updated_at"])
                encoded = json.dumps(row, ensure_ascii=False)
                conn.execute(
                    "UPDATE review_requests SET revision=?,body=? WHERE case_id=? AND request_id=?",
                    (row["revision"], encoded, case_id, row["request_id"]),
                )
                history = {
                    "event": "edited",
                    "actor": body.edited_by,
                    "created_at": row["updated_at"],
                    "revision": row["revision"],
                    "body": row,
                }
                conn.execute(
                    "INSERT INTO review_history VALUES (?,?,?,?)",
                    (
                        case_id,
                        row["request_id"],
                        row["revision"],
                        json.dumps(history, ensure_ascii=False),
                    ),
                )
            conn.execute(
                "INSERT INTO office_workspace VALUES (?,?,?) ON CONFLICT(case_id) "
                "DO UPDATE SET revision=excluded.revision,body=excluded.body",
                (case_id, state["revision"], json.dumps(state, ensure_ascii=False)),
            )
        return get_workspace(service, case_id)
