"""Configuración local; lee la clave autorizada sin copiarla ni registrarla."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_SERVICE_TIER = "fast"
MAX_SOURCE_CONCURRENCY = 5


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT / "data"
    api_key: str = field(default="", repr=False)
    model: str = "gpt-6-luna"
    port: int = 8770
    max_upload_mb: int = 20
    max_pages: int = 40
    source_concurrency: int = 5
    draft_concurrency: int = 3
    initial_review_enabled: bool = False
    management_enabled: bool = False
    initial_classification_provider: str = "openai"
    environment_label: str = "PQRS · revisión inicial y confirmación humana"
    semantic_matrix_cache_mb: int = 512
    source_service_tier: str = DEFAULT_SOURCE_SERVICE_TIER

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
            or "gpt-6-luna"
        )
        data = Path(os.environ.get("PQRS_CLARO_DATA_DIR", str(ROOT / "data")))
        port = int(os.environ.get("PQRS_CLARO_PORT") or local.get("PQRS_CLARO_PORT") or 8770)
        source_limit = (os.environ.get("PQRS_CLARO_SOURCE_CONCURRENCY")
                        or local.get("PQRS_CLARO_SOURCE_CONCURRENCY") or cls.source_concurrency)
        try:
            source_concurrency = int(source_limit)
        except ValueError:
            raise ValueError("PQRS_CLARO_SOURCE_CONCURRENCY debe ser un número entero.") from None
        if not 1 <= source_concurrency <= MAX_SOURCE_CONCURRENCY:
            raise ValueError(
                f"PQRS_CLARO_SOURCE_CONCURRENCY debe estar entre 1 y {MAX_SOURCE_CONCURRENCY}."
            )
        draft_concurrency = int(os.environ.get("PQRS_CLARO_DRAFT_CONCURRENCY")
                                or local.get("PQRS_CLARO_DRAFT_CONCURRENCY") or 3)
        if not 1 <= draft_concurrency <= 6:
            raise ValueError("PQRS_CLARO_DRAFT_CONCURRENCY debe estar entre 1 y 6.")
        matrix_cache_mb = int(os.environ.get("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB")
                              or local.get("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB") or 512)
        if not 0 <= matrix_cache_mb <= 1024:
            raise ValueError("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB debe estar entre 0 y 1024.")
        source_service_tier = (os.environ.get("PQRS_CLARO_SOURCE_SERVICE_TIER")
                               or local.get("PQRS_CLARO_SOURCE_SERVICE_TIER")
                               or DEFAULT_SOURCE_SERVICE_TIER).strip().lower()
        if source_service_tier not in {"fast", "default"}:
            raise ValueError("PQRS_CLARO_SOURCE_SERVICE_TIER debe ser fast o default.")
        classifier = (os.environ.get("PQRS_CLARO_CLASSIFICATION_PROVIDER")
                      or local.get("PQRS_CLARO_CLASSIFICATION_PROVIDER") or "openai").strip()
        if classifier not in {"openai", "jev"}:
            raise ValueError("PQRS_CLARO_CLASSIFICATION_PROVIDER debe ser openai o jev.")
        return cls(data_dir=data, api_key=key, model=model, port=port,
                   source_concurrency=source_concurrency, draft_concurrency=draft_concurrency,
                   initial_classification_provider=classifier,
                   semantic_matrix_cache_mb=matrix_cache_mb,
                   source_service_tier=source_service_tier)
