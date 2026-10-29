"""LLM settings from environment variables. The key is read here and nowhere else; it is never logged or returned."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import db.config  # noqa: F401  (loads the project's .env without overriding real environment variables)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LLMConfigError(ValueError):
    """Invalid LLM configuration (the app refuses to start)."""


def is_local_url(url: str) -> bool:
    """True for http(s) addresses on this machine only (a local model server such as Ollama)."""
    try:
        return urlsplit(url).hostname in LOCAL_HOSTS
    except ValueError:
        return False


@dataclass(frozen=True)
class LLMSettings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 30.0
    max_retries: int = 2
    max_output_tokens: int = 1500
    temperature: float = 0.2
    thinking: str = "disabled"  # "disabled" sends thinking: {type: disabled}; "omit" sends nothing
    context_token_budget: int = 6000

    @property
    def local(self) -> bool:
        """A model server on this machine (for example Ollama): nothing leaves the computer and no key is needed."""
        return is_local_url(self.base_url)

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or self.local


def _number(name: str, default: float, low: float, high: float, integer: bool = False):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        raise LLMConfigError(f"{name} must be a {'whole number' if integer else 'number'}.") from None
    if not low <= value <= high:
        raise LLMConfigError(f"{name} must be between {low:g} and {high:g}.")
    return value


def load_llm_settings() -> LLMSettings:
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_BASE_URL
    # Remote providers must use https. Plain http is accepted only for this machine (a local model server).
    if not (base_url.startswith("https://") or (base_url.startswith("http://") and is_local_url(base_url))):
        raise LLMConfigError("DEEPSEEK_BASE_URL must start with https:// (http:// is allowed only for localhost or 127.0.0.1).")
    thinking = os.environ.get("LLM_THINKING", "").strip().lower() or "disabled"
    if thinking not in ("disabled", "omit"):
        raise LLMConfigError("LLM_THINKING must be 'disabled' or 'omit'.")
    return LLMSettings(
        api_key=os.environ.get("DEEPSEEK_API_KEY", "").strip(),
        base_url=base_url.rstrip("/"),
        model=os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_MODEL,
        timeout_seconds=_number("LLM_TIMEOUT_SECONDS", 30.0, 1, 300),
        max_retries=_number("LLM_MAX_RETRIES", 2, 0, 5, integer=True),
        max_output_tokens=_number("LLM_MAX_OUTPUT_TOKENS", 1500, 50, 8000, integer=True),
        temperature=_number("LLM_TEMPERATURE", 0.2, 0, 2),
        thinking=thinking,
        context_token_budget=_number("LLM_CONTEXT_TOKEN_BUDGET", 6000, 1000, 60000, integer=True),
    )
