"""Ingestion settings: defaults, environment variables, validation and the chunking_version string."""
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import db.config  # noqa: F401  (loads the project's .env without overriding real environment variables)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]

TOKENIZER_NAME = "sentence-transformers/all-MiniLM-L6-v2"
TOKENIZER_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_TOKEN_LIMIT = 256  # all-MiniLM-L6-v2 truncates its input at 256 word pieces (special tokens included)
PIPELINE_VERSION = "p1"  # bump whenever extraction, cleaning or chunking logic changes


class ConfigError(ValueError):
    """Invalid ingestion configuration (the CLI exits with code 2)."""


@dataclass(frozen=True)
class IngestConfig:
    chunk_target: int = 220
    chunk_max: int = 250
    chunk_overlap: int = 40
    low_text_min_chars: int = 50
    needs_ocr_ratio: float = 0.30
    header_footer_ratio: float = 0.30
    margin_fraction: float = 0.10
    max_pdf_mb: int = 50
    max_pdf_pages: int = 500
    allow_over_limit: bool = False
    papers_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "papers")
    tokenizer_path: Path = field(default_factory=lambda: BACKEND_DIR / "models" / "all-MiniLM-L6-v2" / "tokenizer.json")
    report_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "ingestion_reports")

    def validate(self) -> list[str]:
        """Raises ConfigError for invalid values; returns warnings for risky ones."""
        warnings: list[str] = []
        for name in ("chunk_target", "chunk_max", "chunk_overlap", "low_text_min_chars", "max_pdf_mb", "max_pdf_pages"):
            if getattr(self, name) < 1:
                raise ConfigError(f"{name} must be a positive whole number.")
        if self.chunk_overlap >= self.chunk_target:
            raise ConfigError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_TARGET_TOKENS.")
        if self.chunk_target > self.chunk_max:
            raise ConfigError("CHUNK_TARGET_TOKENS must not be larger than CHUNK_MAX_TOKENS.")
        for name in ("needs_ocr_ratio", "header_footer_ratio"):
            if not 0 < getattr(self, name) <= 1:
                raise ConfigError(f"{name} must be greater than 0 and at most 1.")
        if not 0 < self.margin_fraction < 0.5:
            raise ConfigError("margin_fraction must be between 0 and 0.5.")
        if self.chunk_max > MODEL_TOKEN_LIMIT:
            message = (f"CHUNK_MAX_TOKENS={self.chunk_max} is above the embedding model's {MODEL_TOKEN_LIMIT}-token limit: "
                       "the tail of every long chunk would be silently cut off in Batch 06.")
            if not self.allow_over_limit:
                raise ConfigError(message + " Pass --allow-over-limit to accept this.")
            warnings.append("WARNING: " + message)
        return warnings

    def version(self) -> str:
        """Stored in papers.chunking_version; any change here triggers re-ingestion."""
        return (f"{PIPELINE_VERSION}|tok={TOKENIZER_NAME}@{TOKENIZER_REVISION[:8]}|target={self.chunk_target}"
                f"|max={self.chunk_max}|overlap={self.chunk_overlap}|lowchars={self.low_text_min_chars}"
                f"|ocr={self.needs_ocr_ratio:g}|hf={self.header_footer_ratio:g}")

    def public_summary(self) -> dict:
        """Parameters for the run record and the report (no local paths)."""
        return {
            "chunking_version": self.version(), "tokenizer": f"{TOKENIZER_NAME}@{TOKENIZER_REVISION}",
            "chunk_target": self.chunk_target, "chunk_max": self.chunk_max, "chunk_overlap": self.chunk_overlap,
            "low_text_min_chars": self.low_text_min_chars, "needs_ocr_ratio": self.needs_ocr_ratio,
            "header_footer_ratio": self.header_footer_ratio, "max_pdf_mb": self.max_pdf_mb,
            "max_pdf_pages": self.max_pdf_pages,
        }


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number.") from None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number.") from None


def load_config(**overrides) -> IngestConfig:
    """Environment variables first, then explicit overrides (CLI flags); None overrides are ignored."""
    base = IngestConfig()
    config = replace(
        base,
        chunk_target=_env_int("CHUNK_TARGET_TOKENS", base.chunk_target),
        chunk_max=_env_int("CHUNK_MAX_TOKENS", base.chunk_max),
        chunk_overlap=_env_int("CHUNK_OVERLAP_TOKENS", base.chunk_overlap),
        low_text_min_chars=_env_int("LOW_TEXT_MIN_CHARS", base.low_text_min_chars),
        needs_ocr_ratio=_env_float("NEEDS_OCR_RATIO", base.needs_ocr_ratio),
        header_footer_ratio=_env_float("HEADER_FOOTER_RATIO", base.header_footer_ratio),
        max_pdf_mb=_env_int("MAX_PDF_MB", base.max_pdf_mb),
        max_pdf_pages=_env_int("MAX_PDF_PAGES", base.max_pdf_pages),
        papers_dir=Path(os.environ["PAPERS_DIR"]) if os.environ.get("PAPERS_DIR", "").strip() else base.papers_dir,
        tokenizer_path=Path(os.environ["TOKENIZER_PATH"]) if os.environ.get("TOKENIZER_PATH", "").strip() else base.tokenizer_path,
    )
    return replace(config, **{key: value for key, value in overrides.items() if value is not None})
