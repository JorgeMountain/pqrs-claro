"""TypeSafe JEV 1.14 classifies identified requests; no research or model fallback."""

import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

from .classification_questions import QUESTIONS
from .config import ROOT
from .models import DomainError, Page, source_quote
from .performance_metrics import operation, record_jev_attempt, submit_context
from .source_context import MAX_QUOTE_CHARACTERS

MODEL = "jev-1.14.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
CLASSIFICATION_VERSION = 2
MAX_CONCURRENT_REQUESTS = 2
# A local byte budget, not a claimed provider limit. Reject instead of truncating.
MAX_REQUEST_BYTES = 256_000
MAX_RETRY_AFTER_SECONDS = 5.0
SCOPE = (
    "Clasifica exclusivamente la solicitud con identificador {id} de state.requests. "
    "Usa su título, descripción, extractos originales y contexto, "
    "conservando condiciones y alcance. "
    "El contexto puede contener otras solicitudes: "
    "no clasifiques esas otras solicitudes en lugar de esta. "
    "Clasifica lo que pide, sin evaluar su evidencia, viabilidad o respuesta. "
    "No resuelvas la petición. "
)
CONTEXT_GROUPS = ("ancestors", "children", "referenced_requests", "preceding_section")
CONTEXT_FIELDS = (
    "version",
    "target_request_id",
    "origin",
    "subject",
    "document_date",
    "preceding_section_basis",
    "omitted_request_ids",
    "truncated",
)
ENTRY_FIELDS = (
    "id",
    "label",
    "title",
    "parent_id",
    "description",
    "description_truncated",
    "additional_source_ref_count",
)


def get_key():
    """Read only the direct TypeSafe key from the authorized local configuration."""
    key = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    if not key:
        local = dotenv_values(ROOT / ".env.local", encoding="utf-8-sig")
        configured = os.environ.get("PQRS_CLARO_JEV_KEY_FILE") or local.get(
            "PQRS_CLARO_JEV_KEY_FILE"
        )
        path = Path(configured).expanduser() if configured else ROOT / ".env.jev.local"
        if not path.is_absolute():
            path = ROOT / path
        key = (dotenv_values(path, encoding="utf-8-sig").get("TYPESAFE_API_KEY") or "").strip()
    return "" if key == "PEGA_AQUI_TU_CLAVE" else key


def _references(references, pages, *, context=False):
    result = []
    for reference in references:
        coordinates = {key: reference[key] for key in ("page", "line_start", "line_end")}
        quote = source_quote(pages, **coordinates)
        if context and reference.get("quote_truncated"):
            # Preserve the existing source_context budget and its explicit flag.
            quote = quote[:MAX_QUOTE_CHARACTERS]
        clean = {**coordinates, "quote": quote}
        if context and "quote_truncated" in reference:
            clean["quote_truncated"] = reference["quote_truncated"]
        result.append(clean)
    return result


def _context(value, pages):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid request context")
    result = {key: deepcopy(value[key]) for key in CONTEXT_FIELDS if key in value}
    for group in CONTEXT_GROUPS:
        if group not in value:
            continue
        result[group] = [
            {
                **{key: deepcopy(entry[key]) for key in ENTRY_FIELDS if key in entry},
                "source_refs": _references(entry.get("source_refs", []), pages, context=True),
            }
            for entry in value[group]
        ]
    if "unresolved_references" in value:
        result["unresolved_references"] = [
            {
                key: deepcopy(entry[key])
                for key in ("label_number", "reason", "candidate_request_ids")
                if key in entry
            }
            for entry in value["unresolved_references"]
        ]
    return result


def classification_requests(payload):
    """Project already enriched requests and rebuild quoted text from original pages."""
    pages = [Page.model_validate(page) for page in payload["pages"]]
    originals = payload["identification"]["requests"]
    ids = [request["id"] for request in originals]
    if (
        not ids
        or len(ids) != len(set(ids))
        or any(not isinstance(ident, str) or not ident.strip() for ident in ids)
    ):
        raise DomainError("La clasificación requiere peticiones con identificadores únicos.")
    return [
        {
            "id": request["id"],
            "label": request.get("label"),
            "title": request["title"],
            "description": request["description"],
            "source_refs": _references(request["source_refs"], pages),
            "context": _context(request.get("context"), pages),
        }
        for request in originals
    ]


