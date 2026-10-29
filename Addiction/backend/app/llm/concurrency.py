"""Limits how many model calls run at once. A local model server (for example Ollama) works on one request at a time:
a second question queues here, and when no slot frees up in time the API answers 503 "busy" with a retry hint instead of
letting requests pile up behind a multi-minute call."""
import threading

from app.llm.base import BaseLLMClient, LLMBusy, LLMMessage, LLMResult


class ConcurrencyLimitedClient:
    def __init__(self, inner: BaseLLMClient, max_concurrency: int = 1, queue_wait_seconds: float = 120.0):
        self._inner = inner
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._wait = queue_wait_seconds

    @property
    def configured(self) -> bool:
        return self._inner.configured

    def complete(self, messages: list[LLMMessage], *, json_mode: bool = True, max_tokens: int | None = None,
                 temperature: float | None = None, timeout: float | None = None) -> LLMResult:
        wait = self._wait if timeout is None else min(self._wait, timeout)
        if not self._slots.acquire(timeout=wait):
            raise LLMBusy(retry_after=30)
        try:
            return self._inner.complete(messages, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature,
                                        timeout=timeout)
        finally:
            self._slots.release()

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close:
            close()
