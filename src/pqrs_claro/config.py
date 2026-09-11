"""Configuración local; lee la clave autorizada sin copiarla ni registrarla."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT / "data"
    api_key: str = field(default="", repr=False)
    model: str = "gpt-5.6-luna"
    port: int = 8770
    max_upload_mb: int = 20
    max_pages: int = 40
    source_concurrency: int = 3
    draft_concurrency: int = 3

    @classmethod
    def load(cls):
        local = dotenv_values(ROOT / ".env.local")
        key_file = Path(
            os.environ.get("PQRS_CLARO_KEY_FILE")
            or local.get("PQRS_CLARO_KEY_FILE")
            or ROOT.parent / "langgraph-pqrs" / ".env.local"
        )
        shared = dotenv_values(key_file) if key_file.is_file() else {}
        # La configuración de este proyecto tiene prioridad; ningún secreto se escribe.
        key = local.get("OPENAI_API_KEY") or shared.get("OPENAI_API_KEY")
        key = key or os.environ.get("OPENAI_API_KEY", "")
        model = (
            os.environ.get("PQRS_CLARO_MODEL")
            or local.get("PQRS_CLARO_MODEL")
            or shared.get("PQRS_MODEL_IDENTIFICATION")
            or "gpt-5.6-luna"
        )
        data = Path(os.environ.get("PQRS_CLARO_DATA_DIR", str(ROOT / "data")))
        port = int(os.environ.get("PQRS_CLARO_PORT") or local.get("PQRS_CLARO_PORT") or 8770)
        return cls(data_dir=data, api_key=key, model=model, port=port)
