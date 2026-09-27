"""Connection settings shared by the JEV lab and the FIAGA classifier."""

import os

from dotenv import dotenv_values

from .config import ROOT

MODEL = "typesafe-ai/jev"
ENDPOINT = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"


def get_key():
    key = (
        os.environ.get("AI_GATEWAY_API_KEY")
        or dotenv_values(ROOT / ".env.jev.local", encoding="utf-8-sig").get("AI_GATEWAY_API_KEY")
        or ""
    ).strip()
    return "" if key == "PEGA_AQUI_TU_CLAVE" else key
