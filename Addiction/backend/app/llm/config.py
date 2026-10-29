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
    reasoning_effort: str = ""  # "" sends nothing; none|low|medium|high sends reasoning_effort (for example Ollama: none)
    context_token_budget: int = 6000
    max_concurrency: int = 1  # model calls in flight at once (a local model serves one request at a time)
    queue_wait_seconds: float = 120.0  # how long a call may wait for a free slot before the API answers "busy"

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


def _first_env(*names: str) -> tuple[str, str]:
    """(value, name) of the first variable that is set. The neutral LLM_* names win over the older DEEPSEEK_* names."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", names[-1]


def load_llm_settings() -> LLMSettings:
    base_url, base_name = _first_env("LLM_BASE_URL", "DEEPSEEK_BASE_URL")
    base_url = base_url or DEFAULT_BASE_URL
    # Remote providers must use https. Plain http is accepted only for this machine (a local model server).
    if not (base_url.startswith("https://") or (base_url.startswith("http://") and is_local_url(base_url))):
        raise LLMConfigError(f"{base_name} must start with https:// (http:// is allowed only for localhost or 127.0.0.1).")
    thinking = os.environ.get("LLM_THINKING", "").strip().lower() or "disabled"
    if thinking not in ("disabled", "omit"):
        raise LLMConfigError("LLM_THINKING must be 'disabled' or 'omit'.")
    effort = os.environ.get("LLM_REASONING_EFFORT", "").strip().lower()
    if effort not in ("", "omit", "none", "low", "medium", "high"):
        raise LLMConfigError("LLM_REASONING_EFFORT must be omit, none, low, medium or high.")
    return LLMSettings(
        api_key=_first_env("LLM_API_KEY", "DEEPSEEK_API_KEY")[0],
        base_url=base_url.rstrip("/"),
        model=_first_env("LLM_MODEL", "DEEPSEEK_MODEL")[0] or DEFAULT_MODEL,
        timeout_seconds=_number("LLM_TIMEOUT_SECONDS", 30.0, 1, 1800),
        max_retries=_number("LLM_MAX_RETRIES", 2, 0, 5, integer=True),
        max_output_tokens=_number("LLM_MAX_OUTPUT_TOKENS", 1500, 50, 32000, integer=True),
        temperature=_number("LLM_TEMPERATURE", 0.2, 0, 2),
        thinking=thinking,
        reasoning_effort="" if effort == "omit" else effort,
        context_token_budget=_number("LLM_CONTEXT_TOKEN_BUDGET", 6000, 1000, 60000, integer=True),
        max_concurrency=_number("LLM_MAX_CONCURRENCY", 1, 1, 16, integer=True),
        queue_wait_seconds=_number("LLM_QUEUE_WAIT_SECONDS", 120.0, 1, 1800),
    )
