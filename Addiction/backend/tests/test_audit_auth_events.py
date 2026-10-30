"""Audit events outside the question flow: sign-in, sign-out, patients, sessions and refusals. No e-mail is ever recorded."""
import json
import uuid

import pytest
from sqlalchemy import text

from tests.audit_helpers import of_user, read, types
from tests.test_auth_login_callback import callback

EMAIL = "audit-signin@example.test"


@pytest.fixture(autouse=True)
def forget_test_users(cleanup_users):
    cleanup_users.extend(["audit-sub-1", "audit-sub-2", "audit-sub-admin", "audit-sub-3"])


def by_request(engine, response):
    return read(engine, "request_id = :r", r=response.headers["X-Request-ID"])


# ---------------------------------------------------------------- sign-in and sign-out

def test_a_successful_sign_in_records_the_user_and_role_but_no_email(app, google_mock, engine):
    _, response = callback(app, google_mock, claims={"sub": "audit-sub-1", "email": EMAIL})
    assert response.status_code == 302
    (event,) = by_request(engine, response)
    with engine.connect() as c:
        user_id = c.scalar(text("SELECT id FROM users WHERE google_sub = 'audit-sub-1'"))
    assert event["event_type"] == "sign_in_succeeded" and event["outcome"] == "ok" and event["user_id"] == user_id
    assert event["metadata"] == {"role": "student"} and event["session_id"] is None
    assert EMAIL not in json.dumps(event, default=str) and "example.test" not in json.dumps(event, default=str)


def test_an_admin_sign_in_records_the_admin_role(app, google_mock, engine):
    _, response = callback(app, google_mock, claims={"sub": "audit-sub-admin", "email": "admin@example.test"})
    (event,) = by_request(engine, response)
    assert event["event_type"] == "sign_in_succeeded" and event["metadata"] == {"role": "admin"}


@pytest.mark.parametrize("kwargs,reason", [
    ({"state": "a", "cookie_state": "b"}, "state_invalid"),
    ({"error": "access_denied"}, "access_denied"),
    ({"claims": {"sub": "audit-sub-2", "email_verified": False, "email": EMAIL}}, "email_unverified"),
    ({"claims": {"sub": "audit-sub-3", "aud": "someone-else"}}, "token_invalid"),
])
def test_a_failed_sign_in_records_only_the_reason_code(app, google_mock, engine, kwargs, reason):
    _, response = callback(app, google_mock, **kwargs)
    assert response.headers["location"].endswith(f"auth_error={reason}")
    (event,) = by_request(engine, response)
    assert event["event_type"] == "sign_in_failed" and event["outcome"] == "error" and event["error_code"] == reason
    assert event["user_id"] is None and event["metadata"] == {"reason": reason}
    assert EMAIL not in json.dumps(event, default=str)


def test_sign_out_is_recorded(make_client, engine):
    client = make_client()
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    (event,) = of_user(engine, client.login["user_id"], "sign_out")
    assert event["outcome"] == "ok" and event["metadata"] == {}
    assert event["request_id"] == response.headers["X-Request-ID"]


def test_sign_in_events_are_not_written_for_other_requests(make_client, engine):
    client = make_client()
    client.get("/api/auth/me")
    client.get("/api/health")
    assert of_user(engine, client.login["user_id"]) == []                  # no catch-all request logging


# ---------------------------------------------------------------- patients and sessions

def test_viewing_a_patient_profile_is_recorded_but_listing_is_not(make_client, engine):
    client = make_client()
    assert client.get("/api/patients").status_code == 200
    assert client.get("/api/patients/P-001/history").status_code == 200
    assert client.get("/api/patients/P-999").status_code == 404
    assert of_user(engine, client.login["user_id"]) == []
    assert client.get("/api/patients/P-003").status_code == 200
    (event,) = of_user(engine, client.login["user_id"])
    assert event["event_type"] == "patient_viewed" and event["metadata"] == {"patient_id": "P-003"} and event["outcome"] == "ok"


def test_creating_a_session_is_recorded_without_its_title(make_client, engine, clean_chat):
    client = make_client()
    response = client.post("/api/sessions", json={"patient_id": "P-002", "title": "My private SECRET-TITLE notes"})
    sid = response.json()["session_id"]
    (event,) = of_user(engine, client.login["user_id"], "session_created")
    assert str(event["session_id"]) == sid and event["metadata"] == {"patient_id": "P-002"}
    assert "SECRET-TITLE" not in json.dumps(event, default=str)
    assert client.post("/api/sessions", json={"patient_id": "P-404"}).status_code in (404, 422)
    assert len(of_user(engine, client.login["user_id"], "session_created")) == 1


# ---------------------------------------------------------------- refusals

@pytest.mark.parametrize("method,path,route", [
    ("get", "/api/sessions/{sid}", "get_session"),
    ("get", "/api/sessions/{sid}/messages", "list_messages"),
    ("get", "/api/sessions/{sid}/messages/{mid}/trace", "get_message_trace"),
    ("get", "/api/audit/timeline?session_id={sid}", "get_timeline"),
    ("post", "/api/sessions/{sid}/messages/{mid}/feedback", "post_feedback"),
])
def test_another_users_session_is_a_404_for_them_and_an_access_denied_event(make_client, engine, clean_chat, method, path, route):
    owner, intruder = make_client(), make_client()
    sid = owner.post("/api/sessions", json={"patient_id": "P-001"}).json()["session_id"]
    url = path.format(sid=sid, mid=uuid.uuid4())
    kwargs = {"json": {"rating": "helpful"}} if method == "post" else {}
    response = getattr(intruder, method)(url, **kwargs)
    assert response.status_code == 404
    (event,) = of_user(engine, intruder.login["user_id"])
    assert event["event_type"] == "access_denied" and event["outcome"] == "denied" and str(event["session_id"]) == sid
    assert event["metadata"] == {"route": route, "reason_code": "not_owner"}
    assert of_user(engine, owner.login["user_id"], "access_denied") == []


def test_an_unknown_session_is_a_plain_404_with_no_event(make_client, engine):
    client = make_client()
    assert client.get(f"/api/sessions/{uuid.uuid4()}").status_code == 404
    assert of_user(engine, client.login["user_id"], "access_denied") == []


def test_a_student_on_an_admin_route_is_denied_and_recorded(make_client, engine):
    student = make_client()
    assert student.get("/api/admin/audit/summary").status_code == 403
    assert student.get("/api/admin/papers").status_code == 403
    events = of_user(engine, student.login["user_id"], "access_denied")
    assert [e["metadata"] for e in events] == [{"route": "summary", "reason_code": "role_required"},
                                               {"route": "list_papers", "reason_code": "role_required"}]
    assert all(e["outcome"] == "denied" and e["session_id"] is None for e in events)


def test_an_admin_is_not_denied(make_client, engine):
    admin = make_client("admin")
    assert admin.get("/api/admin/audit/summary").status_code == 200
    assert of_user(engine, admin.login["user_id"], "access_denied") == []


def test_every_audited_action_has_its_own_correlation_id(make_client, engine, clean_chat):
    client = make_client()
    client.get("/api/patients/P-001")
    client.get("/api/patients/P-002")
    events = of_user(engine, client.login["user_id"])
    assert types(events) == ["patient_viewed", "patient_viewed"] and events[0]["correlation_id"] != events[1]["correlation_id"]
