"""Google sign-in: the login redirect and the callback. Google is faked; the ID-token checks are the real library's."""
import hashlib
import logging
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import security
from app.auth_service import OAUTH_COOKIE, SESSION_COOKIE
from tests.google_helpers import OTHER_PRIVATE_PEM, make_id_token, oauth_cookie

SECRET = "test-session-secret-0123456789-abcdefghij"
FRONTEND = "http://localhost:8000"
DOMAIN = "testserver.local"


@pytest.fixture(autouse=True)
def forget_test_users(cleanup_users):
    """Every sub used below is registered for deletion afterwards."""
    cleanup_users.extend([
        "flow-sub", "cookie-sub", "secure-sub", "same-sub", "fix-sub", "fixation-sub", "adm-1", "stu-1", "adm-2",
        "store-sub", "replay-sub", "log-sub", "google-sub-1"])


def callback(app, google_mock, *, claims=None, token=None, state="state-1", cookie_state="state-1", nonce="nonce-1",
             code="auth-code", error=None, cookie=True, **cookie_kwargs):
    """Runs GET /api/auth/google/callback with a freshly built login-state cookie; returns (client, response)."""
    google_mock.token = token if token is not None else make_id_token(**{"nonce": nonce, **(claims or {})})
    unique = secrets.token_hex(4)  # real states are random, and the app remembers used ones
    state, cookie_state = f"{state}-{unique}", f"{cookie_state}-{unique}"
    test_client = TestClient(app, base_url=f"http://{DOMAIN}")
    if cookie:
        test_client.cookies.set(OAUTH_COOKIE, oauth_cookie(SECRET, cookie_state, nonce, **cookie_kwargs),
                                domain=DOMAIN, path="/api/auth/google")
    params = {"state": state, "code": code}
    if error:
        params = {"state": state, "error": error}
    response = test_client.get("/api/auth/google/callback", params=params, follow_redirects=False)
    return test_client, response


def assert_error_redirect(response, reason):
    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONTEND}/?auth_error={reason}"
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")


# ---------------------------------------------------------------- login redirect

def test_login_redirects_to_google_with_pkce_state_and_nonce(anon_client):
    response = anon_client.get("/api/auth/google/login", follow_redirects=False)
    assert response.status_code == 302
    url = urlparse(response.headers["location"])
    assert (url.scheme, url.netloc, url.path) == ("https", "accounts.google.com", "/o/oauth2/v2/auth")
    query = {key: values[0] for key, values in parse_qs(url.query).items()}
    assert query["scope"] == "openid email profile"
    assert "gmail" not in response.headers["location"].lower()
    assert query["response_type"] == "code"
    assert query["client_id"] == "test-client-id.apps.googleusercontent.com"
    assert query["redirect_uri"] == "http://localhost:8001/api/auth/google/callback"
    assert query["code_challenge_method"] == "S256"
    assert query["state"] and query["nonce"] and query["code_challenge"]
    assert response.headers["cache-control"] == "no-store"


def test_login_state_cookie_is_signed_httponly_lax_and_short_lived(anon_client):
    response = anon_client.get("/api/auth/google/login", follow_redirects=False)
    header = response.headers["set-cookie"]
    assert header.startswith(f"{OAUTH_COOKIE}=")
    assert "HttpOnly" in header and "SameSite=lax" in header and "Max-Age=600" in header
    assert "Secure" not in header and "Domain" not in header
    value = header.split(";", 1)[0].split("=", 1)[1]
    payload = security.unsign(value, SECRET)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert payload["s"] == query["state"][0] and payload["n"] == query["nonce"][0]
    assert security.pkce_challenge(payload["v"]) == query["code_challenge"][0]
    assert security.unsign(value + "x", SECRET) is None  # tampering is detected
    assert security.unsign(value, "another-secret-another-secret-12345") is None


def test_login_ignores_a_next_parameter(anon_client):
    response = anon_client.get("/api/auth/google/login?next=http://evil.example&redirect=http://evil.example",
                              follow_redirects=False)
    assert "evil.example" not in response.headers["location"]


