"""CSRF token, Origin check and CORS with credentials."""
import pytest

CREATE = {"patient_id": "P-001", "title": "csrf test"}


def without_csrf(test_client):
    test_client.headers.pop("X-CSRF-Token", None)
    return test_client


def test_post_without_a_csrf_token_is_403(make_client, clean_chat):
    user = without_csrf(make_client())
    response = user.post("/api/sessions", json=CREATE)
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "csrf_failed" and error["request_id"]


@pytest.mark.parametrize("value", ["wrong", "", " ", "x" * 500])
def test_post_with_a_wrong_csrf_token_is_403(make_client, clean_chat, value):
    user = without_csrf(make_client())
    response = user.post("/api/sessions", json=CREATE, headers={"X-CSRF-Token": value})
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"


def test_post_with_another_users_csrf_token_is_403(make_client, clean_chat):
    first, second = without_csrf(make_client()), make_client()
    response = first.post("/api/sessions", json=CREATE, headers={"X-CSRF-Token": second.login["csrf"]})
    assert response.status_code == 403


def test_post_with_the_right_csrf_token_succeeds(make_client, clean_chat):
    user = make_client()
    assert user.post("/api/sessions", json=CREATE).status_code == 201


def test_a_failed_csrf_check_creates_nothing(make_client, clean_chat):
    user = without_csrf(make_client())
    user.post("/api/sessions", json=CREATE)
    user.headers["X-CSRF-Token"] = user.login["csrf"]
    assert user.get("/api/sessions").json()["total"] == 0


def test_logout_requires_the_csrf_token_and_keeps_the_session_otherwise(make_client):
    user = without_csrf(make_client())
    assert user.post("/api/auth/logout").status_code == 403
    assert user.get("/api/auth/me").status_code == 200  # still signed in


def test_safe_methods_do_not_need_a_csrf_token(make_client):
    user = without_csrf(make_client())
    assert user.get("/api/patients").status_code == 200


def test_the_csrf_error_does_not_reveal_the_expected_token(make_client):
    user = without_csrf(make_client())
    response = user.post("/api/sessions", json=CREATE, headers={"X-CSRF-Token": "nope"})
    assert user.login["csrf"] not in response.text


@pytest.mark.parametrize("origin", ["http://evil.example", "http://127.0.0.1:8000", "http://localhost:9999", "null"])
def test_disallowed_origin_is_rejected_even_with_a_valid_token(make_client, clean_chat, origin):
    user = make_client()
    response = user.post("/api/sessions", json=CREATE, headers={"Origin": origin})
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_with_a_valid_token_succeeds(make_client, clean_chat):
    user = make_client()
    response = user.post("/api/sessions", json=CREATE, headers={"Origin": "http://localhost:8000"})
    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_with_credentials_for_allowed_origin_only(make_client):
    user = make_client()
    allowed = user.get("/api/patients", headers={"Origin": "http://localhost:8000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    other = user.get("/api/patients", headers={"Origin": "http://evil.example"})
    assert other.status_code == 200
    assert "access-control-allow-origin" not in other.headers


def test_cors_never_uses_a_wildcard(client):
    response = client.get("/api/health", headers={"Origin": "http://localhost:8000"})
    assert response.headers["access-control-allow-origin"] != "*"


def test_openapi_documents_the_cookie_and_the_csrf_header(client):
    spec = client.get("/openapi.json").json()
    schemes = spec["components"]["securitySchemes"]
    assert any(s["type"] == "apiKey" and s["in"] == "cookie" and s["name"] == "me_session" for s in schemes.values())
    parameters = spec["paths"]["/api/sessions"]["post"]["parameters"]
    assert any(p["name"] == "X-CSRF-Token" and p["in"] == "header" for p in parameters)
    assert "401" in spec["paths"]["/api/patients"]["get"]["responses"]
    assert "security" not in spec["paths"]["/api/health"]["get"]
