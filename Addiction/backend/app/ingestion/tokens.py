"""Token counting. The chunker only needs `count(text)`, so tests can inject a fake counter and run offline."""
from pathlib import Path
from typing import Protocol

from app.ingestion.config import ConfigError


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class WordCounter:
    """Offline stand-in: one token per whitespace-separated word. Used by tests, never for real ingestion."""

    def count(self, text: str) -> int:
        return len(text.split())


class MiniLMTokenCounter:
    """Counts word pieces exactly like sentence-transformers/all-MiniLM-L6-v2 (tokenizer file only, no model, no torch).

    The count includes the [CLS] and [SEP] tokens, because the model's 256 limit applies to them too.
    """

    def __init__(self, tokenizer_json: Path):
        if not tokenizer_json.is_file():
            raise ConfigError(
                "Tokenizer file not found. Download tokenizer.json as described in docs/INGESTION.md "
                "(it is not part of the repository).")
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer_json))
        # The file ships with truncation at 128 and fixed padding; both would give wrong counts.
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=True).ids)
