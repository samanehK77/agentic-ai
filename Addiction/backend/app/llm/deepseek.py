"""DeepSeek chat-completions client (OpenAI-compatible) on httpx.

- TLS verification stays on (httpx default); the base URL must be https (checked in the settings).
- Retries (exponential backoff with jitter) only for timeouts, connection errors, 429 and 5xx. Never for 400, 401,
  402, 422 or other client errors.
- Error messages are built from scratch: the text of an httpx exception (which can contain request details) is never
  reused, and provider response bodies are never kept, so the API key cannot leak through an error.
"""
import logging
import random
import time
from collections.abc import Callable

import httpx

from app.llm.base import (
    LLMBadOutput, LLMMessage, LLMNotConfigured, LLMResult, LLMTimeout, LLMUnavailable)
from app.llm.config import LLMSettings

logger = logging.getLogger("mindevidence.llm")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 20.0


class DeepSeekClient:
    def __init__(self, settings: LLMSettings, *, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, jitter: Callable[[], float] = random.random):
        self._settings = settings
        self._sleep = sleep
        self._jitter = jitter
        self._http = httpx.Client(base_url=settings.base_url, timeout=httpx.Timeout(settings.timeout_seconds),
                                  transport=transport)

    @property
    def configured(self) -> bool:
        return self._settings.configured

    def complete(self, messages: list[LLMMessage], *, json_mode: bool = True, max_tokens: int | None = None,
                 temperature: float | None = None) -> LLMResult:
        settings = self._settings
        if not settings.configured:
            raise LLMNotConfigured("The language model is not configured.")
        payload: dict = {
            "model": settings.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens or settings.max_output_tokens,
            "temperature": settings.temperature if temperature is None else temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if settings.thinking == "disabled":
            payload["thinking"] = {"type": "disabled"}
        headers = {"Content-Type": "application/json"}
        if settings.api_key:  # a local model server needs no key
            headers["Authorization"] = f"Bearer {settings.api_key}"

        attempts = settings.max_retries + 1
        last_failure = "unavailable"
        for attempt in range(attempts):
            try:
                response = self._http.post("/chat/completions", json=payload, headers=headers)
            except httpx.TimeoutException:
                last_failure = "timeout"
            except httpx.TransportError:
                last_failure = "connection"
            else:
                status = response.status_code
                if status == 200:
                    return self._parse(response, attempt)
                if status not in RETRYABLE_STATUS:
                    logger.warning("provider rejected the request status=%d", status)  # 400/401/402/422: no retry
                    raise LLMUnavailable() from None
                last_failure = f"status_{status}"
            logger.warning("provider call failed attempt=%d/%d reason=%s", attempt + 1, attempts, last_failure)
            if attempt < attempts - 1:
                delay = min(MAX_BACKOFF_SECONDS, 1.0 * (2 ** attempt) * (0.5 + self._jitter()))
                self._sleep(delay)
        if last_failure == "timeout":
            raise LLMTimeout("The language model did not answer in time.") from None
        raise LLMUnavailable(retry_after=30) from None

    def _parse(self, response: httpx.Response, retries: int) -> LLMResult:
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"].get("content")
            finish = str(choice.get("finish_reason") or "")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise LLMBadOutput("The language model returned an unreadable response.") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMBadOutput("The language model returned an empty answer.")
        if finish == "length":
            raise LLMBadOutput("The language model's answer was cut off.")
        if finish not in ("stop", ""):
            raise LLMBadOutput("The language model did not finish its answer.")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        model = body.get("model") if isinstance(body.get("model"), str) else self._settings.model
        return LLMResult(
            text=content, model=model, prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0), finish_reason=finish or "stop", retries=retries)

    def close(self) -> None:
        self._http.close()