def test_login_each_call_has_new_state_and_nonce(anon_client):
    first = parse_qs(urlparse(anon_client.get("/api/auth/google/login", follow_redirects=False).headers["location"]).query)
    second = parse_qs(urlparse(anon_client.get("/api/auth/google/login", follow_redirects=False).headers["location"]).query)
    assert first["state"] != second["state"] and first["nonce"] != second["nonce"]


def test_login_returns_503_when_google_is_not_configured(make_app):
    app = make_app(google_client_id="", google_client_secret="", google_redirect_uri="")
    with TestClient(app) as test_client:
        response = test_client.get("/api/auth/google/login", follow_redirects=False)
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "auth_not_configured" and error["request_id"]
        assert response.headers["cache-control"] == "no-store"
        assert test_client.get("/api/health").status_code == 200  # the app still starts and serves
        assert test_client.get("/api/patients").status_code == 401  # protected routes stay protected


# ---------------------------------------------------------------- callback: success

def test_full_login_flow_through_the_login_endpoint(app, google_mock):
    with TestClient(app, base_url=f"http://{DOMAIN}") as browser:
        login = browser.get("/api/auth/google/login", follow_redirects=False)
        query = parse_qs(urlparse(login.headers["location"]).query)
        google_mock.token = make_id_token(query["nonce"][0], sub="flow-sub", email="flow@example.test")
        response = browser.get("/api/auth/google/callback", params={"state": query["state"][0], "code": "c1"},
                               follow_redirects=False)
        assert response.status_code == 302 and response.headers["location"] == f"{FRONTEND}/"
        # the PKCE verifier sent to Google matches the challenge sent in the login redirect
        verifier = google_mock.calls[0]["verifier"]
        assert security.pkce_challenge(verifier) == query["code_challenge"][0]
        me = browser.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["email"] == "flow@example.test"
        assert browser.get("/api/patients").status_code == 200


def test_callback_sets_a_secure_session_cookie_and_clears_the_state_cookie(app, google_mock):
    _, response = callback(app, google_mock, claims={"sub": "cookie-sub"})
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    assert "HttpOnly" in session and "SameSite=lax" in session and "Path=/" in session
    assert "Domain" not in session and "Secure" not in session
    assert any(c.startswith(f"{OAUTH_COOKIE}=") and "Max-Age=0" in c for c in cookies)  # one-time cookie removed
    assert response.headers["cache-control"] == "no-store"


def test_session_cookie_has_secure_flag_when_configured(make_app, google_mock):
    app = make_app(cookie_secure=True)
    _, response = callback(app, google_mock, claims={"sub": "secure-sub"})
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    assert "Secure" in session and "HttpOnly" in session
    login = TestClient(app).get("/api/auth/google/login", follow_redirects=False)
    assert "Secure" in login.headers["set-cookie"]


def test_second_login_updates_the_same_user_even_if_the_email_changed(app, google_mock, engine):
    callback(app, google_mock, claims={"sub": "same-sub", "email": "old@example.test", "name": "Old"}, state="a", cookie_state="a")
    callback(app, google_mock, claims={"sub": "same-sub", "email": "new@example.test", "name": "New"}, state="b", cookie_state="b")
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT email, display_name FROM users WHERE google_sub = 'same-sub'")).all()
    assert rows == [("new@example.test", "New")]


def test_every_login_creates_a_new_session_token(app, google_mock, engine):
    first_client, _ = callback(app, google_mock, claims={"sub": "fix-sub"}, state="a", cookie_state="a")
    second_client, _ = callback(app, google_mock, claims={"sub": "fix-sub"}, state="b", cookie_state="b")
    assert first_client.cookies.get(SESSION_COOKIE) != second_client.cookies.get(SESSION_COOKIE)
    with engine.connect() as connection:
        count = connection.scalar(text(
            "SELECT count(*) FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE u.google_sub = 'fix-sub'"))
    assert count == 2


