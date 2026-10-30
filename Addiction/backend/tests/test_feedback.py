"""Optional student feedback on an answer: owner only, fixed codes, idempotent, shown inside the question's timeline group."""
import threading
import uuid

import pytest

from tests.audit_helpers import of_session, read, types

QUESTION = "alpha question about heavy drinking"


def asked(env):
    sid = env.new_session()
    body = env.ask(sid, QUESTION, "rag").json()
    return sid, body["message_id"], body["user_message_id"]


def url(sid, mid):
    return f"/api/sessions/{sid}/messages/{mid}/feedback"


def test_feedback_is_recorded_once_with_a_fixed_reason(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, mid, _ = asked(env)
    response = env.client.post(url(sid, mid), json={"rating": "helpful", "reason": "good_sources"})
    assert response.status_code == 201
    assert response.json() == {"message_id": mid, "rating": "helpful", "reason": "good_sources", "already_recorded": False}
    (event,) = [e for e in of_session(engine, sid) if e["event_type"] == "feedback_submitted"]
    assert event["metadata"] == {"message_id": mid, "rating": "helpful", "reason": "good_sources"} and event["user_id"] == env.login["user_id"]
    assert event["outcome"] == "ok"


def test_the_reason_is_optional(answer_env, answers_corpus):
    env = answer_env()
    sid, mid, _ = asked(env)
    response = env.client.post(url(sid, mid), json={"rating": "not_helpful"})
    assert response.status_code == 201 and response.json()["reason"] is None


def test_feedback_is_idempotent_and_the_first_rating_stands(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, mid, _ = asked(env)
    assert env.client.post(url(sid, mid), json={"rating": "helpful", "reason": "clear"}).status_code == 201
    again = env.client.post(url(sid, mid), json={"rating": "not_helpful", "reason": "unsafe"})
    assert again.status_code == 200
    assert again.json() == {"message_id": mid, "rating": "helpful", "reason": "clear", "already_recorded": True}
    assert len([e for e in of_session(engine, sid) if e["event_type"] == "feedback_submitted"]) == 1


def test_two_simultaneous_submissions_store_one_event(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, mid, _ = asked(env)
    statuses = []

    def post():
        statuses.append(env.client.post(url(sid, mid), json={"rating": "helpful"}).status_code)

    threads = [threading.Thread(target=post) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [200, 200, 200, 201]
    assert len([e for e in of_session(engine, sid) if e["event_type"] == "feedback_submitted"]) == 1


def test_feedback_joins_the_correlation_group_of_its_answer(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, mid, _ = asked(env)
    env.client.post(url(sid, mid), json={"rating": "helpful"})
    group = env.client.get("/api/audit/timeline", params={"session_id": sid}).json()["items"]
    question = next(g for g in group if g["kind"] == "question")
    assert types(question["events"])[-1] == "feedback_submitted" and types(question["events"])[0] == "question_submitted"
    assert question["outcome"] == "answered"


def test_each_user_may_rate_the_same_message_only_in_their_own_session(answer_env, answers_corpus):
    alice, bob = answer_env(), answer_env()
    sid, mid, _ = asked(alice)
    assert bob.client.post(url(sid, mid), json={"rating": "helpful"}).status_code == 404
    assert alice.client.post(url(sid, mid), json={"rating": "helpful"}).status_code == 201


@pytest.mark.parametrize("make_target", [
    lambda sid, mid, umid: (sid, uuid.uuid4()),            # unknown message
    lambda sid, mid, umid: (sid, umid),                    # a question message cannot be rated
    lambda sid, mid, umid: (uuid.uuid4(), mid),            # unknown session
])
def test_unknown_targets_are_404(answer_env, answers_corpus, make_target):
    env = answer_env()
    sid, mid, umid = asked(env)
    target_sid, target_mid = make_target(sid, mid, umid)
    assert env.client.post(url(target_sid, target_mid), json={"rating": "helpful"}).status_code == 404


def test_the_message_must_belong_to_that_session(answer_env, answers_corpus):
    env = answer_env()
    sid, mid, _ = asked(env)
    other = env.new_session()
    assert env.client.post(url(other, mid), json={"rating": "helpful"}).status_code == 404


@pytest.mark.parametrize("body", [
    {}, {"rating": "great"}, {"rating": "helpful", "reason": "free text here"}, {"rating": "helpful", "comment": "free text"},
    {"rating": "helpful", "reason": "x" * 500}, {"rating": None},
])
def test_only_fixed_codes_are_accepted(answer_env, answers_corpus, body):
    env = answer_env()
    sid, mid, _ = asked(env)
    assert env.client.post(url(sid, mid), json=body).status_code == 422


def test_malformed_ids_are_422_and_it_needs_a_login_and_the_csrf_token(answer_env, answers_corpus, anon_client):
    env = answer_env()
    sid, mid, _ = asked(env)
    assert env.client.post(url(sid, "not-a-uuid"), json={"rating": "helpful"}).status_code == 422
    assert env.client.post(url("nope", mid), json={"rating": "helpful"}).status_code == 422
    assert anon_client.post(url(sid, mid), json={"rating": "helpful"}).status_code == 401
    no_csrf = env.client.post(url(sid, mid), json={"rating": "helpful"}, headers={"X-CSRF-Token": "wrong"})
    assert no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "csrf_failed"


def test_a_failure_to_save_feedback_is_a_503_not_silent(answer_env, answers_corpus, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.repositories import audit as audit_repo

    env = answer_env()
    sid, mid, _ = asked(env)
    monkeypatch.setattr(audit_repo, "insert_many", lambda db, rows: (_ for _ in ()).throw(OperationalError("x", {}, Exception("y"))))
    response = env.client.post(url(sid, mid), json={"rating": "helpful"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"
    assert env.app.state.audit.failures >= 1
