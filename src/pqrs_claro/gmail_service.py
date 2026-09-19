"""Bandeja Gmail acotada y entrada idempotente al expediente existente."""

import base64
import hashlib
import json
import re
import threading
from uuid import NAMESPACE_URL, uuid5

from .gmail_auth import GmailAuth, GmailError
from .gmail_content import body_pdf, case_numbers, parse_message
from .storage import now, write_original


def message_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise GmailError("Identificador de mensaje inválido.")
    return value


class GmailService:
    def __init__(self, settings, cases, library, validate_pdf, *, auth=None):
        self.cases, self.library, self.settings = cases, library, settings
        self.root = settings.data_dir / "gmail"
        self.auth = auth or GmailAuth(self.root / "connection")
        self.validate_pdf = validate_pdf
        self.lock = threading.RLock()
        with cases.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS gmail_messages ("
                "id TEXT PRIMARY KEY, account TEXT, message_id TEXT, "
                "case_id TEXT, body TEXT, UNIQUE(account,message_id))"
            )

    def account(self, expected=None):
        account = self.auth.status().get("account")
        if not account:
            raise GmailError("Conecta tu cuenta de Gmail.")
        if expected and account != expected:
            raise GmailError("La cuenta conectada cambió. Vuelve a consultar la bandeja.")
        return account

    @staticmethod
    def key(account, mid):
        return uuid5(NAMESPACE_URL, "pqrs-claro:gmail:" + account + ":" + mid).hex

    def row(self, key):
        with self.cases.connect() as conn:
            row = conn.execute("SELECT body FROM gmail_messages WHERE id=?", (key,)).fetchone()
        if not row:
            raise KeyError(key)
        return json.loads(row[0])

    def save(self, row):
        with self.cases.connect() as conn:
            conn.execute(
                "INSERT INTO gmail_messages VALUES (?,?,?,?,?) ON CONFLICT(id) "
                "DO UPDATE SET case_id=excluded.case_id,body=excluded.body",
                (
                    row["key"],
                    row["account"],
                    row["id"],
                    row.get("case_id"),
                    json.dumps(row, ensure_ascii=False),
                ),
            )

    def inbox(self, label, page_token=""):
        with self.lock:
            account = self.account()
            labels = self.auth.get("/labels", account=account).get("labels", [])
            selected = next((item for item in labels if item["name"] == label), None)
            if not selected:
                return {
                    "account": account,
                    "messages": [],
                    "next_page": None,
                    "notice": f"Crea la etiqueta «{label}» en Gmail y aplícala a tus pruebas.",
                }
            page = self.auth.get(
                "/messages",
                account=account,
                params={
                    "labelIds": selected["id"],
                    "maxResults": 10,
                    "pageToken": page_token,
                },
            )
            messages = []
            for item in page.get("messages", []):
                mid = message_id(item["id"])
                detail = self.auth.get(
                    "/messages/" + mid,
                    account=account,
                    params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in detail.get("payload", {}).get("headers", [])
                }
                entry = {
                    "id": mid,
                    "subject": headers.get("subject", "Sin asunto")[:2000],
                    "sender": headers.get("from", "")[:2000],
                    "date": headers.get("date", "")[:2000],
                    "case_id": None,
                }
                try:
                    entry["case_id"] = self.row(self.key(account, mid)).get("case_id")
                except KeyError:
                    pass
                entry["case_numbers"] = case_numbers(entry["subject"])
                messages.append(entry)
            return {
                "account": account,
                "messages": messages,
                "next_page": page.get("nextPageToken"),
                "notice": "",
            }

    def detail(self, mid, account):
        with self.lock:
            account = self.account(account)
            mid = message_id(mid)
            key = self.key(account, mid)
            try:
                row = self.row(key)
            except KeyError:
                metadata = self.auth.get(
                    "/messages/" + mid, account=account, params={"format": "raw"}
                )
                try:
                    encoded = metadata["raw"]
                    raw = base64.b64decode(
                        encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                    )
                except (KeyError, ValueError):
                    raise GmailError("Gmail no devolvió un correo original válido.") from None
                public, _ = parse_message(raw, {**metadata, "id": mid})
                row = {
                    **public,
                    "key": key,
                    "account": account,
                    "case_id": None,
                    "captured_at": now(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                folder = self.root / "messages" / key
                folder.mkdir(parents=True, exist_ok=True)
                write_original(folder / "original.eml", raw)
                self.save(row)
            with self.cases.connect() as conn:
                others = conn.execute(
                    "SELECT body FROM gmail_messages WHERE account=? AND case_id IS NOT NULL",
                    (account,),
                ).fetchall()
            suggestions = {}
            for other in others:
                value = json.loads(other[0])
                if row["case_number"] and value.get("reported_case_number") == row["case_number"]:
                    suggestions[value["case_id"]] = {
                        "case_id": value["case_id"],
                        "subject": value["subject"],
                    }
            return {**row, "related_cases": list(suggestions.values())}

    def raw(self, row):
        raw = (self.root / "messages" / row["key"] / "original.eml").read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise GmailError("La copia local del correo cambió. No se utilizará para importar.")
        return raw

    def attachment(self, key, attachment_id):
        row = self.row(key)
        _, contents = parse_message(self.raw(row), {"id": row["id"]})
        item = next((a for a in row["attachments"] if a["id"] == attachment_id), None)
        if not item or attachment_id not in contents:
            raise KeyError(attachment_id)
        return item, contents[attachment_id]

    def import_message(self, mid, body):
        with self.lock:
            # Disconnect/account replacement cannot interleave with an import.
            with self.auth.lock:
                row = self.detail(mid, body.account)
                row.pop("related_cases", None)
                if row.get("case_id"):
                    return {"case_id": row["case_id"], "duplicate": True, "linked": True}
                if body.mode == "link":
                    if not body.target_case_id:
                        raise GmailError("Selecciona el expediente al que pertenece el correo.")
                    case = self.cases.get(body.target_case_id)
                    linked = True
                else:
                    if body.mode == "body":
                        if not body.body_confirmed:
                            raise GmailError(
                                "Confirma que el mensaje contiene la petición completa."
                            )
                        pdf, filename = body_pdf(row), "Petición desde correo.pdf"
                    else:
                        item, pdf = self.attachment(row["key"], body.attachment_id or "")
                        if not item["pdf"]:
                            raise GmailError("Selecciona un adjunto PDF como petición principal.")
                        filename = item["name"]
                    self.validate_pdf(pdf, self.settings)
                    # Deterministic ID recovers a crash between case creation and receipt save.
                    cid = self.key(body.account, mid)
                    try:
                        case = self.cases.get(cid)
                    except KeyError:
                        origin = {
                            "kind": "gmail",
                            "mail_key": row["key"],
                            "account": body.account,
                            "message_id": mid,
                            "thread_id": row.get("thread_id"),
                            "subject": row["subject"],
                            "sender": row["sender"],
                            "email_received_at": row["email_received_at"],
                            "reported_case_number": body.case_number.strip(),
                            "primary": body.mode,
                            "attachment_id": body.attachment_id,
                        }
                        case = self.cases.create(filename, pdf, case_id=cid, origin=origin)
                    self.library.link_collections(
                        cid, [c["id"] for c in self.library.collections()]
                    )
                    linked = False
                row.update(
                    case_id=case["id"],
                    imported_at=now(),
                    reported_case_number=body.case_number.strip(),
                    import_mode=body.mode,
                )
                self.save(row)
                return {"case_id": case["id"], "duplicate": False, "linked": linked}

    def case_messages(self, case_id):
        self.cases.get(case_id)
        with self.cases.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM gmail_messages WHERE case_id=?", (case_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self):
        self.auth.close()