def test_an_existing_cookie_is_never_adopted_at_login(app, google_mock, make_client):
    old = make_client()  # someone is already signed in with a known token
    old_token = old.cookies.get(SESSION_COOKIE)
    google_mock.token = make_id_token("n", sub="fixation-sub")
    browser = TestClient(app, base_url=f"http://{DOMAIN}")
    browser.cookies.set(SESSION_COOKIE, old_token, domain=DOMAIN)
    browser.cookies.set(OAUTH_COOKIE, oauth_cookie(SECRET, "s", "n"), domain=DOMAIN, path="/api/auth/google")
    browser.get("/api/auth/google/callback", params={"state": "s", "code": "c"}, follow_redirects=False)
    assert browser.cookies.get(SESSION_COOKIE) != old_token


def test_admin_role_comes_only_from_admin_emails_with_a_verified_email(app, make_app, google_mock):
    admin_client, _ = callback(app, google_mock, claims={"sub": "adm-1", "email": "Admin@Example.test"}, state="a", cookie_state="a")
    assert admin_client.get("/api/auth/me").json()["role"] == "admin"  # case-insensitive match
    student_client, _ = callback(app, google_mock, claims={"sub": "stu-1", "email": "other@example.test"}, state="b", cookie_state="b")
    assert student_client.get("/api/auth/me").json()["role"] == "student"
    # an unverified admin address is rejected before any role is assigned
    _, response = callback(app, google_mock, claims={"sub": "adm-2", "email": "admin@example.test", "email_verified": False},
                           state="c", cookie_state="c")
    assert_error_redirect(response, "email_unverified")
    # the role is recomputed at every login: with an empty admin list the same account becomes a student
    demoted_app = make_app(admin_emails=frozenset())
    demoted_client, _ = callback(demoted_app, google_mock, claims={"sub": "adm-1", "email": "admin@example.test"}, state="d", cookie_state="d")
    assert demoted_client.get("/api/auth/me").json()["role"] == "student"


def test_no_google_token_or_code_is_stored(app, google_mock, engine):
    callback(app, google_mock, claims={"sub": "store-sub"}, code="SECRET-AUTH-CODE")
    token = google_mock.token
    with engine.connect() as connection:
        dump = " ".join(str(value) for table in ("users", "auth_sessions")
                        for row in connection.execute(text(f"SELECT * FROM {table}")) for value in row)
    assert token not in dump and "SECRET-AUTH-CODE" not in dump


# ---------------------------------------------------------------- callback: state attacks

def test_missing_state_cookie_is_rejected(app, google_mock):
    _, response = callback(app, google_mock, cookie=False)
    assert_error_redirect(response, "state_invalid")


def test_state_mismatch_is_rejected(app, google_mock):
    _, response = callback(app, google_mock, state="attacker-state", cookie_state="real-state")
    assert_error_redirect(response, "state_invalid")


def test_missing_state_parameter_is_rejected(app, google_mock):
    test_client = TestClient(app, base_url=f"http://{DOMAIN}")
    test_client.cookies.set(OAUTH_COOKIE, oauth_cookie(SECRET, "s", "n"), domain=DOMAIN, path="/api/auth/google")
    response = test_client.get("/api/auth/google/callback", params={"code": "c"}, follow_redirects=False)
    assert_error_redirect(response, "state_invalid")


def test_expired_state_is_rejected(app, google_mock):
    _, response = callback(app, google_mock, lifetime=-5)
    assert_error_redirect(response, "state_invalid")


def test_forged_state_cookie_is_rejected(app, google_mock):
    forged = security.sign({"s": "state-1", "n": "nonce-1", "v": "v" * 64}, "attacker-secret-attacker-secret-1234", 600)
    google_mock.token = make_id_token("nonce-1")
    test_client = TestClient(app, base_url=f"http://{DOMAIN}")
    test_client.cookies.set(OAUTH_COOKIE, forged, domain=DOMAIN, path="/api/auth/google")
    response = test_client.get("/api/auth/google/callback", params={"state": "state-1", "code": "c"}, follow_redirects=False)
    assert_error_redirect(response, "state_invalid")


