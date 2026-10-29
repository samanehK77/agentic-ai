"""Login sessions: 401 without a session, expiry, logout, hashed tokens, /me."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app import security
from app.auth_service import SESSION_COOKIE

PROTECTED_GETS = [
    "/api/patients", "/api/patients/P-001", "/api/patients/P-001/history", "/api/papers",
    "/api/sessions", "/api/sessions/123e4567-e89b-42d3-a456-426614174000",
    "/api/sessions/123e4567-e89b-42d3-a456-426614174000/messages", "/api/auth/me",
]


def error_code(response):
    return response.json()["error"]["code"]


# ---------------------------------------------------------------- public vs protected

@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_protected_routes_return_401_without_a_session(anon_client, path):
    response = anon_client.get(path)
    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"error"} and body["error"]["code"] == "unauthorized"
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]


def test_post_sessions_without_a_session_is_401_not_403(anon_client):
    response = anon_client.post("/api/sessions", json={"patient_id": "P-001"})
    assert response.status_code == 401 and error_code(response) == "unauthorized"


def test_logout_without_a_session_is_401(anon_client):
    assert anon_client.post("/api/auth/logout").status_code == 401


def test_health_and_auth_endpoints_are_public(anon_client):
    assert anon_client.get("/api/health").status_code == 200
    assert anon_client.get("/api/auth/google/login", follow_redirects=False).status_code == 302
    assert anon_client.get("/api/auth/google/callback", follow_redirects=False).status_code == 302


@pytest.mark.parametrize("cookie", ["", "garbage", "a" * 43, "../../etc/passwd", "x" * 5000])
def test_unknown_or_tampered_cookie_is_rejected(anon_client, cookie):
    anon_client.cookies.set(SESSION_COOKIE, cookie, domain="testserver.local")
    response = anon_client.get("/api/patients")
    assert response.status_code == 401 and error_code(response) == "unauthorized"


def test_a_valid_token_with_one_character_changed_is_rejected(make_client):
    user = make_client()
    token = user.cookies.get(SESSION_COOKIE)
    user.cookies.set(SESSION_COOKIE, token[:-1] + ("A" if token[-1] != "A" else "B"), domain="testserver.local")
    assert user.get("/api/patients").status_code == 401


def test_signed_in_client_can_read_protected_routes(client):
    assert client.get("/api/patients").status_code == 200
    assert client.get("/api/papers").status_code == 200


# ---------------------------------------------------------------- expiry

def test_idle_timeout_is_enforced_and_cleans_up(make_client, engine):
    user = make_client()
    assert user.get("/api/patients").status_code == 200
    with engine.begin() as connection:
        connection.execute(text("UPDATE auth_sessions SET last_seen_at = now() - interval '31 minutes' WHERE user_id = :u"),
                           {"u": user.login["user_id"]})
    response = user.get("/api/patients")
    assert response.status_code == 401 and error_code(response) == "unauthorized"
    with engine.connect() as connection:
        left = connection.scalar(text("SELECT count(*) FROM auth_sessions WHERE user_id = :u"), {"u": user.login["user_id"]})
    assert left == 0  # removed lazily


def test_activity_within_the_idle_window_keeps_the_session_and_slides_it(make_client, engine):
    user = make_client()
    with engine.begin() as connection:
        connection.execute(text("UPDATE auth_sessions SET last_seen_at = now() - interval '10 minutes' WHERE user_id = :u"),
                           {"u": user.login["user_id"]})
    assert user.get("/api/patients").status_code == 200
    with engine.connect() as connection:
        age = connection.scalar(text("SELECT now() - last_seen_at FROM auth_sessions WHERE user_id = :u"),
                                {"u": user.login["user_id"]})
    assert age < timedelta(minutes=1)


def test_absolute_lifetime_is_enforced_even_when_active(make_client, engine):
    user = make_client()
    with engine.begin() as connection:
        connection.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 second' WHERE user_id = :u"),
                           {"u": user.login["user_id"]})
    assert user.get("/api/patients").status_code == 401


def test_idle_and_maximum_lifetime_are_configurable(make_app, engine):
    from fastapi.testclient import TestClient

    from tests.conftest import create_user_session, sign_in

    short = make_app(session_idle_minutes=1)
    login = create_user_session(engine)
    try:
        with TestClient(short, base_url="http://testserver.local") as browser:
            sign_in(browser, login)
            assert browser.get("/api/patients").status_code == 200
            with engine.begin() as connection:
                connection.execute(text("UPDATE auth_sessions SET last_seen_at = now() - interval '2 minutes' WHERE user_id = :u"),
                                   {"u": login["user_id"]})
            assert browser.get("/api/patients").status_code == 401
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": login["user_id"]})


# ---------------------------------------------------------------- logout

def test_logout_revokes_the_session_on_the_server(make_client, engine):
    user = make_client()
    old_token = user.cookies.get(SESSION_COOKIE)
    response = user.post("/api/auth/logout")
    assert response.status_code == 204
    cleared = response.headers["set-cookie"]
    assert cleared.startswith(f"{SESSION_COOKIE}=") and "Max-Age=0" in cleared and "HttpOnly" in cleared
    assert response.headers["cache-control"] == "no-store"
    with engine.connect() as connection:
        revoked = connection.scalar(text("SELECT revoked_at FROM auth_sessions WHERE user_id = :u"), {"u": user.login["user_id"]})
    assert revoked is not None
    # an attacker (or the same browser) who still holds the old cookie gets nothing
    user.cookies.set(SESSION_COOKIE, old_token, domain="testserver.local")
    assert user.get("/api/patients").status_code == 401
    assert user.get("/api/auth/me").status_code == 401


def test_logout_only_ends_the_current_session_of_that_user_not_other_users(make_client):
    first, second = make_client(), make_client()
    first.post("/api/auth/logout")
    assert second.get("/api/patients").status_code == 200


# ---------------------------------------------------------------- tokens in the database

def test_raw_token_is_never_stored_only_its_sha256(make_client, engine):
    user = make_client()
    token = user.cookies.get(SESSION_COOKIE)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM auth_sessions WHERE user_id = :u"), {"u": user.login["user_id"]}).all()
    assert len(rows) == 1
    assert token not in " ".join(str(value) for value in rows[0])
    assert rows[0].token_hash == security.hash_token(token)
    assert len(rows[0].token_hash) == 64


def test_tokens_have_at_least_256_bits_of_entropy():
    tokens = {security.new_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) >= 43 for token in tokens)  # 32 random bytes in base64url


# ---------------------------------------------------------------- /api/auth/me

def test_me_returns_the_user_and_csrf_token_but_nothing_from_google(make_client):
    user = make_client(role="student", email="me@example.test")
    response = user.get("/api/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "email", "display_name", "role", "csrf_token"}
    assert body["email"] == "me@example.test" and body["role"] == "student"
    assert body["csrf_token"] == user.login["csrf"]
    assert response.headers["cache-control"] == "no-store"
    text_ = response.text.lower()
    assert "google_sub" not in text_ and "sub-" not in text_ and "token_hash" not in text_
    assert body["id"] == str(user.login["user_id"])


def test_me_shows_admin_role(make_client):
    assert make_client(role="admin").get("/api/auth/me").json()["role"] == "admin"


def test_naive_time_helpers_are_utc():
    from app.auth_service import utcnow

    assert utcnow().tzinfo is not None and abs(utcnow() - datetime.now(timezone.utc)) < timedelta(seconds=1)
