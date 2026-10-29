"""The DeepSeek client with a mock transport: request format, retries, error mapping and key hygiene."""
import logging

import httpx
import pytest

from app.llm.base import LLMBadOutput, LLMMessage, LLMNotConfigured, LLMTimeout, LLMUnavailable
from app.llm.config import LLMConfigError, load_llm_settings
from app.llm.deepseek import DeepSeekClient
from tests.fake_llm import TEST_KEY, MockProvider, completion, llm_settings

MESSAGES = [LLMMessage("system", "rules"), LLMMessage("user", "hello")]


def ok(content="{}"):
    return lambda payload, n: content


# ---------------------------------------------------------------- request and response

def test_request_format_matches_the_documented_chat_completions_call():
    provider = MockProvider(ok('{"a": 1}'))
    result = provider.client().complete(MESSAGES, json_mode=True)
    call = provider.calls[0]
    assert call["url"] == "https://api.deepseek.com/chat/completions"
    assert call["headers"]["authorization"] == f"Bearer {TEST_KEY}"
    payload = call["payload"]
    assert payload["model"] == "deepseek-chat" and payload["stream"] is False
    assert payload["messages"] == [{"role": "system", "content": "rules"}, {"role": "user", "content": "hello"}]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 1500 and payload["temperature"] == 0.2
    assert (result.text, result.model, result.prompt_tokens, result.completion_tokens, result.retries) == ('{"a": 1}', "deepseek-chat", 120, 60, 0)


def test_json_mode_and_thinking_can_be_switched_off():
    provider = MockProvider(ok("text"))
    provider.client(thinking="omit").complete(MESSAGES, json_mode=False, max_tokens=50, temperature=0.0)
    payload = provider.calls[0]["payload"]
    assert "response_format" not in payload and "thinking" not in payload
    assert payload["max_tokens"] == 50 and payload["temperature"] == 0.0


def test_the_model_id_returned_by_the_api_is_reported():
    provider = MockProvider(lambda p, n: httpx.Response(200, json=completion("{}", model="deepseek-chat-2026-01")))
    assert provider.client().complete(MESSAGES).model == "deepseek-chat-2026-01"


# ---------------------------------------------------------------- retries

@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_statuses_are_retried_with_exponential_backoff(status):
    provider = MockProvider(lambda p, n: httpx.Response(status, json={"error": "slow down"}) if n < 3 else "{}")
    result = provider.client().complete(MESSAGES)
    assert provider.count == 3 and result.retries == 2
    assert provider.sleeps == [1.0, 2.0]  # 1 * 2**attempt * (0.5 + jitter 0.5)


def test_retries_are_bounded_and_end_in_llm_unavailable():
    provider = MockProvider(lambda p, n: httpx.Response(503, text="overloaded"))
    with pytest.raises(LLMUnavailable) as info:
        provider.client(max_retries=2).complete(MESSAGES)
    assert provider.count == 3 and info.value.retry_after == 30


def test_a_zero_retry_setting_makes_one_attempt():
    provider = MockProvider(lambda p, n: httpx.Response(500))
    with pytest.raises(LLMUnavailable):
        provider.client(max_retries=0).complete(MESSAGES)
    assert provider.count == 1 and provider.sleeps == []


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
def test_client_errors_are_never_retried(status):
    provider = MockProvider(lambda p, n: httpx.Response(status, json={"error": {"message": f"secret detail {TEST_KEY}"}}))
    with pytest.raises(LLMUnavailable) as info:
        provider.client().complete(MESSAGES)
    assert provider.count == 1 and provider.sleeps == []
    assert info.value.retry_after is None and TEST_KEY not in str(info.value) and "secret detail" not in str(info.value)


def test_timeouts_are_retried_then_raise_llm_timeout():
    provider = MockProvider(lambda p, n: httpx.ReadTimeout("took too long"))
    with pytest.raises(LLMTimeout):
        provider.client(max_retries=2).complete(MESSAGES)
    assert provider.count == 3 and len(provider.sleeps) == 2


def test_a_timeout_followed_by_success_works():
    provider = MockProvider(lambda p, n: httpx.ConnectTimeout("slow") if n == 1 else "{}")
    assert provider.client().complete(MESSAGES).retries == 1


def test_connection_errors_are_retried_and_end_as_unavailable():
    provider = MockProvider(lambda p, n: httpx.ConnectError("refused"))
    with pytest.raises(LLMUnavailable):
        provider.client().complete(MESSAGES)
    assert provider.count == 3


# ---------------------------------------------------------------- bad output

