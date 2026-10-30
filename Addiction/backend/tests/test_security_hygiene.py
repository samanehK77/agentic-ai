"""Secret hygiene: sentinel secrets must never appear in the frontend, in any API response (errors and OpenAPI included),
in the audit table or in the log output; tracked files hold no secret-like strings; sensitive paths are git-ignored; every
published Docker port is bound to 127.0.0.1. None of this reads .env."""
import dataclasses
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import load_settings
from app.main import create_app
from tests.answers_helpers import faithful_responder
from tests.conftest import create_user_session, sign_in
from tests.fake_embedder import FakeEmbedder
from tests.fake_llm import MockProvider, llm_settings

PROJECT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT / "frontend"

SENTINELS = {
    "SESSION_SECRET": "SENTINEL-session-secret-9f3a7c1d5e8b2a4c6e0f1a3b",
    "GOOGLE_CLIENT_SECRET": "GOCSP" + "X-SENTINEL-google-secret-7c2d9e4f",  # split so this file itself does not look like a real secret
    "LLM_API_KEY": "sk-SENTINEL-llm-key-5b8e1c7a9d3f2046",
}


@pytest.fixture
def sentinel_env(engine):
    """An app whose secrets are known sentinel values, with a mock model that even echoes its key in an error body."""
    provider = MockProvider(faithful_responder)
    settings = dataclasses.replace(
        load_settings(), session_secret=SENTINELS["SESSION_SECRET"], google_client_secret=SENTINELS["GOOGLE_CLIENT_SECRET"],
        retrieval_min_similarity=0.5,
        llm=llm_settings(api_key=SENTINELS["LLM_API_KEY"], max_retries=0))
    app = create_app(engine=engine, settings=settings, embedder=FakeEmbedder(), llm_client=provider.client(api_key=SENTINELS["LLM_API_KEY"], max_retries=0))
    student, admin = create_user_session(engine), create_user_session(engine, "admin")
    with TestClient(app, base_url="http://testserver.local") as anon, TestClient(app, base_url="http://testserver.local") as s, \
            TestClient(app, base_url="http://testserver.local") as a:
        sign_in(s, student)
        sign_in(a, admin)
        yield {"app": app, "anon": anon, "student": s, "admin": a, "provider": provider, "logins": [student, admin]}
    with engine.begin() as c:
        for login in (student, admin):
            c.execute(text("DELETE FROM chat_sessions WHERE owner_id = :u"), {"u": login["user_id"]})
            c.execute(text("DELETE FROM users WHERE id = :u"), {"u": login["user_id"]})


def secret_values(engine) -> dict[str, str]:
    """The sentinels plus the real database password the app itself loaded (never printed, only compared)."""
    from db.config import get_database_url

    values = dict(SENTINELS)
    password = get_database_url().password
    if password and len(password) >= 6:
        values["POSTGRES_PASSWORD"] = password
    return values


def assert_clean(blob: str, secrets: dict[str, str], where: str) -> None:
    for name, value in secrets.items():
        assert value not in blob, f"{name} appears in {where}"


# ---------------------------------------------------------------- API responses, audit table, logs

def exercise(env) -> list[str]:
    """Success paths, error paths and the documentation routes; returns every response body and header block."""
    anon, student, admin = env["anon"], env["student"], env["admin"]
    seen: list[str] = []

    def keep(response):
        seen.append(response.text + json.dumps(dict(response.headers)))
        return response

    for client, path in ((anon, "/api/health"), (anon, "/openapi.json"), (anon, "/docs"), (anon, "/redoc"), (anon, "/api/patients"),
                         (anon, "/api/auth/me"), (student, "/api/auth/me"), (student, "/api/patients/P-001"), (student, "/api/patients/P-999"),
                         (student, "/api/patients/bad"), (student, "/api/papers"), (student, "/api/sessions"),
                         (student, "/api/audit/timeline"), (student, "/api/audit/timeline?session_id=not-a-uuid"),
                         (student, "/api/admin/diagnostics"), (student, "/api/admin/audit/summary"), (student, "/api/admin/papers"),
                         (admin, "/api/admin/diagnostics"), (admin, "/api/admin/audit/summary"), (admin, "/api/admin/audit/events"),
                         (admin, "/api/admin/papers"), (anon, "/api/nothing-here")):
        keep(client.get(path))
    keep(anon.get("/api/auth/google/login", follow_redirects=False))
    keep(anon.get("/api/auth/google/callback", params={"state": "x", "code": "y"}, follow_redirects=False))
    keep(student.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}))
    sid = student.post("/api/sessions", json={"patient_id": "P-001"}).json()["session_id"]
    keep(student.post(f"/api/sessions/{sid}/messages", json={"content": "alpha question", "mode": "rag"}))
    keep(student.post(f"/api/sessions/{sid}/messages", json={"content": "", "mode": "rag"}))
    keep(student.get(f"/api/sessions/{sid}/messages"))
    keep(student.get("/api/audit/timeline", params={"session_id": sid}))
    # a provider failure whose body echoes the key must not leak through the answer error
    env["provider"].responder = lambda payload, n: httpx.Response(500, json={"error": f"bad key {SENTINELS['LLM_API_KEY']}"})
    keep(student.post(f"/api/sessions/{sid}/messages", json={"content": "alpha again", "mode": "rag"}))
    return seen


