import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import create_app
from db.config import get_database_url

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def broken_client():
    """An app whose database is unreachable (nothing listens on port 1)."""
    url = get_database_url().set(port=1)
    engine = create_engine(url, connect_args={"connect_timeout": 2})
    with TestClient(create_app(engine=engine), base_url="http://testserver.local") as test_client:
        # A cookie is needed to get past the 401 check; looking it up is what hits the dead database.
        test_client.cookies.set("me_session", "any-token", domain="testserver.local")
        yield test_client
    engine.dispose()


def assert_standard_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == code
    assert error["message"]
    assert error["request_id"]
    assert response.headers["X-Request-ID"] == error["request_id"]
    return error


# ---------------------------------------------------------------- health

def test_health_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_is_down(broken_client):
    response = broken_client.get("/api/health")
    error = assert_standard_error(response, 503, "service_unavailable")
    text = response.text.lower()
    for secret in ("password", "127.0.0.1", "psycopg", "connection", "port"):
        assert secret not in text, f"health 503 leaks {secret!r}"
    assert "details" not in error


def test_other_endpoints_return_503_not_500_when_database_is_down(broken_client):
    assert_standard_error(broken_client.get("/api/patients"), 503, "service_unavailable")


# ---------------------------------------------------------------- error format

ERROR_CASES = [
    ("get", "/api/patients/P-999", 404, "not_found"),
    ("get", "/api/patients/ABC", 422, "validation_error"),
    ("get", "/api/patients?limit=1000", 422, "validation_error"),
    ("get", "/api/sessions/not-a-uuid", 422, "validation_error"),
    ("get", "/api/sessions/123e4567-e89b-42d3-a456-426614174000", 404, "not_found"),
    ("get", "/api/does-not-exist", 404, "not_found"),
    ("post", "/api/patients", 405, "method_not_allowed"),
]


@pytest.mark.parametrize("method,path,status,code", ERROR_CASES)
def test_every_error_uses_the_standard_format(client, method, path, status, code):
    assert_standard_error(getattr(client, method)(path), status, code)


def test_validation_details_do_not_echo_the_input(client):
    response = client.post("/api/sessions", json={"patient_id": "<script>alert(1)</script>"})
    error = assert_standard_error(response, 422, "validation_error")
    assert error["details"]
    assert "<script>" not in response.text
    assert set(error["details"][0]) == {"loc", "msg", "type"}


def test_unexpected_errors_return_a_generic_500(engine):
    app = create_app(engine=engine)

    @app.get("/boom")
    def boom():
        raise RuntimeError("SELECT secret FROM hidden_table WHERE password = 'x'")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")
    error = assert_standard_error(response, 500, "internal_error")
    for leak in ("SELECT", "hidden_table", "Traceback", "RuntimeError", "password"):
        assert leak not in response.text
    assert "details" not in error


# ---------------------------------------------------------------- request ids

def test_a_request_id_is_generated_when_none_is_sent(client):
    response = client.get("/api/health")
    assert UUID_RE.match(response.headers["X-Request-ID"])


def test_a_safe_request_id_is_kept(client):
    response = client.get("/api/health", headers={"X-Request-ID": "abc-123-DEF"})
    assert response.headers["X-Request-ID"] == "abc-123-DEF"


@pytest.mark.parametrize("bad", [
    "<script>alert(1)</script>",
    "a" * 65,
    "has space",
    "../../etc/passwd",
    "semi;colon",
    "",
])
def test_an_unsafe_request_id_is_replaced_not_echoed(client, bad):
    response = client.get("/api/patients/P-999", headers={"X-Request-ID": bad})
    request_id = response.headers["X-Request-ID"]
    assert request_id != bad
    assert UUID_RE.match(request_id)
    assert response.json()["error"]["request_id"] == request_id


def test_a_64_character_request_id_is_accepted(client):
    value = "a" * 64
    assert client.get("/api/health", headers={"X-Request-ID": value}).headers["X-Request-ID"] == value
