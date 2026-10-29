"""Idempotency-Key: a double submit never produces two model calls."""
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.answers_helpers import faithful_responder
from tests.conftest import sign_in

QUESTION = "alpha question about heavy drinking"
KEY = "key-0001-abcdef"


def rows(env, sid):
    with env.engine.connect() as c:
        return c.execute(text("SELECT role, idempotency_key, request_hash FROM chat_messages WHERE session_id = :s ORDER BY created_at"),
                         {"s": sid}).all()


def test_same_key_and_same_body_returns_the_stored_reply_with_one_model_call(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    first = env.ask(sid, QUESTION, "rag", key=KEY)
    second = env.ask(sid, QUESTION, "rag", key=KEY)
    assert (first.status_code, second.status_code) == (201, 201) and env.provider.count == 1
    assert second.headers["Idempotency-Replayed"] == "true" and "Idempotency-Replayed" not in first.headers
    a, b = first.json(), second.json()
    assert a["message_id"] == b["message_id"] and a["content"] == b["content"] and a["citations"] == b["citations"]
    assert a["sections"] == b["sections"] and a["generation"] == b["generation"] and a["trace"] == b["trace"]
    assert b["request_id"] == second.headers["X-Request-ID"] != a["request_id"]  # a replay still has its own request id
    assert len(rows(env, sid)) == 2  # still just one user message and one assistant message


def test_the_key_and_a_request_hash_are_stored_on_the_assistant_message_only(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag", key=KEY)
    user, assistant = rows(env, sid)
    assert user == ("user", None, None) and assistant[0] == "assistant" and assistant[1] == KEY and len(assistant[2]) == 64


def test_same_key_with_a_different_body_is_a_409_and_calls_nothing(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag", key=KEY)
    changed = env.ask(sid, "a different question", "rag", key=KEY)
    other_mode = env.ask(sid, QUESTION, "both", key=KEY)
    assert changed.status_code == other_mode.status_code == 409
    error = changed.json()["error"]
    assert error["code"] == "idempotency_conflict" and error["request_id"] == changed.headers["X-Request-ID"]
    assert env.provider.count == 1 and len(rows(env, sid)) == 2


def test_surrounding_whitespace_does_not_make_it_a_different_body(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag", key=KEY)
    assert env.ask(sid, f"  {QUESTION}  ", "rag", key=KEY).status_code == 201 and env.provider.count == 1


def test_a_failed_attempt_stores_nothing_so_the_same_key_can_be_retried(answer_env, answers_corpus):
    state = {"fail": True}

    def flaky(payload, call):
        return httpx.Response(503, text="down") if state["fail"] else faithful_responder(payload, call)

    env = answer_env(flaky)
    sid = env.new_session()
    failed = env.ask(sid, QUESTION, "rag", key=KEY)
    assert failed.status_code == 503 and rows(env, sid) == []
    state["fail"] = False
    retry = env.ask(sid, QUESTION, "rag", key=KEY)
    assert retry.status_code == 201 and "Idempotency-Replayed" not in retry.headers and len(rows(env, sid)) == 2
    calls_before = env.provider.count
    assert env.ask(sid, QUESTION, "rag", key=KEY).headers["Idempotency-Replayed"] == "true"
    assert env.provider.count == calls_before


def test_a_failure_after_the_key_was_used_for_another_body_is_still_a_conflict_not_a_new_call(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag", key=KEY)
    assert env.ask(sid, "different", "rag", key=KEY).status_code == 409


def test_without_a_key_every_request_is_a_new_turn(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag")
    env.ask(sid, QUESTION, "rag")
    assert env.provider.count == 2 and len(rows(env, sid)) == 4


def test_the_same_key_in_different_sessions_is_independent(answer_env, answers_corpus):
    env = answer_env()
    first, second = env.new_session(), env.new_session()
    env.ask(first, QUESTION, "rag", key=KEY)
    response = env.ask(second, QUESTION, "rag", key=KEY)
    assert response.status_code == 201 and "Idempotency-Replayed" not in response.headers and env.provider.count == 2


def test_replays_and_no_evidence_answers_work_without_the_model(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, "completely unrelated words", "rag", key=KEY)
    again = env.ask(sid, "completely unrelated words", "rag", key=KEY)
    assert again.headers["Idempotency-Replayed"] == "true" and env.provider.count == 0


def test_a_replay_does_not_use_up_the_rate_limit(answer_env, answers_corpus):
    env = answer_env(settings_changes={"answer_rate_limit_per_minute": 1})
    sid = env.new_session()
    assert env.ask(sid, QUESTION, "general_knowledge", key=KEY).status_code == 201
    for _ in range(3):
        assert env.ask(sid, QUESTION, "general_knowledge", key=KEY).status_code == 201  # replays are free
    assert env.ask(sid, "a new question", "general_knowledge").status_code == 429


def test_a_replay_is_read_from_the_stored_answer_and_marks_changed_chunks_stale(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag", key=KEY)
    with engine.begin() as c:
        c.execute(text("UPDATE paper_chunks SET text_sha256 = :h WHERE chunk_id = 'test-ans-a-c0001'"), {"h": "e" * 64})
    replay = env.ask(sid, QUESTION, "rag", key=KEY).json()
    assert env.provider.count == 1 and replay["citations"][0]["stale"] is True


def test_another_users_session_with_the_same_key_is_still_a_404(answer_env, answers_corpus):
    alice, bob = answer_env(), answer_env()
    sid = alice.new_session()
    alice.ask(sid, QUESTION, "rag", key=KEY)
    assert bob.ask(sid, QUESTION, "rag", key=KEY).status_code == 404 and bob.provider.count == 0


def test_two_simultaneous_submits_with_the_same_key_make_one_model_call(answer_env, answers_corpus):
    def slow(payload, call):
        time.sleep(0.6)  # long enough for the second request to arrive while the first is still running
        return faithful_responder(payload, call)

    env = answer_env(slow)
    sid = env.new_session()
    results: list[httpx.Response] = []

    def submit():
        client = TestClient(env.app, base_url="http://testserver.local")
        sign_in(client, env.login)
        with client:
            results.append(client.post(f"/api/sessions/{sid}/messages", json={"content": QUESTION, "mode": "rag"},
                                       headers={"Idempotency-Key": KEY}))

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
        time.sleep(0.15)
    for thread in threads:
        thread.join()
    assert [r.status_code for r in results] == [201, 201] and env.provider.count == 1
    assert results[0].json()["message_id"] == results[1].json()["message_id"] and len(rows(env, sid)) == 2
    assert sorted(r.headers.get("Idempotency-Replayed", "false") for r in results) == ["false", "true"]


@pytest.mark.parametrize("key", ["a" * 8, "A.b_c-1234", "x" * 64])
def test_valid_key_shapes_are_accepted(answer_env, answers_corpus, key):
    env = answer_env()
    assert env.ask(env.new_session(), QUESTION, "general_knowledge", key=key).status_code == 201
