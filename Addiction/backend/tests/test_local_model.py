"""Compatibility with local model servers (for example Ollama) and the neutral LLM_* setting names."""
import threading
import time

import httpx
import pytest

from app.llm.base import LLMBadOutput, LLMBusy, LLMMessage
from app.llm.concurrency import ConcurrencyLimitedClient
from app.llm.config import LLMConfigError, load_llm_settings
from app.llm.deepseek import DeepSeekClient, strip_think
from tests.fake_llm import MockProvider, completion, llm_settings

MESSAGES = [LLMMessage("system", "rules"), LLMMessage("user", "hello")]


def reply_with(message: dict, finish: str = "stop"):
    return lambda payload, n: httpx.Response(200, json={"model": "qwen", "choices": [{"finish_reason": finish, "message": message}],
                                                       "usage": {"prompt_tokens": 5, "completion_tokens": 5}})


# ---------------------------------------------------------------- thinking text

@pytest.mark.parametrize("raw,expected", [
    ("<think>some reasoning</think>{\"a\": 1}", '{"a": 1}'),
    ("<think>\nmulti\nline\n</think>\n\n{\"a\": 1}", '{"a": 1}'),
    ("<THINK>x</THINK>{\"a\": 1}", '{"a": 1}'),
    ("<think>a</think>{\"b\": 2}<think>c</think>", '{"b": 2}'),
    ("{\"a\": 1}", '{"a": 1}'),
    ("<think>cut off and never closed", ""),
])
def test_think_blocks_are_removed_from_the_content(raw, expected):
    assert strip_think(raw) == expected


def test_a_reply_with_a_think_block_is_parsed_as_the_answer():
    provider = MockProvider(reply_with({"role": "assistant", "content": "<think>I will answer now</think>{\"a\": 1}"}))
    assert provider.client().complete(MESSAGES).text == '{"a": 1}'


def test_a_reply_that_is_only_thinking_is_bad_output():
    provider = MockProvider(reply_with({"role": "assistant", "content": "<think>never finished"}))
    with pytest.raises(LLMBadOutput):
        provider.client().complete(MESSAGES)


def test_reasoning_fields_are_never_read_and_never_used_as_an_answer():
    message = {"role": "assistant", "content": '{"a": 1}', "reasoning": "SECRET-THOUGHTS", "reasoning_content": "MORE-THOUGHTS"}
    result = MockProvider(reply_with(message)).client().complete(MESSAGES)
    assert result.text == '{"a": 1}' and "THOUGHTS" not in repr(result)
    empty = {"role": "assistant", "content": "", "reasoning": '{"a": 1}'}  # the answer is NOT taken from the reasoning
    with pytest.raises(LLMBadOutput):
        MockProvider(reply_with(empty)).client().complete(MESSAGES)


def test_the_model_name_reported_by_the_server_is_kept():
    provider = MockProvider(lambda p, n: httpx.Response(200, json=completion("{}", model="qwen3.5-16k:latest")))
    assert provider.client(model="qwen3.5-16k").complete(MESSAGES).model == "qwen3.5-16k:latest"


# ---------------------------------------------------------------- setting names

NAMES = ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_API_KEY",
         "LLM_MAX_CONCURRENCY", "LLM_QUEUE_WAIT_SECONDS")


@pytest.fixture
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_older_deepseek_names_still_work(clean_env):
    clean_env.setenv("DEEPSEEK_BASE_URL", "http://localhost:11434/v1")
    clean_env.setenv("DEEPSEEK_MODEL", "qwen3.5-16k")
    settings = load_llm_settings()
    assert (settings.base_url, settings.model, settings.api_key, settings.local, settings.configured) == (
        "http://localhost:11434/v1", "qwen3.5-16k", "", True, True)


def test_the_neutral_names_win_when_both_are_set(clean_env):
    clean_env.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    clean_env.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    clean_env.setenv("DEEPSEEK_API_KEY", "old-key")
    clean_env.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    clean_env.setenv("LLM_MODEL", "qwen3.5-16k")
    clean_env.setenv("LLM_API_KEY", "new-key")
    settings = load_llm_settings()
    assert (settings.base_url, settings.model, settings.api_key) == ("http://localhost:11434/v1", "qwen3.5-16k", "new-key")


def test_an_empty_neutral_name_falls_back_to_the_older_one(clean_env):
    clean_env.setenv("LLM_MODEL", "  ")
    clean_env.setenv("DEEPSEEK_MODEL", "from-deepseek-name")
    assert load_llm_settings().model == "from-deepseek-name"


def test_a_key_is_only_optional_for_this_machine(clean_env):
    clean_env.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    assert load_llm_settings().configured is True
    clean_env.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    assert load_llm_settings().configured is False
    clean_env.setenv("LLM_API_KEY", "k")
    assert load_llm_settings().configured is True