def _probability(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("Invalid probability")
    return value


def parse_decision(raw, request_id):
    if raw.get("model") != MODEL:
        raise ValueError("Unexpected model")
    if set(raw["answers"]) != {request_id}:
        raise ValueError("Incomplete or foreign answer ids")
    answer = raw["answers"][request_id]
    criteria = QUESTIONS["petition_type"]["criteria"]
    if answer.get("type") != "choice" or answer.get("choice") not in criteria:
        raise ValueError("Invalid decision")
    if set(answer["probabilities"]) != set(criteria):
        raise ValueError("Incomplete probability distribution")
    probabilities = {key: _probability(value) for key, value in answer["probabilities"].items()}
    if abs(sum(probabilities.values()) - 1) > 0.02:
        raise ValueError("Invalid probability distribution")
    return {
        "choice": answer["choice"],
        "confidence": _probability(answer["confidence"]),
        "probabilities": probabilities,
    }


def retry_delay(value):
    delay = 1.0
    if value:
        try:
            delay = float(value)
        except (TypeError, ValueError):
            try:
                until = parsedate_to_datetime(value)
                until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
                delay = (until - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = 1.0
    if not math.isfinite(delay):
        delay = 1.0
    return min(MAX_RETRY_AFTER_SECONDS, max(0.0, delay))


def _http_error(status):
    reason = {
        401: "Revisa la clave de TypeSafe.",
        403: "La clave no tiene permiso para este modelo.",
        402: "Revisa el saldo o presupuesto de TypeSafe.",
        429: "Se alcanzó un límite de uso. Reintenta más tarde.",
    }.get(status, "El servicio no pudo completar la clasificación. Reintenta más tarde.")
    return DomainError(f"JEV no pudo clasificar (HTTP {status}). {reason}")


class JevPetitionClassifier:
    def __init__(self, *, key=None, transport=None):
        self.key = get_key() if key is None else key
        self.transport = transport

    @staticmethod
    def body(request):
        return {
            "model": MODEL,
            "state": {"requests": [request]},
            "questions": {
                request["id"]: {
                    **QUESTIONS["petition_type"],
                    "instructions": SCOPE.format(id=request["id"])
                    + QUESTIONS["petition_type"]["instructions"],
                }
            },
        }

    def _classify_one(self, client, request):
        body = self.body(request)
        with operation("identification.classify", request_id=request["id"]):
            for attempt in range(2):
                started = time.perf_counter()
                status, error_type, http_status, usage = "transport_error", None, None, None
                delay = None
                try:
                    response = client.post(
                        ENDPOINT, headers={"Authorization": f"Bearer {self.key}"}, json=body
                    )
                    http_status = response.status_code
                    if http_status != 200:
                        status = "http_error"
                        if attempt == 0 and (http_status == 429 or 500 <= http_status < 600):
                            delay = retry_delay(response.headers.get("Retry-After"))
                        else:
                            raise _http_error(http_status)
                    else:
                        status = "invalid_response"
                        raw = response.json()
                        usage = raw.get("usage") if isinstance(raw, dict) else None
                        result = parse_decision(raw, request["id"])
                        status = "ok"
                        return result
                except httpx.TransportError as exc:
                    error_type = type(exc).__name__
                    if attempt == 0:
                        delay = 1.0
                    else:
                        raise DomainError(
                            "No se pudo conectar con JEV para clasificar las peticiones. "
                            "Las peticiones siguen guardadas; puedes reintentar."
                        ) from None
                except DomainError:
                    error_type = "HTTPStatusError"
                    raise
                except (ValueError, KeyError, TypeError, AttributeError):
                    error_type = "InvalidResponse"
                    raise DomainError(
                        "JEV devolvió una clasificación incompleta o inválida. "
                        "Las peticiones siguen guardadas; puedes reintentar."
                    ) from None
                finally:
                    record_jev_attempt(
                        model=MODEL,
                        seconds=time.perf_counter() - started,
                        status=status,
                        error_type=error_type,
                        usage=usage,
                        retry=attempt > 0,
                        http_status=http_status,
                    )
                if delay is not None:
                    time.sleep(delay)
        raise DomainError("JEV no completó la clasificación.")

    def classify(self, payload):
        if not self.key:
            raise DomainError(
                "Configura TYPESAFE_API_KEY o PQRS_CLARO_JEV_KEY_FILE para clasificar con JEV."
            )
        try:
            requests = classification_requests(payload)
            # Validate every local payload before starting any request.
            for request in requests:
                size = len(json.dumps(self.body(request), ensure_ascii=False).encode("utf-8"))
                if size > MAX_REQUEST_BYTES:
                    raise DomainError(
                        f"La petición {request['id']} y su contexto superan el límite local "
                        f"de {MAX_REQUEST_BYTES} bytes para clasificar con JEV. "
                        "No se ha recortado ni enviado el texto."
                    )
        except DomainError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DomainError(
                "Las peticiones o su contexto no tienen un formato válido para clasificar."
            ) from None

        decisions = {}
        with httpx.Client(
            timeout=90, trust_env=False, follow_redirects=False, transport=self.transport
        ) as client:
            with ThreadPoolExecutor(
                max_workers=MAX_CONCURRENT_REQUESTS, thread_name_prefix="jev-classification"
            ) as pool:
                futures = {
                    submit_context(pool, self._classify_one, client, request): request["id"]
                    for request in requests
                }
                try:
                    for future in as_completed(futures):
                        decisions[futures[future]] = future.result()
                except Exception:
                    for future in futures:
                        future.cancel()
                    raise
        if set(decisions) != {request["id"] for request in requests}:
            raise DomainError("La clasificación no cubre exactamente las peticiones.")
        return {request["id"]: decisions[request["id"]] for request in requests}
