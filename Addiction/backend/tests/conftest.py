"""Test fixtures. Tests run against throwaway databases named <POSTGRES_DB>_test*, never the real one."""
import os
from pathlib import Path

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

# The API refuses to start unless APP_ENV=development and a long SESSION_SECRET, so tests set their own
# configuration before importing the app (this also keeps the developer's real .env values out of the tests).
os.environ.update({
    "APP_ENV": "development",
    "SESSION_SECRET": "test-session-secret-0123456789-abcdefghij",
    "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "GOOGLE_REDIRECT_URI": "http://localhost:8001/api/auth/google/callback",
    "FRONTEND_URL": "http://localhost:8000",
    "COOKIE_SECURE": "false",
    "ADMIN_EMAILS": "admin@example.test",
    "CORS_ORIGINS": "",
    "SESSION_IDLE_MINUTES": "",
    "SESSION_MAX_HOURS": "",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.auth_service import SESSION_COOKIE  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security import hash_token, new_token  # noqa: E402
from db.config import get_database_url  # noqa: E402
from db.seed import seed  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["sqlalchemy_url"] = url
    return config


def recreate_database(suffix: str):
    """Drop and create <POSTGRES_DB>_<suffix>; returns its URL."""
    base = get_database_url()
    name = f"{base.database}_{suffix}"
    assert name.endswith(f"_{suffix}") and suffix.startswith("test"), "refusing to touch a non-test database"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return base.set(database=name)


@pytest.fixture(scope="session")
def engine():
    url = recreate_database("test")
    command.upgrade(alembic_config(url), "head")
    eng = create_engine(url)
    seed(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """A connection whose changes are always rolled back."""
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


def create_user_session(engine, role: str = "student", email: str | None = None) -> dict:
    """Creates a user and a login session directly in the test database (Google is never involved)."""
    suffix = secrets.token_hex(4)
    token, csrf = new_token(), new_token()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        user_id = connection.scalar(text(
            "INSERT INTO users (google_sub, email, email_verified, display_name, role) "
            "VALUES (:sub, :email, true, :name, :role) RETURNING id"),
            {"sub": f"sub-{suffix}", "email": email or f"user-{suffix}@example.test", "name": f"Test User {suffix}", "role": role})
        connection.execute(text(
            "INSERT INTO auth_sessions (user_id, token_hash, csrf_token, created_at, last_seen_at, expires_at) "
            "VALUES (:u, :h, :c, :now, :now, :exp)"),
            {"u": user_id, "h": hash_token(token), "c": csrf, "now": now, "exp": now + timedelta(hours=8)})
    return {"user_id": user_id, "token": token, "csrf": csrf}


def sign_in(test_client: TestClient, login: dict) -> TestClient:
    test_client.cookies.set(SESSION_COOKIE, login["token"], domain="testserver.local")
    test_client.headers["X-CSRF-Token"] = login["csrf"]
    return test_client


@pytest.fixture(scope="session")
def app(engine):
    return create_app(engine=engine)


@pytest.fixture(scope="session")
def client(app, engine):
    """A signed-in test client (a student) for the real app wired to the seeded test database."""
    with TestClient(app, base_url="http://testserver.local") as test_client:
        yield sign_in(test_client, create_user_session(engine))


@pytest.fixture
def anon_client(app):
    """A client with no cookies and no CSRF header."""
    with TestClient(app, base_url="http://testserver.local") as test_client:
        yield test_client


@pytest.fixture
def make_client(app, engine):
    """Factory for extra signed-in clients (other users, admins); their rows are removed afterwards."""
    created: list[dict] = []

    def factory(role: str = "student", email: str | None = None):
        login = create_user_session(engine, role, email)
        created.append(login)
        test_client = TestClient(app, base_url="http://testserver.local")
        test_client.login = login
        return sign_in(test_client, login)

    yield factory
    with engine.begin() as connection:
        for login in created:
            connection.execute(text("DELETE FROM chat_sessions WHERE owner_id = :u"), {"u": login["user_id"]})
            connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": login["user_id"]})


@pytest.fixture
def clean_chat(engine):
    """Removes chat sessions (and, by cascade, messages) created during a test."""
    yield
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM chat_sessions"))


class GoogleMock:
    """Controls what the faked Google returns. `token` is the ID token the code exchange hands back."""

    def __init__(self):
        self.token: str | None = None
        self.exchange_fails = False
        self.calls: list[dict] = []


@pytest.fixture
def google_mock(monkeypatch):
    from app import google
    from tests.google_helpers import FakeCertsRequest

    mock = GoogleMock()

    def fake_exchange(settings, code, code_verifier):
        mock.calls.append({"code": code, "verifier": code_verifier})
        if mock.exchange_fails:
            raise google.GoogleError("fake failure")
        return mock.token

    monkeypatch.setattr(google, "exchange_code", fake_exchange)
    monkeypatch.setattr(google, "_certs_request", FakeCertsRequest)
    return mock


@pytest.fixture
def make_app(engine):
    """Builds an app with changed settings, e.g. make_app(cookie_secure=True)."""
    import dataclasses

    from app.config import load_settings

    def factory(**changes):
        return create_app(engine=engine, settings=dataclasses.replace(load_settings(), **changes))

    return factory


@pytest.fixture
def cleanup_users(engine):
    """Deletes users (and their login sessions and chat sessions) whose google_sub was registered during the test."""
    subs: list[str] = []
    yield subs
    with engine.begin() as connection:
        for sub in subs:
            connection.execute(text(
                "DELETE FROM chat_sessions WHERE owner_id IN (SELECT id FROM users WHERE google_sub = :s)"), {"s": sub})
            connection.execute(text("DELETE FROM users WHERE google_sub = :s"), {"s": sub})
