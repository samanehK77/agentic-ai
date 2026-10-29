"""A mock DeepSeek for tests: httpx.MockTransport behind the REAL DeepSeekClient, so request building, retries and
parsing are exercised without any network. The responder decides what each call returns."""
import json
from collections.abc import Callable

import httpx

from app.llm.config import LLMSettings
from app.llm.deepseek import DeepSeekClient

TEST_KEY = "sk-test-SECRET-KEY-0123456789"


def llm_settings(**changes) -> LLMSettings:
    base = dict(api_key=TEST_KEY, base_url="https://api.deepseek.com", model="deepseek-chat", timeout_seconds=5.0,
                max_retries=2, max_output_tokens=1500, temperature=0.2, thinking="disabled", context_token_budget=6000)
    base.update(changes)
    return LLMSettings(**base)


def completion(content: str | None, *, model: str = "deepseek-chat", finish: str = "stop", prompt: int = 120,
               completion_tokens: int = 60) -> dict:
    return {"id": "x", "model": model, "choices": [{"index": 0, "finish_reason": finish,
                                                     "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion_tokens, "total_tokens": prompt + completion_tokens}}


class MockProvider:
    """responder(payload, call_number) returns a content string, an httpx.Response, or an Exception to raise."""

    def __init__(self, responder: Callable[[dict, int], object]):
        self.responder = responder
        self.calls: list[dict] = []
        self.sleeps: list[float] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.calls.append({"payload": payload, "headers": dict(request.headers), "url": str(request.url)})
        result = self.responder(payload, len(self.calls))
        if isinstance(result, Exception):
            raise result
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=completion(result))

    def client(self, **settings_changes) -> DeepSeekClient:
        return DeepSeekClient(llm_settings(**settings_changes), transport=self.transport,
                              sleep=self.sleeps.append, jitter=lambda: 0.5)

    @property
    def count(self) -> int:
        return len(self.calls)


def answer_json(sections: list[dict], *, conflicts: list[str] | None = None, limitations: str = "Few trials.",
                escalation: bool = False) -> str:
    return json.dumps({"sections": sections, "conflicting_evidence": conflicts or [], "limitations": limitations,
                       "escalation_needed": escalation})


def section(kind: str, text: str, *citations: tuple[str, str]) -> dict:
    return {"kind": kind, "text": text, "citations": [{"alias": a, "quote": q} for a, q in citations]}
