"""The audit API: a student's own timeline (grouping, ordering, isolation, pagination) and the administrator views."""
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text

from tests.audit_helpers import read

QUESTION = "alpha question about heavy drinking"
INSERT = text("""INSERT INTO audit_events (occurred_at, correlation_id, user_id, event_type, outcome, latency_ms, error_code, metadata)
                 VALUES (:at, :c, :u, :t, :o, :l, :e, CAST(:m AS jsonb))""")


def timeline(client, sid, **params):
    return client.get("/api/audit/timeline", params={"session_id": sid, **params})


def seed(engine, rows):
    with engine.begin() as c:
        for at, t, o, l, e, m, u in rows:
            c.execute(INSERT, {"at": at, "c": uuid.uuid4(), "u": u, "t": t, "o": o, "l": l, "e": e, "m": json.dumps(m)})


def day(year, month=1, d=1, hour=12):
    return datetime(year, month, d, hour, tzinfo=timezone.utc)


# ---------------------------------------------------------------- the student's timeline

def test_the_timeline_groups_questions_newest_first_with_outcomes_and_latency(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    for question in (QUESTION, "completely unrelated words", "What dose of naltrexone should he take?"):
        assert env.ask(sid, question, "rag").status_code == 201
    body = timeline(env.client, sid).json()
    assert body["total"] == 4 and body["limit"] == 50 and body["offset"] == 0           # three questions and the session itself
    groups = body["items"]
    assert [g["kind"] for g in groups] == ["question", "question", "question", "action"]
    assert [g["outcome"] for g in groups[:3]] == ["unsupported", "no_evidence", "answered"]  # newest question first
    assert groups[3]["outcome"] == "ok" and groups[3]["events"][0]["event_type"] == "session_created"
    started = [g["started_at"] for g in groups]
    assert started == sorted(started, reverse=True)
    answered = groups[2]
    assert answered["total_latency_ms"] is not None and answered["error_code"] is None
    assert answered["events"][0]["event_type"] == "question_submitted" and answered["events"][-1]["event_type"] == "answer_returned"
    assert len(answered["events"]) == 15 and len({e["event_id"] for e in answered["events"]}) == 15
    assert len({g["correlation_id"] for g in groups}) == 4
    occurred = [e["occurred_at"] for e in answered["events"]]
    assert occurred == sorted(occurred)
    nodes = [e for e in answered["events"] if e["event_type"] == "node_executed" and e["outcome"] == "ok"]
    assert nodes and all(e["latency_ms"] is not None for e in nodes)


def test_a_group_carries_the_model_configuration(answer_env, answers_corpus):
    env = answer_env(llm_changes={"model": "qwen3.5-16k"})
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag")
    group = timeline(env.client, sid).json()["items"][0]
    config = group["config"]
    assert config["model"] == "qwen3.5-16k" and config["prompt_version"] == "answer-v1" and config["top_k"] == 5
    assert len(config["config_fingerprint"]) == 12 and config["embedding_model"] and config["chunking_version"]


def test_a_failed_question_is_an_error_group_with_its_code_and_a_running_one_is_marked(answer_env, answers_corpus, engine):
    env = answer_env(lambda p, n: httpx.ReadTimeout("t"), llm_changes={"max_retries": 0})
    sid = env.new_session()
    assert env.ask(sid, QUESTION, "rag").status_code == 504
    group = timeline(env.client, sid).json()["items"][0]
    assert group["outcome"] == "error" and group["error_code"] == "llm_timeout" and group["total_latency_ms"] is not None
    assert group["events"][-1]["event_type"] == "pipeline_error"
    # a question that has not finished yet (only question_submitted so far) is shown as running
    from app.audit.service import AuditService, new_correlation_id

    AuditService(engine).record("question_submitted", correlation_id=new_correlation_id(), user_id=env.login["user_id"], session_id=uuid.UUID(sid),
                                metadata={"question_chars": 5, "mode": "rag", "idempotent": False, "config_fingerprint": "abc"})
    assert timeline(env.client, sid).json()["items"][0]["outcome"] == "running"


def test_the_timeline_is_paginated_by_group(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    for _ in range(3):
        env.ask(sid, QUESTION, "rag")
    everything = timeline(env.client, sid).json()["items"]
    first = timeline(env.client, sid, limit=2).json()
    second = timeline(env.client, sid, limit=2, offset=2).json()
    assert first["total"] == second["total"] == 4 and first["limit"] == 2
    assert [g["correlation_id"] for g in first["items"] + second["items"]] == [g["correlation_id"] for g in everything]
    assert timeline(env.client, sid, limit=2, offset=10).json()["items"] == []
    assert timeline(env.client, sid, limit=0).status_code == 422 and timeline(env.client, sid, limit=101).status_code == 422
    assert timeline(env.client, sid, offset=-1).status_code == 422


def test_the_timeline_of_an_empty_session_has_one_group_only_for_its_creation(answer_env):
    env = answer_env()
    body = timeline(env.client, env.new_session()).json()
    assert body["total"] == 1 and body["items"][0]["kind"] == "action"


def test_timeline_isolation_and_validation(answer_env, answers_corpus, anon_client):
    alice, bob = answer_env(), answer_env()
    sid = alice.new_session()
    alice.ask(sid, QUESTION, "rag")
    assert timeline(alice.client, sid).status_code == 200
    foreign = timeline(bob.client, sid)
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "not_found"
    unknown = timeline(alice.client, uuid.uuid4())
    assert unknown.status_code == 404 and unknown.json()["error"]["message"] == foreign.json()["error"]["message"]
    assert alice.client.get("/api/audit/timeline", params={"session_id": "not-a-uuid"}).status_code == 422
    assert alice.client.get("/api/audit/timeline").status_code == 422
    assert anon_client.get("/api/audit/timeline", params={"session_id": sid}).status_code == 401


def test_a_students_timeline_never_contains_another_users_events(answer_env, answers_corpus, engine):
    alice = answer_env()
    sid = alice.new_session()
    alice.ask(sid, QUESTION, "rag")
    intruder_id = uuid.uuid4()
    # even a foreign event that carries this session id (it cannot happen through the API) is not shown
    seed(engine, [(datetime.now(timezone.utc), "sign_out", "ok", None, None, {}, None)])
    with engine.begin() as c:
        c.execute(text("INSERT INTO audit_events (correlation_id, user_id, session_id, event_type, outcome) "
                       "SELECT :c, id, :s, 'sign_out', 'ok' FROM users WHERE id <> :a LIMIT 1"),
                  {"c": intruder_id, "s": sid, "a": alice.login["user_id"]})
    groups = timeline(alice.client, sid).json()["items"]
    assert str(intruder_id) not in {g["correlation_id"] for g in groups}


def test_the_timeline_response_holds_only_metadata(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    answer = env.ask(sid, "alpha CONFIDENTIAL-QUESTION-WORDS about heavy drinking", "both").json()
    text_body = timeline(env.client, sid).text
    for needle in ("CONFIDENTIAL-QUESTION-WORDS", "heavy drinking", "Alpha chunk", answer["content"][:40]):
        assert needle not in text_body


# ---------------------------------------------------------------- administrator views

ADMIN_URLS = ("/api/admin/audit/events", "/api/admin/audit/summary")


@pytest.mark.parametrize("url", ADMIN_URLS)
def test_admin_audit_endpoints_are_403_for_students_and_401_when_signed_out(make_client, anon_client, url):
    assert make_client("student").get(url).status_code == 403
    assert anon_client.get(url).status_code == 401
    assert make_client("admin").get(url).status_code == 200


def test_admin_events_are_paginated_filtered_and_metadata_only(answer_env, answers_corpus, engine):
    student, admin = answer_env(), answer_env(role="admin")
    sid = student.new_session()
    student.ask(sid, QUESTION, "rag")
    student.ask(sid, "completely unrelated words", "rag")
    uid = str(student.login["user_id"])
    everything = admin.client.get("/api/admin/audit/events", params={"user_id": uid, "limit": 100}).json()
    total = everything["total"]
    assert total == len(everything["items"]) >= 25
    newest = [e["occurred_at"] for e in everything["items"]]
    assert newest == sorted(newest, reverse=True)
    page = admin.client.get("/api/admin/audit/events", params={"user_id": uid, "limit": 5, "offset": 5}).json()
    assert page["total"] == total and len(page["items"]) == 5 and page["items"] == everything["items"][5:10]
    answers = admin.client.get("/api/admin/audit/events", params={"user_id": uid, "event_type": "answer_returned"}).json()
    assert answers["total"] == 2 and {e["metadata"]["result"] for e in answers["items"]} == {"answered", "no_evidence"}
    none = admin.client.get("/api/admin/audit/events", params={"user_id": uid, "outcome": "error"}).json()
    assert none["total"] == 0
    denied = admin.client.get("/api/admin/audit/events", params={"event_type": "answer_returned", "outcome": "ok", "user_id": uid}).json()
    assert denied["total"] == 2
    for event in everything["items"]:
        assert set(event) == {"event_id", "event_type", "outcome", "occurred_at", "latency_ms", "error_code", "seq", "metadata",
                              "correlation_id", "request_id", "user_id", "session_id"}
    body = admin.client.get("/api/admin/audit/events", params={"user_id": uid, "limit": 100}).text
    for needle in ("heavy drinking", "Alpha chunk", "email", "@"):
        assert needle not in body
    assert admin.client.get("/api/admin/audit/events", params={"event_type": "email_sent"}).status_code == 422
    assert admin.client.get("/api/admin/audit/events", params={"user_id": "x"}).status_code == 422
    assert admin.client.get("/api/admin/audit/events", params={"limit": 101}).status_code == 422


def test_admin_events_filter_by_date_range(make_client, engine):
    admin = make_client("admin")
    seed(engine, [(day(2003, 3, 1), "sign_out", "ok", None, None, {}, None), (day(2003, 3, 5), "sign_out", "ok", None, None, {}, None),
                  (day(2003, 3, 9), "sign_out", "ok", None, None, {}, None)])
    got = admin.get("/api/admin/audit/events", params={"date_from": "2003-03-02T00:00:00Z", "date_to": "2003-03-09T00:00:00Z"}).json()
    assert got["total"] == 1 and got["items"][0]["occurred_at"].startswith("2003-03-05")
    assert admin.get("/api/admin/audit/events", params={"date_from": "garbage"}).status_code == 422


def test_the_admin_summary_numbers_are_correct_on_seeded_data(make_client, engine):
    admin = make_client("admin")
    rows = []
    for latency, result in ((100, "answered"), (200, "answered"), (300, "answered"), (400, "no_evidence"), (1000, "no_evidence")):
        rows.append((day(2001, 5, 1), "answer_returned", "ok", latency, None, {"result": result}, None))
    rows += [(day(2001, 5, 1), "pipeline_error", "error", 50, "llm_timeout", {}, None),
             (day(2001, 5, 2), "answer_returned", "skipped", 1, None, {"replayed": True}, None),   # a replay is not an answer
             (day(2001, 5, 2), "sign_out", "ok", None, None, {}, None),
             (day(2001, 5, 2), "sign_out", "ok", None, None, {}, None),
             (day(2001, 6, 1), "answer_returned", "ok", 99999, None, {"result": "answered"}, None)]   # outside the range
    seed(engine, rows)
    summary = admin.get("/api/admin/audit/summary", params={"date_from": "2001-05-01T00:00:00Z", "date_to": "2001-05-31T00:00:00Z"}).json()
    assert summary["answers_returned"] == 5 and summary["pipeline_errors"] == 1
    assert summary["error_rate"] == pytest.approx(1 / 6, abs=1e-4)
    assert summary["no_evidence_rate"] == 0.4
    assert summary["answer_latency_p50_ms"] == 300.0
    assert summary["answer_latency_p95_ms"] == pytest.approx(880.0)
    per_day = {(r["day"], r["event_type"]): r["count"] for r in summary["per_day"]}
    assert per_day == {("2001-05-01", "answer_returned"): 5, ("2001-05-01", "pipeline_error"): 1,
                       ("2001-05-02", "answer_returned"): 1, ("2001-05-02", "sign_out"): 2}
    assert summary["audit_write_failures"] >= 0 and summary["date_from"].startswith("2001-05-01")


def test_the_admin_summary_without_data_has_null_rates(make_client):
    summary = make_client("admin").get("/api/admin/audit/summary", params={"date_from": "1999-01-01T00:00:00Z", "date_to": "1999-01-02T00:00:00Z"}).json()
    assert summary["per_day"] == [] and summary["answers_returned"] == 0
    assert summary["error_rate"] is None and summary["no_evidence_rate"] is None and summary["answer_latency_p95_ms"] is None


def test_the_openapi_describes_the_audit_endpoints(client):
    spec = client.get("/openapi.json").json()
    for path in ("/api/audit/timeline", "/api/admin/audit/events", "/api/admin/audit/summary"):
        assert "get" in spec["paths"][path] and spec["paths"][path]["get"]["description"]
    assert {"audit"} <= {t["name"] for t in spec["tags"]}
