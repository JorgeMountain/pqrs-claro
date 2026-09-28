"""Explicit, retryable removal of one trashed case; shared library/mail stay intact."""

import json
import re
import shutil
import sqlite3
from contextlib import contextmanager

from .storage import Conflict, now


@contextmanager
def database(root, name):
    path = root / name
    if not path.exists():
        yield None
        return
    conn = sqlite3.connect(path, timeout=15)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def remove_folder(root, parent, identifier):
    # Paths never come from document text. Resolve and check before recursive removal.
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Identificador de archivo no válido para eliminar.")
    base = (root / parent).resolve()
    target = root / parent / identifier
    resolved = target.resolve()
    if base.parent != root.resolve() or resolved.parent != base or resolved == base:
        raise ValueError("La carpeta del expediente está fuera del directorio permitido.")
    if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
        raise ValueError("No se puede eliminar una carpeta enlazada.")
    if target.exists():
        shutil.rmtree(target)


def delete_rows(conn, names, case_id):
    existing = tables(conn)
    for name in names:
        if name in existing:
            conn.execute(f'DELETE FROM "{name}" WHERE case_id=?', (case_id,))


def purge_library(root, case_id):
    with database(root, "biblioteca.sqlite") as conn:
        if conn is None:
            return
        private = [
            sid
            for sid, body in conn.execute("SELECT id,body FROM sources")
            if json.loads(body).get("case_id") == case_id
        ]
        for sid in private:
            remove_folder(root, "library", sid)
            conn.execute(
                "DELETE FROM source_relationships WHERE source_id=? OR target_id=?", (sid, sid)
            )
            conn.execute("DELETE FROM source_reviews WHERE id=?", (sid,))
            conn.execute("DELETE FROM sources WHERE id=?", (sid,))
        delete_rows(conn, ("source_runs", "case_source_collections", "evidence_receipts"), case_id)


def purge_verifications(root, case_id):
    with database(root, "comprobaciones.sqlite") as conn:
        if conn is None:
            return
        conn.execute(
            "DELETE FROM verification_events WHERE target_type='application' AND "
            "target_id IN (SELECT id FROM verification_applications WHERE case_id=?)",
            (case_id,),
        )
        conn.execute("DELETE FROM verification_applications WHERE case_id=?", (case_id,))
        # An explicitly reused verification belongs to other cases' audit trails too.
        unshared = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM verifications WHERE case_id=? AND id NOT IN "
                "(SELECT verification_id FROM verification_applications)",
                (case_id,),
            )
        ]
        for vid in unshared:
            conn.execute(
                "DELETE FROM verification_events WHERE target_type='verification' AND target_id=?",
                (vid,),
            )
            conn.execute("DELETE FROM verifications WHERE id=?", (vid,))


def purge_checkpoints(root, case_id):
    for name, prefix in (
        ("checkpoints.sqlite", case_id + ":"),
        ("source_checkpoints.sqlite", case_id + ":"),
        ("draft_checkpoints.sqlite", case_id + ":"),
        ("review_checkpoints.sqlite", "review:" + case_id + ":"),
    ):
        with database(root, name) as conn:
            if conn is None:
                continue
            for table in ("checkpoints", "writes"):
                if table in tables(conn):
                    conn.execute(
                        f'DELETE FROM "{table}" WHERE thread_id=? OR substr(thread_id,1,?)=?',
                        (case_id, len(prefix), prefix),
                    )


def release_mail(conn, case_id):
    if "gmail_messages" not in tables(conn):
        return
    original = json.loads(
        conn.execute("SELECT body FROM cases WHERE id=?", (case_id,)).fetchone()[0]
    )
    primary_key = original.get("origin", {}).get("mail_key")
    for key, raw in conn.execute(
        "SELECT id,body FROM gmail_messages WHERE case_id=? OR (case_id IS NULL AND id=?)",
        (case_id, primary_key),
    ):
        row = json.loads(raw)
        row["case_id"] = None
        row["import_generation"] = row.get("import_generation", 0) + 1
        for field in ("imported_at", "import_mode", "reported_case_number"):
            row.pop(field, None)
        conn.execute(
            "UPDATE gmail_messages SET case_id=NULL,body=? WHERE id=?",
            (json.dumps(row, ensure_ascii=False), key),
        )


def purge_case(store, case_id, version, lifecycle_revision):
    """Service admission locks are held by the router throughout this operation.

    A durable marker forbids restoring a partially erased case after an I/O error
    or interruption. Retrying the same action finishes the idempotent cleanup.
    Gmail is released only in the final transaction, together with case removal.
    """
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT c.version,l.revision,l.deleted_at FROM cases c "
            "LEFT JOIN case_lifecycle l ON l.case_id=c.id WHERE c.id=?",
            (case_id,),
        ).fetchone()
        if not row:
            raise KeyError("No se encontró el expediente.")
        if not row[2]:
            raise Conflict("Primero mueve el expediente a la papelera.")
        if row[:2] != (version, lifecycle_revision):
            raise Conflict("El expediente cambió. Actualiza la lista y vuelve a intentarlo.")
        conn.execute("INSERT OR IGNORE INTO case_purges VALUES (?,?)", (case_id, now()))
    try:
        remove_folder(store.root, "files", case_id)
        remove_folder(store.root, "oficios", case_id)
        purge_library(store.root, case_id)
        purge_verifications(store.root, case_id)
        purge_checkpoints(store.root, case_id)
        for name, names in (
            ("borradores.sqlite", ("draft_runs",)),
            ("oficios.sqlite", ("office_runs",)),
            (
                "revisiones.sqlite",
                (
                    "review_requests",
                    "review_history",
                    "review_approvals",
                    "response_proposals",
                    "office_workspace",
                ),
            ),
        ):
            with database(store.root, name) as conn:
                if conn is not None:
                    delete_rows(conn, names, case_id)
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            release_mail(conn, case_id)
            delete_rows(
                conn,
                (
                    "preparations",
                    "intake_reviews",
                    "intake_history",
                    "case_management",
                    "management_events",
                    "revisions",
                    "case_lifecycle_events",
                    "case_lifecycle",
                    "case_purges",
                ),
                case_id,
            )
            conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
    except (OSError, sqlite3.Error) as exc:
        raise Conflict(
            "El borrado no terminó. Cierra los archivos abiertos y reintenta "
            "«Eliminar definitivamente» en la papelera."
        ) from exc
    return {"id": case_id, "permanently_deleted": True}