@pytest.mark.parametrize("url", ["http://api.example.com/v1", "http://localhost.evil.com/v1", "http://192.168.1.5:11434/v1"])
def test_plain_http_stays_refused_for_other_machines_with_the_neutral_name(clean_env, url):
    clean_env.setenv("LLM_BASE_URL", url)
    with pytest.raises(LLMConfigError, match="LLM_BASE_URL"):
        load_llm_settings()


def test_concurrency_settings(clean_env):
    settings = load_llm_settings()
    assert (settings.max_concurrency, settings.queue_wait_seconds) == (1, 120.0)
    clean_env.setenv("LLM_MAX_CONCURRENCY", "3")
    clean_env.setenv("LLM_QUEUE_WAIT_SECONDS", "10")
    settings = load_llm_settings()
    assert (settings.max_concurrency, settings.queue_wait_seconds) == (3, 10.0)
    for name, value in (("LLM_MAX_CONCURRENCY", "0"), ("LLM_MAX_CONCURRENCY", "99"), ("LLM_QUEUE_WAIT_SECONDS", "0")):
        clean_env.setenv(name, value)
        with pytest.raises(LLMConfigError):
            load_llm_settings()
        clean_env.setenv(name, "1")


# ---------------------------------------------------------------- the concurrency limit

class SlowClient:
    configured = True

    def __init__(self, seconds=0.4, fail=False):
        self.seconds, self.fail, self.running, self.peak, self.calls = seconds, fail, 0, 0, 0
        self.lock = threading.Lock()

    def complete(self, messages, **kwargs):
        with self.lock:
            self.running += 1
            self.calls += 1
            self.peak = max(self.peak, self.running)
        try:
            time.sleep(self.seconds)
            if self.fail:
                raise RuntimeError("boom")
            return "ok"
        finally:
            with self.lock:
                self.running -= 1


def run_in_threads(client, count):
    out = []

    def call():
        try:
            out.append(client.complete(MESSAGES))
        except Exception as error:
            out.append(error)

    threads = [threading.Thread(target=call) for _ in range(count)]
    for thread in threads:
        thread.start()
        time.sleep(0.05)
    for thread in threads:
        thread.join()
    return out


def test_calls_queue_behind_the_limit_and_never_run_more_at_once():
    inner = SlowClient(0.2)
    results = run_in_threads(ConcurrencyLimitedClient(inner, max_concurrency=1, queue_wait_seconds=5), 3)
    assert results == ["ok", "ok", "ok"] and inner.peak == 1


def test_a_higher_limit_allows_parallel_calls():
    inner = SlowClient(0.3)
    run_in_threads(ConcurrencyLimitedClient(inner, max_concurrency=2, queue_wait_seconds=5), 2)
    assert inner.peak == 2


def test_waiting_too_long_is_busy_with_a_retry_hint():
    inner = SlowClient(0.6)
    results = run_in_threads(ConcurrencyLimitedClient(inner, max_concurrency=1, queue_wait_seconds=0.1), 2)
    assert results[1] == "ok" or isinstance(results[0], LLMBusy) or isinstance(results[1], LLMBusy)
    busy = [r for r in results if isinstance(r, LLMBusy)]
    assert len(busy) == 1 and busy[0].retry_after == 30 and inner.calls == 1


def test_a_failing_call_releases_its_slot():
    inner = SlowClient(0.05, fail=True)
    client = ConcurrencyLimitedClient(inner, max_concurrency=1, queue_wait_seconds=1)
    for _ in range(3):  # would hang or report busy if a failed call kept the slot
        with pytest.raises(RuntimeError):
            client.complete(MESSAGES)


def test_the_wrapper_reports_whether_the_inner_client_is_configured():
    assert ConcurrencyLimitedClient(MockProvider(lambda p, n: "{}").client(api_key="")).configured is False
    assert ConcurrencyLimitedClient(MockProvider(lambda p, n: "{}").client()).configured is True


def test_the_remaining_workflow_time_also_caps_the_wait_for_a_slot():
    inner = SlowClient(1.0)
    client = ConcurrencyLimitedClient(inner, max_concurrency=1, queue_wait_seconds=60)
    first = threading.Thread(target=client.complete, args=(MESSAGES,))
    first.start()
    time.sleep(0.1)
    started = time.perf_counter()
    with pytest.raises(LLMBusy):
        client.complete(MESSAGES, timeout=0.2)
    assert time.perf_counter() - started < 0.6
    first.join()


def test_settings_defaults_use_one_slot():
    assert llm_settings().max_concurrency == 1
