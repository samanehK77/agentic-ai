"""Role checks, startup configuration and secret hygiene."""
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.config import StartupError, load_settings
from app.deps import require_role
from app.main import create_app


@pytest.fixture
def role_app(engine):
    """An app with a test-only admin route (real routes for admins arrive in later batches)."""
    application = create_app(engine=engine)

    @application.get("/api/_test/admin", dependencies=[Depends(require_role("admin"))])
    def admin_only():
        return {"ok": True}

    @application.get("/api/_test/either", dependencies=[Depends(require_role("admin", "student"))])
    def either():
        return {"ok": True}

    return application


def with_login(application, make_client_factory, role):
    return make_client_factory(role)


def test_require_role_student_is_forbidden(role_app, make_client):
    student = make_client("student")
    student.app = role_app
    with TestClient(role_app, base_url="http://testserver.local", cookies=student.cookies, headers=student.headers) as c:
        response = c.get("/api/_test/admin")
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "forbidden" and error["request_id"]


def test_require_role_admin_passes(role_app, make_client):
    admin = make_client("admin")
    with TestClient(role_app, base_url="http://testserver.local", cookies=admin.cookies, headers=admin.headers) as c:
        assert c.get("/api/_test/admin").json() == {"ok": True}
        assert c.get("/api/_test/either").status_code == 200


def test_require_role_without_a_session_is_401(role_app):
    with TestClient(role_app, base_url="http://testserver.local") as c:
        assert c.get("/api/_test/admin").status_code == 401


# ---------------------------------------------------------------- startup configuration

@pytest.mark.parametrize("secret", [None, "", "short", "x" * 31])
def test_app_refuses_to_start_with_a_weak_session_secret(engine, monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", secret)
    with pytest.raises(StartupError, match="SESSION_SECRET"):
        create_app(engine=engine)


def test_a_32_character_secret_is_accepted(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    assert load_settings().session_secret == "x" * 32


def test_the_app_starts_without_google_settings(engine, monkeypatch):
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()
    assert not settings.google_configured
    assert create_app(engine=engine).title == "MindEvidence Lab API"


@pytest.mark.parametrize("raw,expected", [("", False), ("false", False), ("FALSE", False), ("true", True), ("True", True)])
def test_cookie_secure_setting(monkeypatch, raw, expected):
    monkeypatch.setenv("COOKIE_SECURE", raw)
    assert load_settings().cookie_secure is expected


@pytest.mark.parametrize("raw", ["yes", "1", "maybe"])
def test_cookie_secure_rejects_unclear_values(monkeypatch, raw):
    monkeypatch.setenv("COOKIE_SECURE", raw)
    with pytest.raises(StartupError, match="COOKIE_SECURE"):
        load_settings()


def test_admin_emails_and_lifetimes_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", " One@Example.test , two@example.test ")
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "5")
    monkeypatch.setenv("SESSION_MAX_HOURS", "2")
    settings = load_settings()
    assert settings.admin_emails == {"one@example.test", "two@example.test"}
    assert (settings.session_idle_minutes, settings.session_max_hours) == (5, 2)


@pytest.mark.parametrize("name,raw", [("SESSION_IDLE_MINUTES", "0"), ("SESSION_MAX_HOURS", "abc"), ("SESSION_IDLE_MINUTES", "-3")])
def test_bad_lifetimes_are_refused(monkeypatch, name, raw):
    monkeypatch.setenv(name, raw)
    with pytest.raises(StartupError, match=name):
        load_settings()


def test_default_lifetimes(monkeypatch):
    settings = load_settings()
    assert (settings.session_idle_minutes, settings.session_max_hours) == (30, 8)


def test_development_guard_still_applies(engine, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(StartupError, match="APP_ENV"):
        create_app(engine=engine)


# ---------------------------------------------------------------- no secrets in responses

def test_error_bodies_never_contain_secrets(anon_client, client):
    secrets_ = ["test-client-secret", "test-session-secret-0123456789-abcdefghij"]
    responses = [
        anon_client.get("/api/patients"), anon_client.get("/api/auth/me"), anon_client.post("/api/auth/logout"),
        client.get("/api/patients/P-999"), client.get("/api/sessions/not-a-uuid"),
        client.post("/api/sessions", json={"patient_id": "P-001"}, headers={"X-CSRF-Token": "bad"}),
        anon_client.get("/openapi.json"),
    ]
    for response in responses:
        for secret in secrets_:
            assert secret not in response.text
