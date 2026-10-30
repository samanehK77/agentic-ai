"""CORS, the development-only startup guard and the OpenAPI document."""
import pytest

from app.config import StartupError, load_settings
from app.main import create_app

ALLOWED = "http://localhost:8000"


# ---------------------------------------------------------------- CORS

def test_allowed_origin_gets_cors_headers(client):
    response = client.get("/api/health", headers={"Origin": ALLOWED})
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-credentials"] == "true"


def test_other_origin_gets_no_cors_headers(client):
    for origin in ("http://evil.example", "http://127.0.0.1:8000", "http://localhost:9999", "null"):
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


def test_wildcard_is_never_returned(client):
    response = client.get("/api/health", headers={"Origin": ALLOWED})
    assert response.headers["access-control-allow-origin"] != "*"


def test_preflight_allows_only_get_post_options(client):
    response = client.options("/api/sessions", headers={
        "Origin": ALLOWED, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-request-id,x-csrf-token"})
    assert response.status_code == 200
    allowed = {m.strip() for m in response.headers["access-control-allow-methods"].split(",")}
    assert allowed == {"GET", "POST", "OPTIONS"}
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "x-request-id" in allowed_headers and "x-csrf-token" in allowed_headers
    assert response.headers["X-Request-ID"]


def test_preflight_from_other_origin_is_refused(client):
    response = client.options("/api/sessions", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_preflight_for_delete_is_refused(client):
    response = client.options("/api/sessions", headers={"Origin": ALLOWED, "Access-Control-Request-Method": "DELETE"})
    assert response.status_code == 400


# ---------------------------------------------------------------- startup guard

@pytest.mark.parametrize("value", [None, "", "production", "staging", "Development ", "dev"])
def test_app_refuses_to_start_unless_development(engine, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", value)
    with pytest.raises(StartupError, match="APP_ENV"):
        create_app(engine=engine)


def test_app_starts_in_development(engine, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert create_app(engine=engine).title == "MindEvidence Lab API"


def test_default_cors_origins(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert load_settings().cors_origins == ("http://localhost:8000",)


def test_cors_origins_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:5173, http://localhost:5173")
    assert load_settings().cors_origins == ("http://127.0.0.1:5173", "http://localhost:5173")


@pytest.mark.parametrize("bad", ["*", "http://127.0.0.1:8000,*", "127.0.0.1:8000", "ftp://x"])
def test_wildcard_or_malformed_cors_origins_are_refused(monkeypatch, bad):
    monkeypatch.setenv("CORS_ORIGINS", bad)
    with pytest.raises(StartupError, match="CORS"):
        load_settings()


# ---------------------------------------------------------------- OpenAPI

EXPECTED_OPERATIONS = {
    ("get", "/api/health"),
    ("get", "/api/auth/google/login"),
    ("get", "/api/auth/google/callback"),
    ("get", "/api/auth/me"),
    ("post", "/api/auth/logout"),
    ("get", "/api/patients"),
    ("get", "/api/patients/{patient_id}"),
    ("get", "/api/patients/{patient_id}/history"),
    ("get", "/api/papers"),
    ("post", "/api/retrieval/search"),
    ("get", "/api/admin/papers"),
    ("get", "/api/admin/papers/{paper_id}"),
    ("get", "/api/admin/papers/{paper_id}/chunks"),
    ("get", "/api/admin/chunks/{chunk_id}"),
    ("get", "/api/sessions"),
    ("post", "/api/sessions"),
    ("get", "/api/sessions/{session_id}"),
    ("get", "/api/sessions/{session_id}/messages"),
    ("post", "/api/sessions/{session_id}/messages"),
    ("get", "/api/sessions/{session_id}/messages/{message_id}/trace"),
    ("post", "/api/sessions/{session_id}/messages/{message_id}/feedback"),
    ("get", "/api/audit/timeline"),
    ("get", "/api/admin/audit/events"),
    ("get", "/api/admin/audit/summary"),
    ("get", "/api/admin/diagnostics"),
}


def test_openapi_lists_every_endpoint(client):
    spec = client.get("/openapi.json").json()
    found = {(method, path) for path, item in spec["paths"].items() for method in item}
    assert found == EXPECTED_OPERATIONS
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            assert operation.get("summary"), (method, path)
            assert operation.get("tags"), (method, path)
            assert any(code[0] in "23" for code in operation["responses"]), (method, path)


def test_openapi_contains_the_schemas(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("PatientSummary", "PatientProfile", "HistoryItem", "PaperOut", "SessionCreate", "SessionOut",
                 "MessageOut", "ErrorResponse", "ErrorBody", "HealthOut"):
        assert name in schemas, name
    assert any(name.startswith("Page_") for name in schemas)
    assert schemas["PatientProfile"]["properties"]["is_synthetic"]["const"] is True


def test_openapi_documents_error_responses(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"404", "422"} <= set(paths["/api/patients/{patient_id}"]["get"]["responses"])
    assert "503" in paths["/api/health"]["get"]["responses"]
    assert "201" in paths["/api/sessions"]["post"]["responses"]


def test_interactive_docs_are_available(client):
    assert client.get("/docs").status_code == 200
