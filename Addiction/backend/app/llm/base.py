"""Provider-neutral types. A different provider only has to implement BaseLLMClient."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str  # the model id the API reported
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    retries: int  # how many attempts were repeated before this one succeeded


class LLMError(Exception):
    """Base of all provider failures. Messages are generic and safe to show: never provider bodies, headers or keys."""


class LLMNotConfigured(LLMError):
    """No API key is configured."""


class LLMTimeout(LLMError):
    """The provider did not answer in time (after the allowed retries)."""


class LLMUnavailable(LLMError):
    """The provider rejected or failed the request (rate limit, server error, authentication, balance...)."""

    def __init__(self, message: str = "The language model service is not available right now.",
                 retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMBusy(LLMUnavailable):
    """Another question is using the model and no slot became free in time (local models serve one request at a time)."""

    def __init__(self, retry_after: int = 30):
        super().__init__("The language model is busy with another question.", retry_after=retry_after)


class LLMBadOutput(LLMError):
    """The provider answered, but with empty, truncated or unusable output."""


class BaseLLMClient(Protocol):
    configured: bool

    def complete(self, messages: list[LLMMessage], *, json_mode: bool = True, max_tokens: int | None = None,
                 temperature: float | None = None, timeout: float | None = None) -> LLMResult:
        """`timeout` caps the WHOLE call including retries (the workflow's remaining time); None = the configured timeout."""
        ...
