"""The audit trail of a question: every event in order under one correlation id, the same node events as the stored trace,
failed runs with their partial trace, writes that survive a rolled-back answer, fail-open behaviour and replays."""
import json
import logging
import time
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from tests.answers_helpers import faithful_responder
from tests.audit_helpers import last_question, of_session, of_user, read, types
from tests.fake_llm import TEST_KEY

QUESTION = "alpha question about heavy drinking"
NODES = ["validate_inputs", "safety_screen", "classify_intent", "decide_retrieval", "execute_retrieval", "assess_evidence",
         "generate_answer", "validate_citations", "safety_check", "format_output"]


def stored_messages(engine, sid):
    with engine.connect() as c:
        return c.scalar(text("SELECT count(*) FROM chat_messages WHERE session_id = :s"), {"s": sid})


def ask_ok(env, content, mode="rag", sid=None, **kwargs):
    sid = sid or env.new_session()
    response = env.ask(sid, content, mode, **kwargs)
    assert response.status_code == 201, response.text
    return sid, response


# ---------------------------------------------------------------- a full question

def test_a_full_question_leaves_every_event_in_order_under_one_correlation_id(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, response = ask_ok(env, QUESTION, "rag")
    group = last_question(engine, sid)
    kinds = types(group)
    assert kinds[0] == "question_submitted" and kinds[-1] == "answer_returned"
    assert kinds.count("node_executed") == 10 and kinds.count("retrieval_executed") == 1
    assert kinds.count("llm_request") == 1 and kinds.count("citation_validated") == 1
    # derived events follow their node
    for node, derived in (("execute_retrieval", "retrieval_executed"), ("generate_answer", "llm_request"),
                          ("validate_citations", "citation_validated")):
        nodes = [e for e in group if e["event_type"] == "node_executed"]
        position = next(i for i, e in enumerate(group) if e["event_type"] == "node_executed" and e["metadata"]["node"] == node)
        assert group[position + 1]["event_type"] == derived, (node, nodes)
    assert [e["metadata"]["node"] for e in group if e["event_type"] == "node_executed"] == NODES
    assert len({e["correlation_id"] for e in group}) == 1
    assert {e["user_id"] for e in group} == {env.login["user_id"]} and {str(e["session_id"]) for e in group} == {sid}
    rid = response.headers["X-Request-ID"]
    assert {e["request_id"] for e in group} == {rid}                       # the client-side id is kept separately ...
    assert str(group[0]["correlation_id"]) != rid                           # ... and is not the correlation id
    assert [e["seq"] for e in group] == sorted(e["seq"] for e in group) and len({e["seq"] for e in group}) == len(group)


def test_the_correlation_id_is_server_generated_and_a_client_request_id_is_not_reused(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    client_id = str(uuid.uuid4())
    response = env.ask(sid, QUESTION, "rag", headers={"X-Request-ID": client_id})
    assert response.headers["X-Request-ID"] == client_id
    first = last_question(engine, sid)
    assert str(first[0]["correlation_id"]) != client_id and first[0]["request_id"] == client_id
    env.ask(sid, QUESTION, "rag", headers={"X-Request-ID": client_id})
    second = last_question(engine, sid)
    assert second[0]["correlation_id"] != first[0]["correlation_id"]       # a new question is a new correlation group


def test_latency_is_recorded_per_event_and_for_the_whole_answer(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, _ = ask_ok(env, QUESTION, "rag")
    group = last_question(engine, sid)
    executed = [e for e in group if e["event_type"] == "node_executed" and e["outcome"] == "ok"]
    assert executed and all(e["latency_ms"] is not None and e["latency_ms"] >= 0 for e in executed)
    answer = group[-1]
    assert answer["latency_ms"] is not None and answer["latency_ms"] >= max(e["latency_ms"] for e in executed)
    assert [e["occurred_at"] for e in group] == sorted(e["occurred_at"] for e in group)


def test_node_events_equal_the_stored_trace(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, response = ask_ok(env, QUESTION, "both")
    body = response.json()
    group = last_question(engine, sid)
    audited = [e for e in group if e["event_type"] == "node_executed"]
    trace = body["execution_trace"]
    assert [e["metadata"]["node"] for e in audited] == [t["node"] for t in trace]
    for event, entry in zip(audited, trace):
        assert event["metadata"]["status"] == entry["status"]
        assert event["metadata"].get("reason_code") == entry["reason_code"]
        assert event["metadata"].get("counts", {}) == entry["counts"]
        assert event["metadata"].get("chunk_ids", []) == entry["chunk_ids"]
        if entry["status"] == "skipped":
            assert event["outcome"] == "skipped" and event["latency_ms"] is None
        else:
            assert event["latency_ms"] == entry["duration_ms"]
    with engine.connect() as c:  # chat_messages.trace stays the per-message snapshot
        stored = c.scalar(text("SELECT trace FROM chat_messages WHERE message_id = :m"), {"m": body["message_id"]})
    assert stored == trace


def test_retrieval_llm_and_citation_events_carry_their_details(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, response = ask_ok(env, QUESTION, "rag")
    group = {e["event_type"]: e for e in last_question(engine, sid)}
    retrieval, llm, cites, answer = (group[k]["metadata"] for k in ("retrieval_executed", "llm_request", "citation_validated", "answer_returned"))
    assert retrieval["chunks"] >= 1 and retrieval["chunk_ids"] and retrieval["top_k"] == 5 and retrieval["attempt"] == 1
    assert retrieval["evidence_level"] in ("weak", "adequate")
    assert llm["model"] == "deepseek-chat" and llm["status"] == "ok" and llm["prompt_tokens"] > 0 and llm["retries"] == 0
    assert llm["config_fingerprint"] == group["question_submitted"]["metadata"]["config_fingerprint"]
    assert cites["citations"] >= 1 and cites["verified"] <= cites["citations"]
    assert answer["result"] == "answered" and answer["message_id"] == response.json()["message_id"] and answer["llm_called"] is True
    submitted = group["question_submitted"]["metadata"]
    assert submitted["mode"] == "rag" and submitted["question_chars"] == len(QUESTION) and submitted["idempotent"] is False
    assert submitted["prompt_version"] == "answer-v1" and submitted["top_k"] == 5
    assert len(submitted["config_fingerprint"]) == 12 and submitted["model"] == "deepseek-chat"


def test_the_configuration_fingerprint_changes_with_the_configuration(answer_env, answers_corpus, engine):
    first = answer_env(llm_changes={"model": "model-a"})
    second = answer_env(llm_changes={"model": "model-b"}, settings_changes={"answer_top_k": 3})
    prints = []
    for env in (first, second):
        sid, _ = ask_ok(env, QUESTION, "rag")
        prints.append(last_question(engine, sid)[0]["metadata"])
    assert prints[0]["config_fingerprint"] != prints[1]["config_fingerprint"]
    assert (prints[0]["model"], prints[1]["model"]) == ("model-a", "model-b") and prints[1]["top_k"] == 3


@pytest.mark.parametrize("content,mode,result,llm_called", [
    ("completely unrelated words", "rag", "no_evidence", False),
    ("What dose of naltrexone should he take?", "rag", "unsupported", False),
    ("I want to die", "both", "crisis", False),
])
def test_every_kind_of_answer_ends_with_answer_returned(answer_env, answers_corpus, engine, content, mode, result, llm_called):
    env = answer_env()
    sid, _ = ask_ok(env, content, mode)
    group = last_question(engine, sid)
    answer = group[-1]
    assert answer["event_type"] == "answer_returned" and answer["metadata"]["result"] == result
    assert answer["metadata"]["llm_called"] is llm_called and "llm_request" not in types(group)
    assert types(group).count("node_executed") == 10                      # skipped nodes are recorded as skipped
    assert any(e["outcome"] == "skipped" for e in group if e["event_type"] == "node_executed")


def test_a_follow_up_retry_records_two_retrieval_events(answer_env, answers_corpus, engine):
    env = answer_env()
    sid, _ = ask_ok(env, QUESTION, "rag")
    response = env.ask(sid, "and what about that?", "rag")
    assert response.status_code == 201
    retrievals = [e for e in last_question(engine, sid) if e["event_type"] == "retrieval_executed"]
    assert [r["metadata"]["attempt"] for r in retrievals] == list(range(1, len(retrievals) + 1)) and retrievals


# ---------------------------------------------------------------- failed runs

def bad_output(payload, call):
    return "this is not json"


def slow(payload, call):
    time.sleep(2.0)
    return faithful_responder(payload, call)


@pytest.mark.parametrize("responder,llm_changes,settings,status,code,failed_node", [
    (lambda p, n: httpx.ReadTimeout("t"), {"max_retries": 0}, {}, 504, "llm_timeout", "generate_answer"),
    (lambda p, n: httpx.Response(500, json={"error": TEST_KEY}), {"max_retries": 0}, {}, 503, "llm_unavailable", "generate_answer"),
    (bad_output, {}, {}, 502, "llm_bad_output", "generate_answer"),
    (slow, {"timeout_seconds": 1.0, "max_retries": 0}, {"graph_total_timeout_seconds": 1.5}, 504, None, "generate_answer"),
])
def test_a_failed_model_call_leaves_pipeline_error_and_the_partial_trace(
        answer_env, answers_corpus, engine, responder, llm_changes, settings, status, code, failed_node):
    env = answer_env(responder, llm_changes=llm_changes, settings_changes=settings)
    sid = env.new_session()
    response = env.ask(sid, QUESTION, "rag")
    assert response.status_code == status
    error_code = response.json()["error"]["code"]
    group = last_question(engine, sid)
    assert types(group)[0] == "question_submitted" and types(group)[-1] == "pipeline_error"
    assert "answer_returned" not in types(group)
    final = group[-1]
    assert final["outcome"] == "error" and final["error_code"] == error_code and (code is None or error_code == code)
    assert final["metadata"]["failed_node"] == failed_node and final["metadata"]["retrieval_chunks"] >= 1
    assert final["latency_ms"] is not None
    nodes = [e for e in group if e["event_type"] == "node_executed"]
    assert [e["metadata"]["node"] for e in nodes][:6] == NODES[:6]       # the nodes that ran before the failure ...
    assert nodes[-1]["metadata"]["node"] == failed_node and nodes[-1]["outcome"] == "error"  # ... and the failing one
    assert nodes[-1]["error_code"] == error_code
    assert "retrieval_executed" in types(group) and types(group).count("llm_request") == 1
    llm = next(e for e in group if e["event_type"] == "llm_request")
    assert llm["outcome"] == "error" and llm["metadata"]["status"] == "error"
    assert stored_messages(engine, sid) == 0                              # nothing was stored for the user
    assert TEST_KEY not in json.dumps([e["metadata"] for e in group], default=str)


def test_a_retrieval_timeout_is_recorded_at_the_retrieval_node(answer_env, answers_corpus, engine):
    env = answer_env(settings_changes={"graph_retrieval_timeout_seconds": 0.3})
    real = env.embedder.embed
    env.embedder.embed = lambda texts: (time.sleep(1.0), real(texts))[1]
    sid = env.new_session()
    assert env.ask(sid, QUESTION, "rag").status_code == 504
    group = last_question(engine, sid)
    assert group[-1]["event_type"] == "pipeline_error" and group[-1]["error_code"] == "workflow_timeout"
    assert group[-1]["metadata"]["failed_node"] == "execute_retrieval"
    retrieval = next(e for e in group if e["event_type"] == "retrieval_executed")
    assert retrieval["outcome"] == "error"


def test_the_rate_limit_and_an_idempotency_conflict_are_recorded_as_pipeline_errors(answer_env, answers_corpus, engine):
    env = answer_env(settings_changes={"answer_rate_limit_per_minute": 1})
    sid = env.new_session()
    assert env.ask(sid, QUESTION, "rag", key="conflict-key-1").status_code == 201
    conflict = env.ask(sid, "a different question", "rag", key="conflict-key-1")
    assert conflict.status_code == 409
    limited = env.ask(sid, QUESTION, "rag")
    assert limited.status_code == 429
    errors = [e for e in of_session(engine, sid) if e["event_type"] == "pipeline_error"]
    assert [e["error_code"] for e in errors] == ["idempotency_conflict", "rate_limited"]
    assert all(e["metadata"].get("failed_node") is None for e in errors)
    assert stored_messages(engine, sid) == 2                              # only the first, successful turn


def test_an_unexpected_exception_is_recorded_as_internal_error(answer_env, answers_corpus, engine, monkeypatch):
    env = answer_env()
    sid = env.new_session()
    from app.graph import nodes

    def boom(state, deps):
        raise RuntimeError("unexpected: " + state.question)

    monkeypatch.setattr(nodes, "decide_retrieval", boom)
    from app.graph.build import build_graph
    from app.answers.service import Pipeline
    env.app.state.answer_pipeline.graph = build_graph()  # rebuilt, so it uses the patched node
    with pytest.raises(RuntimeError):
        env.ask(sid, QUESTION, "rag")
    group = last_question(engine, sid)
    assert group[-1]["event_type"] == "pipeline_error" and group[-1]["error_code"] == "internal_error"
    assert group[-1]["metadata"]["failed_node"] == "decide_retrieval"
    assert QUESTION not in json.dumps([e["metadata"] for e in group], default=str)  # the exception text is never stored
    assert stored_messages(engine, sid) == 0


def test_events_survive_when_the_answer_transaction_rolls_back(answer_env, answers_corpus, engine, monkeypatch):
    """The answer is only stored in the last short phase. If that phase fails, the audit log (own transactions) keeps the run."""
    env = answer_env()
    sid = env.new_session()
    from app.repositories import answers as answers_repo

    def fail_to_store(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("the connection was lost"))

    monkeypatch.setattr(answers_repo, "insert_turn", fail_to_store)
    response = env.ask(sid, QUESTION, "rag")
    assert response.status_code == 503
    assert stored_messages(engine, sid) == 0
    group = last_question(engine, sid)
    assert types(group)[0] == "question_submitted" and types(group)[-1] == "pipeline_error"
    assert types(group).count("node_executed") == 10                        # the whole run happened, only the storing failed
    assert "llm_request" in types(group) and "answer_returned" not in types(group)


# ---------------------------------------------------------------- idempotent replay and refusals

def test_a_replay_records_a_skipped_answer_and_no_new_run(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    assert env.ask(sid, QUESTION, "rag", key="replay-key-01").status_code == 201
    again = env.ask(sid, QUESTION, "rag", key="replay-key-01")
    assert again.status_code == 201 and again.headers["Idempotency-Replayed"] == "true"
    events = of_session(engine, sid)
    submitted = [e for e in events if e["event_type"] == "question_submitted"]
    assert len(submitted) == 2 and submitted[0]["metadata"]["idempotent"] is True
    replay_group = [e for e in events if e["correlation_id"] == submitted[1]["correlation_id"]]
    assert types(replay_group) == ["question_submitted", "answer_returned"]
    assert replay_group[1]["outcome"] == "skipped" and replay_group[1]["metadata"]["replayed"] is True
    assert env.provider.count == 1


def test_asking_in_someone_elses_session_is_access_denied_and_not_a_question(answer_env, answers_corpus, engine):
    owner, intruder = answer_env(), answer_env()
    sid = owner.new_session()
    before = len(of_session(engine, sid))
    assert intruder.ask(sid, QUESTION, "rag").status_code == 404
    new = of_session(engine, sid)[before:]
    assert types(new) == ["access_denied"]
    event = new[0]
    assert event["user_id"] == intruder.login["user_id"] and event["outcome"] == "denied"
    assert event["metadata"] == {"route": "post_message", "reason_code": "not_owner"} and event["error_code"] == "not_owner"
    assert intruder.provider.count == 0
    unknown = intruder.ask(str(uuid.uuid4()), QUESTION, "rag")             # an unknown id is a plain 404: nothing to deny
    assert unknown.status_code == 404 and not of_user(engine, intruder.login["user_id"], "pipeline_error")


# ---------------------------------------------------------------- fail-open

def test_a_failing_audit_write_does_not_break_the_request(answer_env, answers_corpus, engine, monkeypatch, caplog):
    env = answer_env()
    sid = env.new_session()
    audit = env.app.state.audit
    from app.repositories import audit as audit_repo

    def broken(db, rows):
        raise OperationalError("INSERT", {}, Exception("connection refused " + QUESTION))

    monkeypatch.setattr(audit_repo, "insert_many", broken)
    before = audit.failures
    with caplog.at_level(logging.ERROR, logger="mindevidence.audit"):
        response = env.ask(sid, QUESTION, "rag")
    assert response.status_code == 201 and response.json()["content"]       # the user's request is not broken
    assert stored_messages(engine, sid) == 2                                 # the answer itself was stored
    assert audit.failures >= before + 2                                      # question_submitted and the final batch
    assert "audit_write_failed" in caplog.text and "OperationalError" in caplog.text
    assert QUESTION not in caplog.text and "connection refused" not in caplog.text  # a safe line: no exception text
    assert of_session(engine, sid) == [e for e in of_session(engine, sid) if e["event_type"] != "answer_returned"]


def test_the_failure_counter_reaches_the_admin_summary(answer_env, answers_corpus, monkeypatch):
    admin = answer_env(role="admin")
    from app.repositories import audit as audit_repo

    monkeypatch.setattr(audit_repo, "insert_many", lambda db, rows: (_ for _ in ()).throw(OperationalError("x", {}, Exception("y"))))
    sid = admin.new_session()
    assert admin.ask(sid, QUESTION, "rag").status_code == 201
    monkeypatch.undo()
    summary = admin.client.get("/api/admin/audit/summary").json()
    assert summary["audit_write_failures"] >= 2
