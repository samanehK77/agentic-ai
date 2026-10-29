"""python -m app.llm_smoke: it must never call the provider without --live."""
import httpx

from app.llm_smoke import main
from tests.fake_llm import TEST_KEY, MockProvider


def test_it_refuses_without_the_live_flag(capsys):
    provider = MockProvider(lambda p, n: "{}")
    assert main([], client=provider.client()) == 2
    assert "--live" in capsys.readouterr().err and provider.count == 0


def test_it_refuses_without_a_key_and_sends_nothing(capsys, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main(["--live"]) == 2
    assert "No DEEPSEEK_API_KEY" in capsys.readouterr().err


def test_a_successful_live_call_prints_numbers_but_never_the_key(capsys):
    provider = MockProvider(lambda p, n: '{"ok": true}')
    assert main(["--live"], client=provider.client()) == 0
    out = capsys.readouterr()
    assert "OK: model=deepseek-chat" in out.out and "prompt_tokens=120" in out.out
    assert TEST_KEY not in out.out + out.err and provider.count == 1
    payload = provider.calls[0]["payload"]
    assert payload["max_tokens"] == 30 and "patient" not in str(payload).lower()  # a tiny call without patient data


def test_a_failed_call_prints_only_the_error_class(capsys):
    provider = MockProvider(lambda p, n: httpx.Response(401, text=TEST_KEY))
    assert main(["--live"], client=provider.client()) == 1
    err = capsys.readouterr().err
    assert "LLMUnavailable" in err and TEST_KEY not in err