@pytest.mark.parametrize("responder", [
    lambda p, n: httpx.Response(200, json=completion(None)),
    lambda p, n: httpx.Response(200, json=completion("   ")),
    lambda p, n: httpx.Response(200, json=completion('{"cut": ', finish="length")),
    lambda p, n: httpx.Response(200, json=completion("{}", finish="content_filter")),
    lambda p, n: httpx.Response(200, json={"choices": []}),
    lambda p, n: httpx.Response(200, text="not json at all"),
])
def test_empty_truncated_or_unreadable_output_is_bad_output(responder):
    provider = MockProvider(responder)
    with pytest.raises(LLMBadOutput):
        provider.client().complete(MESSAGES)
    assert provider.count == 1  # a bad answer is not a transport failure: no automatic retry here


# ---------------------------------------------------------------- configuration and key hygiene

def test_without_a_key_nothing_is_sent():
    provider = MockProvider(ok())
    client = provider.client(api_key="")
    assert client.configured is False
    with pytest.raises(LLMNotConfigured):
        client.complete(MESSAGES)
    assert provider.count == 0


def test_the_key_never_appears_in_exceptions_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    for responder in (lambda p, n: httpx.Response(401, text=TEST_KEY), lambda p, n: httpx.ConnectError(TEST_KEY),
                      lambda p, n: httpx.ReadTimeout(TEST_KEY)):
        provider = MockProvider(responder)
        with pytest.raises(Exception) as info:
            provider.client().complete(MESSAGES)
        assert TEST_KEY not in str(info.value) and TEST_KEY not in repr(info.value)
        assert info.value.__cause__ is None
    assert TEST_KEY not in caplog.text and "Bearer" not in caplog.text


def test_settings_defaults(monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "LLM_TIMEOUT_SECONDS", "LLM_MAX_RETRIES",
                 "LLM_MAX_OUTPUT_TOKENS", "LLM_TEMPERATURE", "LLM_THINKING", "LLM_CONTEXT_TOKEN_BUDGET"):
        monkeypatch.delenv(name, raising=False)
    settings = load_llm_settings()
    assert (settings.base_url, settings.model, settings.timeout_seconds, settings.max_retries) == (
        "https://api.deepseek.com", "deepseek-chat", 30.0, 2)
    assert settings.temperature == 0.2 and settings.thinking == "disabled" and not settings.configured


@pytest.mark.parametrize("name,value", [
    ("DEEPSEEK_BASE_URL", "http://api.deepseek.com"), ("DEEPSEEK_BASE_URL", "ftp://x"), ("DEEPSEEK_BASE_URL", "http://localhost.evil.com/v1"),
    ("DEEPSEEK_BASE_URL", "http://192.168.1.5:11434/v1"), ("DEEPSEEK_BASE_URL", "http://localhost@evil.example/v1"), ("LLM_TIMEOUT_SECONDS", "0"),
    ("LLM_MAX_RETRIES", "9"), ("LLM_TEMPERATURE", "5"), ("LLM_THINKING", "maybe"), ("LLM_MAX_OUTPUT_TOKENS", "abc"),
])
def test_invalid_settings_are_refused(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(LLMConfigError):
        load_llm_settings()


def test_the_app_refuses_an_insecure_base_url_at_startup(engine, monkeypatch):
    from app.config import StartupError
    from app.main import create_app

    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://insecure.example")
    with pytest.raises(StartupError, match="https"):
        create_app(engine=engine)


def test_the_app_starts_without_a_key(engine):
    from app.main import create_app

    assert create_app(engine=engine).state.llm_client.configured is False


def test_tls_verification_is_on():
    client = DeepSeekClient(llm_settings())
    assert client._http._transport._pool._ssl_context.verify_mode.name == "CERT_REQUIRED"


# ---------------------------------------------------------------- local model servers (for example Ollama)

@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "http://127.0.0.1:11434/v1", "http://[::1]:11434/v1", "https://localhost:8443/v1"])
def test_local_addresses_may_use_plain_http_and_need_no_key(monkeypatch, url):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", url)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = load_llm_settings()
    assert settings.local and settings.configured and settings.api_key == ""


def test_a_remote_address_still_needs_a_key_to_be_configured(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    settings = load_llm_settings()
    assert not settings.local and not settings.configured


def test_a_local_server_gets_the_request_without_an_authorization_header():
    provider = MockProvider(ok('{"a": 1}'))
    client = provider.client(api_key="", base_url="http://localhost:11434/v1", model="qwen3.5:latest", thinking="omit")
    assert client.configured is True
    result = client.complete(MESSAGES)
    call = provider.calls[0]
    assert call["url"] == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in call["headers"]
    assert call["payload"]["model"] == "qwen3.5:latest" and "thinking" not in call["payload"]
    assert call["payload"]["response_format"] == {"type": "json_object"} and result.text == '{"a": 1}'


def test_a_key_is_still_sent_when_one_is_set_even_for_a_local_server():
    provider = MockProvider(ok())
    provider.client(base_url="http://localhost:11434/v1").complete(MESSAGES)
    assert provider.calls[0]["headers"]["authorization"] == f"Bearer {TEST_KEY}"
