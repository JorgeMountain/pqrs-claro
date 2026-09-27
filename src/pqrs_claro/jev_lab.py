"""Private cloud adapter for the isolated classification lab."""

import time

import httpx
from fastapi import HTTPException

from .jev_client import ENDPOINT, MODEL, get_key


async def predict(text, questions, *, key=None, transport=None):
    key = get_key() if key is None else key
    if not key:
        raise HTTPException(503, "Falta AI_GATEWAY_API_KEY en .env.jev.local.")
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=90, trust_env=False, transport=transport) as client:
            response = await client.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {key}"},
                json={"model": MODEL, "state": text, "questions": questions},
            )
        if response.status_code != 200:
            reason = {
                401: "Revisa la validez de la clave.",
                403: "La clave no tiene permiso para este modelo.",
                402: "Comprueba el saldo o presupuesto de AI Gateway.",
                429: "Se alcanzó un límite de uso; intenta más tarde.",
            }.get(response.status_code, "El proveedor no pudo completar la prueba.")
            try:
                error_type = response.json().get("error", {}).get("type")
            except (ValueError, AttributeError):
                error_type = None
            if error_type == "customer_verification_required":
                reason = (
                    "Vercel exige registrar una tarjeta para habilitar AI Gateway, "
                    "incluso con créditos gratuitos. Configúrala en el panel de AI Gateway."
                )
            raise HTTPException(502, f"JEV (HTTP {response.status_code}): {reason}")
        raw = response.json()
        answers = raw["answers"]
        choice = answers["petition_type"]["choice"]
        rude = answers["rude_language"]["noul"]
        if choice not in questions["petition_type"]["criteria"]:
            raise ValueError("Invalid choice")

        def probability(value):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= 1
            ):
                raise ValueError("Invalid probability")
            return value

        clean = {
            "petition_type": {"type": "choice", "choice": choice},
            "rude_language": {"type": "noul", "noul": probability(rude)},
        }
        for name in clean:
            if "confidence" in answers[name]:
                clean[name]["confidence"] = probability(answers[name]["confidence"])
        if "probabilities" in answers["petition_type"]:
            clean["petition_type"]["probabilities"] = {
                name: probability(value)
                for name, value in answers["petition_type"]["probabilities"].items()
                if name in questions["petition_type"]["criteria"]
            }
        usage = {
            name: max(0, int((raw.get("usage") or {}).get(name, 0)))
            for name in ("input_tokens", "output_tokens")
        }
    except httpx.RequestError:
        raise HTTPException(503, "No se pudo conectar con JEV en la nube.") from None
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise HTTPException(502, "JEV devolvió un formato inesperado.") from None
    return {
        "answers": clean,
        "routing": {"models": dict.fromkeys(questions, "typesafe-ai/jev")},
        "usage": usage,
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
    }