def test_no_secret_appears_in_any_api_response_or_header(sentinel_env, engine, answers_corpus):
    bodies = exercise(sentinel_env)
    assert len(bodies) > 20
    secrets = secret_values(engine)
    for index, body in enumerate(bodies):
        assert_clean(body, secrets, f"API response {index}")


def test_no_secret_appears_in_the_audit_table(sentinel_env, engine, answers_corpus):
    exercise(sentinel_env)
    with engine.connect() as c:
        rows = c.execute(text("SELECT metadata::text, error_code, request_id FROM audit_events ORDER BY occurred_at DESC LIMIT 500")).all()
    assert rows
    assert_clean(json.dumps([list(r) for r in rows]), secret_values(engine), "audit_events")


def test_no_secret_appears_in_the_log_output(sentinel_env, engine, answers_corpus, caplog):
    caplog.set_level(logging.DEBUG)
    exercise(sentinel_env)
    assert caplog.records
    assert_clean(caplog.text, secret_values(engine), "the log output")


# ---------------------------------------------------------------- the frontend and tracked files

FRONTEND_FILES = [p for p in FRONTEND.rglob("*") if p.is_file() and p.suffix in (".js", ".html", ".css", ".json", ".md", ".py")]
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "Google client secret": re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}"),
    "Google client id": re.compile(r"\b[0-9]{9,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "API key (sk-)": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{30,}"),
}


def test_no_frontend_file_holds_a_secret(engine):
    assert FRONTEND_FILES
    secrets = secret_values(engine)
    for path in FRONTEND_FILES:
        content = path.read_text(encoding="utf-8", errors="replace")
        assert_clean(content, secrets, f"frontend/{path.relative_to(FRONTEND).as_posix()}")
        for label, pattern in SECRET_PATTERNS.items():
            assert not pattern.search(content), f"{label} pattern in frontend/{path.relative_to(FRONTEND).as_posix()}"
    # the real values of the secret variables of this machine (loaded by the app's own configuration): never in the frontend
    for name in ("SESSION_SECRET", "GOOGLE_CLIENT_SECRET", "DEEPSEEK_API_KEY", "LLM_API_KEY", "POSTGRES_PASSWORD"):
        value = os.environ.get(name, "")
        if len(value) >= 8:
            for path in FRONTEND_FILES:
                assert value not in path.read_text(encoding="utf-8", errors="replace"), f"{name} value in a frontend file"


def test_the_frontend_config_holds_only_the_api_base_url_and_the_answer_timeout():
    config = (FRONTEND / "js" / "config.js").read_text(encoding="utf-8")
    exports = re.findall(r"^export const (\w+)\s*=\s*(.+?);\s*$", config, re.MULTILINE)
    assert [name for name, _ in exports] == ["API_BASE_URL", "ANSWER_TIMEOUT_MS"]
    values = dict(exports)
    assert re.fullmatch(r'"http://localhost:\d+"', values["API_BASE_URL"]) and re.fullmatch(r"\d+", values["ANSWER_TIMEOUT_MS"])
    assert "process.env" not in config and "secret" not in config.lower()


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT, capture_output=True, text=True)


@pytest.fixture(scope="module")
def tracked_files() -> list[str]:
    result = git("ls-files")
    if result.returncode != 0:
        pytest.skip("not inside a git checkout")
    return result.stdout.splitlines()


def test_no_tracked_file_looks_like_a_secret(tracked_files):
    assert len(tracked_files) > 50
    suspicious_names = [f for f in tracked_files if re.search(r"(^|/)\.env($|\.(?!example$))|\.pem$|\.key$|id_rsa|credentials\.json|client_secret.*\.json", f)]
    assert suspicious_names == []
    for name in tracked_files:
        path = PROJECT / name
        if path.suffix.lower() in (".pdf", ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".safetensors", ".zip") or not path.is_file():
            continue
        if path.stat().st_size > 2_000_000:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            match = pattern.search(content)
            assert not match, f"{label} pattern in tracked file {name}"


def test_sensitive_paths_are_git_ignored_and_not_tracked(tracked_files):
    for ignored in (".env", "data/papers/example.pdf", "backend/models/all-MiniLM-L6-v2/model.safetensors", "data/eval_reports/x.json",
                    "data/ingestion_reports/x.json", "backend/.venv/pyvenv.cfg", "backend/app/__pycache__/x.pyc", "backend/.pytest_cache/x"):
        result = git("check-ignore", "-q", ignored)
        assert result.returncode == 0, f"{ignored} is not git-ignored"
    for name in tracked_files:
        assert not name.lower().endswith((".pdf", ".safetensors", ".pyc")), f"{name} must not be tracked"
        assert not name.startswith(("backend/models/", "data/eval_reports/", "data/ingestion_reports/", "backend/.venv/")), name


def test_env_example_has_names_only():
    for line in (PROJECT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", name), line
            assert value.strip() == "", f"{name} has a value in .env.example"


def test_every_published_docker_port_is_bound_to_localhost():
    compose = (PROJECT / "docker-compose.yml").read_text(encoding="utf-8")
    blocks = re.findall(r"^[ \t]*ports:[ \t]*\n((?:[ \t]*-[ \t]*.+\n?)+)", compose, re.MULTILINE)
    published = [re.sub(r"^[ \t]*-[ \t]*[\"']?|[\"']?[ \t]*(#.*)?$", "", line) for block in blocks for line in block.splitlines() if line.strip()]
    assert published, "no published ports found: the db service should publish one"
    for entry in published:
        assert entry.startswith("127.0.0.1:"), f"port {entry} is not bound to 127.0.0.1"
