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
    procedure_scope_pilot: bool = False
    independent_ocr_read: bool = True

    @classmethod
    def load(cls):
        local = dotenv_values(ROOT / ".env.local")
        key_file = Path(
            os.environ.get("PQRS_CLARO_KEY_FILE")
            or local.get("PQRS_CLARO_KEY_FILE")
            or ROOT.parent / "langgraph-pqrs" / ".env.local"
        )
        shared = dotenv_values(key_file) if key_file.is_file() else {}
        # El entorno explícito tiene prioridad sobre .env.local y claves compartidas.
        key = (
            os.environ.get("OPENAI_API_KEY")
            or local.get("OPENAI_API_KEY")
            or shared.get("OPENAI_API_KEY")
            or ""
        )
        model = (
            os.environ.get("PQRS_CLARO_MODEL")
            or local.get("PQRS_CLARO_MODEL")
            or shared.get("PQRS_MODEL_IDENTIFICATION")
            or "gpt-6-luna"
        )
        data = Path(
            os.environ.get("PQRS_CLARO_DATA_DIR")
            or local.get("PQRS_CLARO_DATA_DIR")
            or str(ROOT / "data")
        )
        raw_port = os.environ.get("PQRS_CLARO_PORT") or local.get("PQRS_CLARO_PORT") or 8770
        try:
            port = int(raw_port)
        except ValueError:
            raise ValueError("PQRS_CLARO_PORT debe ser un número entero.") from None
        if not 1 <= port <= 65535:
            raise ValueError("PQRS_CLARO_PORT debe estar entre 1 y 65535.")
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
        raw_draft = (
            os.environ.get("PQRS_CLARO_DRAFT_CONCURRENCY")
            or local.get("PQRS_CLARO_DRAFT_CONCURRENCY")
            or 3
        )
        try:
            draft_concurrency = int(raw_draft)
        except ValueError:
            raise ValueError("PQRS_CLARO_DRAFT_CONCURRENCY debe ser un número entero.") from None
        if not 1 <= draft_concurrency <= 6:
            raise ValueError("PQRS_CLARO_DRAFT_CONCURRENCY debe estar entre 1 y 6.")
        raw_cache = (
            os.environ.get("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB")
            or local.get("PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB")
            or 512
        )
        try:
            matrix_cache_mb = int(raw_cache)
        except ValueError:
            raise ValueError(
                "PQRS_CLARO_SEMANTIC_MATRIX_CACHE_MB debe ser un número entero."
            ) from None
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
        procedure_scope_value = (
            os.environ.get("PQRS_PROCEDURE_SCOPE_PILOT")
            or local.get("PQRS_PROCEDURE_SCOPE_PILOT") or "false"
        ).strip().lower()
        if procedure_scope_value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("PQRS_PROCEDURE_SCOPE_PILOT debe indicar true o false.")
        procedure_scope_pilot = procedure_scope_value in {"true", "1", "yes", "on"}
        independent = (os.environ.get("PQRS_CLARO_INDEPENDENT_OCR_READ")
                       or local.get("PQRS_CLARO_INDEPENDENT_OCR_READ") or "1").strip().lower()
        if independent not in {"0", "1", "false", "true"}:
            raise ValueError("PQRS_CLARO_INDEPENDENT_OCR_READ debe indicar 1 o 0.")
        return cls(data_dir=data, api_key=key, model=model, port=port,
                   source_concurrency=source_concurrency, draft_concurrency=draft_concurrency,
                   initial_classification_provider=classifier,
                   semantic_matrix_cache_mb=matrix_cache_mb,
                   source_service_tier=source_service_tier,
                   procedure_scope_pilot=procedure_scope_pilot,
                   independent_ocr_read=independent in {"true", "1"})
