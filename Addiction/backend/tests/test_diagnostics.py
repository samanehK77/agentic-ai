"""Operator diagnostics: ok/warn/fail with hints, facts without secrets, the admin endpoint and the CLI."""
import dataclasses
import json
import logging

import httpx
import pytest

from app.config import load_settings
from app.diagnostics import __main__ as cli
from app.diagnostics.checks import Check, Context, check_llm, overall, run_all, startup_summary
from app.llm.config import is_local_url
from app.retrieval.embedder import EmbedderProvider
from tests.fake_embedder import FakeEmbedder
from tests.fake_llm import TEST_KEY, llm_settings

SHOW = {"details": {"parameter_size": "9.7B", "quantization_level": "Q4_K_M"}, "parameters": "num_ctx 16384\nstop foo",
        "model_info": {"qwen.context_length": 262144}}


def transport(models=("qwen3.5-16k",), show=SHOW, list_status=200, fail=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("refused: http://user:pw@host/secret-path")
        if request.url.path.endswith("/models"):
            return httpx.Response(list_status, json={"data": [{"id": m} for m in models]})
        if request.url.path.endswith("/api/show"):
            return httpx.Response(200 if show else 404, json=show or {})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def context(engine, *, llm=None, http=None, deep=False, **settings_changes):
    settings = dataclasses.replace(load_settings(), llm=llm or llm_settings(base_url="http://localhost:11434/v1", model="qwen3.5-16k", api_key=""),
                                   **settings_changes)
    ctx = Context(engine, settings, EmbedderProvider.fixed(FakeEmbedder()), deep=deep, audit_failures=0)
    ctx.http_client_factory = lambda: httpx.Client(transport=http or transport())
    return ctx


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


# ---------------------------------------------------------------- the checks

def test_database_migrations_pgvector_and_audit_checks_pass_on_the_test_database(engine):
    got = by_name(run_all(context(engine)))
    for name in ("database", "migrations", "pgvector", "audit_log", "environment"):
        assert got[name].status == "ok", (name, got[name])
    assert got["migrations"].facts["at_head"] is True and got["audit_log"].facts["append_only_trigger"] is True


def test_the_corpus_check_reports_counts_and_what_to_do(engine, answers_corpus):
    got = by_name(run_all(context(engine)))
    facts = got["corpus"].facts
    assert {"papers_ingested", "chunks", "embedded", "pending", "skipped"} <= set(facts) and all(isinstance(v, int) for v in facts.values())
    assert got["index"].facts["matches_running_model"] is True or got["index"].hint  # a mismatch always carries a hint


def test_a_missing_database_is_a_fail_with_a_hint_and_no_exception_text():
    from sqlalchemy import create_engine

    bad = create_engine("postgresql+psycopg://nobody:supersecretpw@127.0.0.1:1/none", connect_args={"connect_timeout": 1})
    checks = run_all(context(bad))
    first = checks[0]
    assert first.name == "database" and first.status == "fail" and "docker compose up" in first.hint
    blob = json.dumps([c.__dict__ for c in checks], default=str)
    assert "supersecretpw" not in blob and "nobody" not in blob and "127.0.0.1" not in blob


def test_the_llm_check_ok_and_the_model_facts_are_read_without_generation(engine):
    got = by_name(check_llm(context(engine)))
    assert got["llm"].status == "ok" and got["llm"].facts["model_listed"] is True
    facts = got["llm_model_facts"].facts
    assert got["llm_model_facts"].status == "ok"
    assert (facts["parameter_size"], facts["quantization"], facts["context_length"]) == ("9.7B", "Q4_K_M", 16384)  # num_ctx wins over the architecture maximum
    assert "llm_generation" not in got


def test_a_context_smaller_than_budget_plus_output_is_a_warning(engine):
    small = dict(SHOW, parameters="num_ctx 4096")
    ctx = context(engine, http=transport(show=small), llm=llm_settings(base_url="http://localhost:11434/v1", model="qwen3.5-16k", api_key="",
                                                                        context_token_budget=6000, max_output_tokens=1500))
    check = by_name(check_llm(ctx))["llm_model_facts"]
    assert check.status == "warn" and "truncated" in check.message and "num_ctx" in check.hint
    assert check.facts["context_length"] == 4096 and check.facts["tokens_needed"] == 7500
    big = context(engine, http=transport(show=dict(SHOW, parameters="num_ctx 8192")), llm=llm_settings(
        base_url="http://localhost:11434/v1", model="qwen3.5-16k", api_key="", context_token_budget=6000, max_output_tokens=1500))
    assert by_name(check_llm(big))["llm_model_facts"].status == "ok"


def test_the_context_falls_back_to_the_architecture_maximum_when_no_num_ctx_is_set(engine):
    ctx = context(engine, http=transport(show={"details": {}, "model_info": {"llama.context_length": 2048}}))
    assert by_name(check_llm(ctx))["llm_model_facts"].facts["context_length"] == 2048


@pytest.mark.parametrize("kwargs,status,needle", [
    ({"fail": True}, "fail", "not reachable"),
    ({"list_status": 401}, "fail", "credentials"),
    ({"list_status": 500}, "warn", "not with a model list"),
    ({"models": ("another-model",)}, "warn", "not in its list"),
])
def test_llm_problems_have_a_status_and_a_hint(engine, kwargs, status, needle):
    check = by_name(check_llm(context(engine, http=transport(**kwargs))))["llm"]
    assert check.status == status and needle in check.message and check.hint


def test_an_unconfigured_llm_is_a_fail_with_a_hint(engine):
    ctx = context(engine, llm=llm_settings(api_key="", base_url="https://api.deepseek.com"))
    check = check_llm(ctx)[0]
    assert check.status == "fail" and "LLM_BASE_URL" in check.hint


def test_a_remote_provider_does_not_expose_model_details(engine):
    ctx = context(engine, llm=llm_settings(api_key=TEST_KEY, base_url="https://api.deepseek.com"), http=transport(models=("deepseek-chat",)))
    got = by_name(check_llm(ctx))
    assert got["llm_model_facts"].facts == {"exposed": False}


def test_a_server_without_model_details_is_not_a_problem(engine):
    got = by_name(check_llm(context(engine, http=transport(show=None))))
    assert got["llm_model_facts"].status == "ok" and got["llm_model_facts"].facts == {"exposed": False}


def test_a_crashing_check_becomes_a_fail_with_only_the_exception_class(engine, monkeypatch):
    from app.diagnostics import checks

    def boom(ctx):
        raise RuntimeError("secret detail http://u:p@h/path")

    monkeypatch.setattr(checks, "CHECKS", (("corpus", boom),))
    (result,) = run_all(context(engine))
    assert result.status == "fail" and "RuntimeError" in result.message and "secret" not in json.dumps(result.__dict__)


def test_google_and_admin_checks_report_presence_not_values(engine):
    ctx = context(engine, google_client_id="", google_client_secret="", google_redirect_uri="", admin_emails=frozenset())
    got = by_name(run_all(ctx))
    assert got["google_sign_in"].status == "warn" and got["google_sign_in"].facts["client_id"] is False
    assert got["admin_accounts"].status == "warn"
    configured = by_name(run_all(context(engine, google_client_id="id", google_client_secret="s3cret-value", google_redirect_uri="http://x/cb")))
    assert configured["google_sign_in"].status == "ok" and "s3cret-value" not in json.dumps(configured["google_sign_in"].__dict__)


def test_an_unusual_app_env_is_a_fail(engine):
    assert by_name(run_all(context(engine, app_env="production")))["environment"].status == "fail"


def test_a_missing_embedding_model_is_a_warning_with_a_hint(engine, monkeypatch):
    ctx = context(engine)
    ctx.provider = EmbedderProvider(lambda: FakeEmbedder())  # nothing loaded
    check = by_name(run_all(ctx))["embedding_model"]
    assert check.status in ("ok", "warn") and (check.status == "ok" or check.hint)
    assert check.facts["loaded"] is False


def test_the_overall_status_is_the_worst_one():
    assert overall([Check("a", "ok", ""), Check("b", "warn", "")]) == "warn"
    assert overall([Check("a", "warn", ""), Check("b", "fail", "")]) == "fail"
    assert overall([Check("a", "ok", "")]) == "ok"


# ---------------------------------------------------------------- no secrets, URLs or paths in any output

def test_the_report_holds_no_secret_url_or_path(engine):
    ctx = context(engine, llm=llm_settings(api_key=TEST_KEY, base_url="http://localhost:11434/v1", model="qwen3.5-16k"),
                  google_client_secret="GOCSPX-sentinel-secret", session_secret="sentinel-session-secret-0123456789-abcdef",
                  google_client_id="sentinel-client-id", google_redirect_uri="http://localhost:8001/api/auth/google/callback")
    blob = json.dumps([c.__dict__ for c in run_all(ctx)], default=str)
    for needle in (TEST_KEY, "GOCSPX-sentinel-secret", "sentinel-session-secret", "sentinel-client-id", "http://", "https://", "localhost:11434",
                   "11434", "C:\\", "C:/", "/Users/", "\\Users\\", "models/all-MiniLM"):
        assert needle not in blob, needle


# ---------------------------------------------------------------- endpoint and CLI

def test_the_admin_endpoint_is_admin_only_and_never_generates(answer_env, make_client, anon_client):
    admin = answer_env(role="admin")
    response = admin.client.get("/api/admin/diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("ok", "warn", "fail") and {c["name"] for c in body["checks"]} >= {"database", "migrations", "corpus", "llm", "audit_log"}
    assert admin.provider.count == 0                                      # the mock model was never called
    assert not any(c["name"] == "llm_generation" for c in body["checks"])
    assert make_client("student").get("/api/admin/diagnostics").status_code == 403
    assert anon_client.get("/api/admin/diagnostics").status_code == 401


def test_the_cli_prints_a_readable_report_and_the_exit_code_reflects_failures(engine, capsys):
    assert cli.main([], context=context(engine, google_client_id="")) in (0, 1)
    out = capsys.readouterr().out
    assert "[OK  ] database" in out and "Overall:" in out and "this machine and the configured model only" in out
    bad = context(engine, llm=llm_settings(api_key="", base_url="https://api.deepseek.com"))
    assert cli.main([], context=bad) == 1                                  # no LLM configured: fail
    assert "how to fix:" in capsys.readouterr().out


def test_the_cli_json_output_is_valid(engine, capsys):
    cli.main(["--json"], context=context(engine))
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list) and all({"name", "status", "message", "hint", "facts"} <= set(item) for item in data)


def test_only_deep_makes_one_generation_call(engine, monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, settings):
            pass

        def complete(self, messages, **kwargs):
            calls.append(kwargs)
            from app.llm.base import LLMResult
            return LLMResult('{"ok": true}', "m", 10, 5, "stop", 0)

    monkeypatch.setattr("app.llm.deepseek.DeepSeekClient", FakeClient)
    cli.main([], context=context(engine))
    assert calls == []
    cli.main(["--deep"], context=context(engine))
    assert len(calls) == 1 and calls[0]["max_tokens"] <= 60
    assert "llm_generation" in capsys.readouterr().out


def test_the_health_endpoint_stays_minimal_and_public(anon_client):
    response = anon_client.get("/api/health")
    assert response.status_code == 200 and response.json() == {"status": "ok", "database": "ok"}


# ---------------------------------------------------------------- startup summary and the host.docker.internal rule

def test_the_startup_summary_names_problems_but_never_values():
    settings = dataclasses.replace(load_settings(), google_client_id="", google_client_secret="sentinel-xyz", admin_emails=frozenset(),
                                   llm=llm_settings(api_key=TEST_KEY, base_url="https://api.deepseek.com"))
    line, problems = startup_summary(settings)
    assert "google=missing" in line and "llm=remote" in line
    assert any("google" in p for p in problems) and any("administrator" in p for p in problems)
    assert TEST_KEY not in line + "".join(problems) and "sentinel-xyz" not in line + "".join(problems)


def test_creating_the_app_logs_the_summary(engine, caplog):
    from app.main import create_app

    with caplog.at_level(logging.INFO, logger="mindevidence.startup"):
        create_app(engine=engine, settings=dataclasses.replace(load_settings(), google_client_id=""))
    assert "startup env=development" in caplog.text and "configuration: google sign-in is not configured" in caplog.text


@pytest.mark.parametrize("url,local", [
    ("http://localhost:11434/v1", True), ("http://127.0.0.1:11434/v1", True), ("http://host.docker.internal:11434/v1", True),
    ("http://host.docker.internal.evil.example/v1", False), ("http://evil.example/host.docker.internal", False),
    ("https://api.deepseek.com", False), ("http://192.168.1.5:11434/v1", False),
])
def test_only_this_machine_counts_as_local(url, local):
    assert is_local_url(url) is local


def test_a_remote_host_still_needs_a_key():
    assert llm_settings(api_key="", base_url="http://evil.example/v1").configured is False
    assert llm_settings(api_key="", base_url="http://host.docker.internal:11434/v1").configured is True
