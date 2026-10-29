"""Embedding CLI settings (environment variables or flags) with validation."""
import os
from dataclasses import dataclass, replace
from pathlib import Path

import db.config  # noqa: F401  (loads the project's .env without overriding real environment variables)
from app.ingestion.config import ConfigError
from app.retrieval.embedder import DEFAULT_MODEL_DIR


@dataclass(frozen=True)
class EmbedConfig:
    min_tokens: int = 20
    batch_size: int = 32
    model_dir: Path = DEFAULT_MODEL_DIR
    retry_attempts: int = 3
    retry_base_seconds: float = 1.0

    def validate(self) -> None:
        if self.min_tokens < 1:
            raise ConfigError("EMBED_MIN_TOKENS must be a positive whole number.")
        if not 1 <= self.batch_size <= 512:
            raise ConfigError("EMBED_BATCH_SIZE must be between 1 and 512.")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number.") from None


def load_config(**overrides) -> EmbedConfig:
    base = EmbedConfig()
    model_dir = os.environ.get("EMBEDDING_MODEL_PATH", "").strip()
    config = replace(base, min_tokens=_env_int("EMBED_MIN_TOKENS", base.min_tokens),
                     batch_size=_env_int("EMBED_BATCH_SIZE", base.batch_size),
                     model_dir=Path(model_dir) if model_dir else base.model_dir)
    config = replace(config, **{k: v for k, v in overrides.items() if v is not None})
    config.validate()
    return config