def test_state_cannot_be_replayed(app, google_mock):
    cookie = oauth_cookie(SECRET, "replay-state", "n")
    google_mock.token = make_id_token("n", sub="replay-sub")
    results = []
    for _ in range(2):  # the same signed cookie presented twice, e.g. by an attacker who captured it
        test_client = TestClient(app, base_url=f"http://{DOMAIN}")
        test_client.cookies.set(OAUTH_COOKIE, cookie, domain=DOMAIN, path="/api/auth/google")
        results.append(test_client.get("/api/auth/google/callback", params={"state": "replay-state", "code": "c"},
                                       follow_redirects=False))
    assert results[0].headers["location"] == f"{FRONTEND}/"
    assert_error_redirect(results[1], "state_invalid")


def test_state_cookie_is_removed_even_when_login_fails(app, google_mock):
    _, response = callback(app, google_mock, state="wrong", cookie_state="right")
    assert any(c.startswith(f"{OAUTH_COOKIE}=") and "Max-Age=0" in c for c in response.headers.get_list("set-cookie"))


def test_google_error_redirects_with_access_denied_and_echoes_nothing(app, google_mock):
    _, response = callback(app, google_mock, error="<script>alert(1)</script>")
    assert_error_redirect(response, "access_denied")
    assert "script" not in response.headers["location"]


# ---------------------------------------------------------------- callback: token checks (real google-auth verification)

@pytest.mark.parametrize("claims", [
    {"nonce": "some-other-nonce"},                      # nonce mismatch
    {"nonce": None},                                    # nonce missing
    {"aud": "someone-elses-client-id"},                 # wrong audience
    {"iss": "https://evil.example"},                    # wrong issuer
    {"exp": 1_000_000_000, "iat": 999_999_000},         # expired
    {"sub": None},                                      # no subject
    {"_signing_key": OTHER_PRIVATE_PEM},                # signed with a key Google does not publish
])
def test_bad_id_tokens_are_rejected(app, google_mock, claims):
    _, response = callback(app, google_mock, claims=claims)
    assert_error_redirect(response, "token_invalid")


def test_garbage_id_token_is_rejected(app, google_mock):
    _, response = callback(app, google_mock, token="not.a.jwt")
    assert_error_redirect(response, "token_invalid")


def test_code_exchange_failure_is_reported_generically(app, google_mock):
    google_mock.exchange_fails = True
    _, response = callback(app, google_mock)
    assert_error_redirect(response, "token_invalid")


def test_missing_code_is_rejected(app, google_mock):
    test_client = TestClient(app, base_url=f"http://{DOMAIN}")
    test_client.cookies.set(OAUTH_COOKIE, oauth_cookie(SECRET, "no-code", "n"), domain=DOMAIN, path="/api/auth/google")
    response = test_client.get("/api/auth/google/callback", params={"state": "no-code"}, follow_redirects=False)
    assert_error_redirect(response, "token_invalid")


@pytest.mark.parametrize("verified", [False, None, "true"])
def test_email_must_be_verified(app, google_mock, verified):
    _, response = callback(app, google_mock, claims={"email_verified": verified})
    assert_error_redirect(response, "email_unverified")


# ---------------------------------------------------------------- logging

def test_auth_logs_contain_no_secrets_or_emails(app, google_mock, caplog):
    caplog.set_level(logging.DEBUG)
    client_, _ = callback(app, google_mock, claims={"sub": "log-sub", "email": "private.person@example.test"},
                          code="LOGGED-CODE-123", state="a", cookie_state="a")
    token = client_.cookies.get(SESSION_COOKIE)
    csrf = client_.get("/api/auth/me").json()["csrf_token"]
    callback(app, google_mock, state="bad", cookie_state="good")
    client_.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    # only the application's own log lines (the test client's httpx logger prints request URLs itself)
    logs = " | ".join(r.getMessage() for r in caplog.records if r.name.startswith("mindevidence"))
    assert "login_success" in logs and "login_failed" in logs and "logout" in logs
    for secret in (token, csrf, google_mock.token, "LOGGED-CODE-123", "private.person", "test-client-secret", SECRET):
        assert secret not in logs


def test_hashing_helper_matches_sha256():
    assert security.hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
