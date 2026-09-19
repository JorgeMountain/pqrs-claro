"""Gmail de solo lectura: OAuth con PKCE y credenciales locales protegidas."""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from urllib.parse import urlencode

import httpx

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
REDIRECT = "http://127.0.0.1:8772/api/gmail/oauth/callback"
API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailError(ValueError):
    pass


class SecretStore:
    """DPAPI por usuario en Windows. Sin almacenamiento plano como alternativa."""

    def __init__(self, root):
        self.root = root

    def read(self, name):
        path = self.root / (name + ".protected")
        if not path.exists():
            return {}
        try:
            import win32crypt

            raw = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1]
            return json.loads(raw)
        except Exception:
            raise GmailError(
                "No se pudo abrir la conexión protegida de Gmail en este usuario."
            ) from None

    def write(self, name, value):
        try:
            import win32crypt

            data = win32crypt.CryptProtectData(
                json.dumps(value).encode(), "PQRS Claro Gmail", None, None, None, 0
            )
            self.root.mkdir(parents=True, exist_ok=True)
            temp = self.root / (name + ".tmp")
            temp.write_bytes(data)
            os.replace(temp, self.root / (name + ".protected"))
        except Exception:
            raise GmailError("No se pudo guardar la conexión con protección de Windows.") from None

    def delete(self, name):
        (self.root / (name + ".protected")).unlink(missing_ok=True)


class GmailAuth:
    def __init__(self, root, *, vault=None, transport=None):
        self.vault = vault or SecretStore(root)
        self.lock = threading.RLock()
        self.flows = {}
        self.http = httpx.Client(timeout=30, trust_env=False, transport=transport)

    def _request(self, method, url, **kwargs):
        try:
            with self.http.stream(method, url, **kwargs) as response:
                if response.status_code >= 400:
                    messages = {
                        400: "Google no aceptó la autorización. Vuelve a conectar la cuenta.",
                        401: "La autorización venció. Vuelve a conectar Gmail.",
                        403: "Google no permite leer el correo. Revisa Gmail API y los permisos.",
                        404: "El mensaje ya no está disponible en Gmail.",
                        429: "Gmail alcanzó un límite temporal. Reintenta más tarde.",
                    }
                    raise GmailError(
                        messages.get(response.status_code, "Gmail no está disponible. Reintenta.")
                    )
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 60 * 1024 * 1024:
                        raise GmailError("El mensaje supera el tamaño admitido para importar.")
                    chunks.append(chunk)
                return json.loads(b"".join(chunks))
        except (httpx.HTTPError, json.JSONDecodeError):
            raise GmailError(
                "No se pudo consultar Google. Revisa la conexión y reintenta."
            ) from None

    def configure(self, raw):
        try:
            data = json.loads(raw)["installed"]
            client_id, secret = data["client_id"], data["client_secret"]
            if not (
                isinstance(client_id, str)
                and len(client_id) < 300
                and client_id.endswith(".apps.googleusercontent.com")
                and isinstance(secret, str)
                and 5 < len(secret) < 300
            ):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise GmailError(
                "Selecciona el JSON de un cliente OAuth de tipo Aplicación de escritorio."
            ) from None
        with self.lock:
            if self.vault.read("token"):
                raise GmailError(
                    "Desconecta la cuenta antes de cambiar la configuración de Google."
                )
            # Nunca usar endpoints suministrados en un archivo de configuración.
            self.vault.write("client", {"client_id": client_id, "client_secret": secret})
            self.flows.clear()

    def status(self):
        with self.lock:
            token = self.vault.read("token")
            return {
                "configured": bool(self.vault.read("client")),
                "connected": bool(token),
                "account": token.get("account"),
                "label": "PQRS-Pruebas",
                "read_only": True,
            }

    def authorize(self):
        with self.lock:
            client = self.vault.read("client")
            if not client:
                raise GmailError("Configura primero el cliente de Google con su archivo JSON.")
            verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            self.flows = {state: {"verifier": verifier, "expires": time.time() + 600}}
            params = {
                "client_id": client["client_id"],
                "redirect_uri": REDIRECT,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent select_account",
                "state": state,
                "code_challenge": challenge.decode().rstrip("="),
                "code_challenge_method": "S256",
            }
            return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}

    def callback(self, state, code, error=None):
        with self.lock:
            flow = self.flows.pop(state, None)
            if not flow or flow["expires"] < time.time():
                raise GmailError(
                    "La conexión expiró o no fue iniciada aquí. Vuelve a Conectar Gmail."
                )
            if error or not code:
                raise GmailError(
                    "No se autorizó Gmail. Puedes volver a intentarlo desde el sistema."
                )
            client = self.vault.read("client")
            token = self._request(
                "POST",
                "https://oauth2.googleapis.com/token",
                data={
                    **client,
                    "code": code,
                    "redirect_uri": REDIRECT,
                    "grant_type": "authorization_code",
                    "code_verifier": flow["verifier"],
                },
            )
            if SCOPE not in token.get("scope", "").split() or not token.get("refresh_token"):
                raise GmailError("Autoriza la lectura del correo para mantener la conexión local.")
            profile = self._request(
                "GET",
                API + "/profile",
                headers={"Authorization": "Bearer " + token["access_token"]},
            )
            account = str(profile.get("emailAddress", "")).strip().lower()
            if not account or "@" not in account:
                raise GmailError("Google no permitió verificar la cuenta conectada.")
            self.vault.write(
                "token",
                {
                    "account": account,
                    "access_token": token["access_token"],
                    "refresh_token": token["refresh_token"],
                    "expires": time.time() + int(token.get("expires_in", 3600)),
                },
            )
            return account

    def get(self, path, *, params=None, account=None):
        with self.lock:
            token = self.vault.read("token")
            if not token:
                raise GmailError("Conecta tu cuenta de Gmail para consultar mensajes.")
            if account and token["account"] != account:
                raise GmailError("La cuenta conectada cambió. Vuelve a consultar la bandeja.")
            if token["expires"] < time.time() + 60:
                fresh = self._request(
                    "POST",
                    "https://oauth2.googleapis.com/token",
                    data={
                        **self.vault.read("client"),
                        "grant_type": "refresh_token",
                        "refresh_token": token["refresh_token"],
                    },
                )
                token.update(
                    access_token=fresh["access_token"],
                    expires=time.time() + int(fresh.get("expires_in", 3600)),
                )
                self.vault.write("token", token)
            return self._request(
                "GET",
                API + path,
                params=params,
                headers={"Authorization": "Bearer " + token["access_token"]},
            )

    def disconnect(self):
        with self.lock:
            self.vault.delete("token")
            self.flows.clear()

    def close(self):
        self.http.close()
