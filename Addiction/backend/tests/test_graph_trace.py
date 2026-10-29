"""The execution trace: statistics only, persisted, readable by its owner only; and the properties of the graph itself
(no checkpointer, no remote tracing, no network)."""
import json
import operator
import os
import socket
import typing
import uuid

import pytest
from sqlalchemy import text

from app.graph.state import GraphState
from app.graph.trace import NODE_ORDER, TraceEvent

QUESTION = "alpha question about heavy drinking"
SECRET_QUESTION = "alpha CONFIDENTIAL-QUESTION-WORDS about heavy drinking"


def ask_ok(env, content, mode="both", sid=None, **kwargs):
    response = env.ask(sid or env.new_session(), content, mode, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------- what is in the trace

def test_every_event_has_the_documented_shape_and_the_request_id_as_correlation_id(answer_env, answers_corpus):
    env = answer_env()
    response = env.ask(env.new_session(), QUESTION, "rag")
    body = response.json()
    for event in body["execution_trace"]:
        parsed = TraceEvent(**event)
        assert parsed.correlation_id == response.headers["X-Request-ID"]
        assert all(isinstance(v, (int, float, bool)) for v in parsed.counts.values())
        assert parsed.reason or parsed.status == "ok"
    executed = [e for e in body["execution_trace"] if e["status"] != "skipped"]
    assert all(e["started_at"] and e["duration_ms"] >= 0 for e in executed)
    assert [e["started_at"] for e in executed] == sorted(e["started_at"] for e in executed)  # in the order they ran


def test_the_trace_contains_no_question_patient_chunk_or_answer_text(answer_env, answers_corpus, engine):
    env = answer_env()
    body = ask_ok(env, SECRET_QUESTION, "both")
    with engine.connect() as c:
        stored = json.dumps(c.scalar(text("SELECT trace FROM chat_messages WHERE message_id = :m"), {"m": body["message_id"]}))
        facts = c.execute(text("SELECT living_situation, background, history_summary FROM patients WHERE patient_id = 'P-001'")).one()
    api = json.dumps(body["execution_trace"])
    forbidden = ["CONFIDENTIAL-QUESTION-WORDS", "heavy drinking", "naltrexone reduced", "Alpha chunk", "Second chunk",
                 "Ignore previous instructions", "The hypothetical patient", "psychosocial support", body["content"][:40], *facts]
    for blob in (stored, api):
        for needle in forbidden:
            assert needle not in blob, needle


def test_the_trace_is_persisted_with_the_graph_version(answer_env, answers_corpus, engine):
    env = answer_env()
    body = ask_ok(env, QUESTION, "rag")
    with engine.connect() as c:
        trace, version = c.execute(text("SELECT trace, graph_version FROM chat_messages WHERE message_id = :m"),
                                   {"m": body["message_id"]}).one()
        user_row = c.execute(text("SELECT trace, graph_version FROM chat_messages WHERE message_id = :m"),
                             {"m": body["user_message_id"]}).one()
    assert [e["node"] for e in trace] == list(NODE_ORDER) and version == "graph-v1" == body["graph_version"]
    assert user_row == (None, None)  # only the assistant message carries a trace


def test_the_same_trace_comes_back_from_the_endpoint_the_message_list_and_a_replay(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    body = ask_ok(env, QUESTION, "rag", sid, key="trace-key-0001")
    endpoint = env.client.get(f"/api/sessions/{sid}/messages/{body['message_id']}/trace")
    assert endpoint.status_code == 200
    assert endpoint.json() == {"message_id": body["message_id"], "graph_version": "graph-v1", "execution_trace": body["execution_trace"]}
    listed = env.client.get(f"/api/sessions/{sid}/messages").json()["items"][-1]["answer"]
    replay = env.ask(sid, QUESTION, "rag", key="trace-key-0001").json()
    assert listed["execution_trace"] == replay["execution_trace"] == body["execution_trace"]
    assert listed["classification"] == body["classification"] and listed["graph_version"] == "graph-v1"


# ---------------------------------------------------------------- who may read it

def test_only_the_owner_may_read_a_trace(answer_env, answers_corpus):
    alice, bob = answer_env(), answer_env()
    sid = alice.new_session()
    body = ask_ok(alice, QUESTION, "rag", sid)
    url = f"/api/sessions/{sid}/messages/{body['message_id']}/trace"
    assert alice.client.get(url).status_code == 200
    assert bob.client.get(url).status_code == 404


def test_unknown_user_message_and_malformed_ids(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    body = ask_ok(env, QUESTION, "rag", sid)
    base = f"/api/sessions/{sid}/messages"
    assert env.client.get(f"{base}/{uuid.uuid4()}/trace").status_code == 404
    assert env.client.get(f"{base}/{body['user_message_id']}/trace").status_code == 404  # a user message has no trace
    assert env.client.get(f"/api/sessions/{uuid.uuid4()}/messages/{body['message_id']}/trace").status_code == 404
    assert env.client.get(f"{base}/not-a-uuid/trace").status_code == 422
    other = env.new_session()  # the message belongs to another session of the same user
    assert env.client.get(f"/api/sessions/{other}/messages/{body['message_id']}/trace").status_code == 404


def test_the_trace_endpoint_needs_a_login(answer_env, anon_client):
    url = f"/api/sessions/{uuid.uuid4()}/messages/{uuid.uuid4()}/trace"
    assert anon_client.get(url).status_code == 401


# ---------------------------------------------------------------- properties of the graph

def test_the_trace_lists_are_append_only_in_the_state_definition():
    hints = typing.get_type_hints(GraphState, include_extras=True)
    for name in ("execution_trace", "user_trace"):
        assert hints[name].__metadata__[0] is operator.add  # nodes return only what they add; nothing is overwritten


def test_there_is_no_checkpointer_and_no_remote_tracing(answer_env):
    env = answer_env()
    graph = env.app.state.answer_pipeline.graph
    assert graph.checkpointer is None and graph.store is None
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
        assert os.environ[name] == "false"
    assert "LANGSMITH_API_KEY" not in os.environ and "LANGCHAIN_API_KEY" not in os.environ


def test_the_workflow_makes_no_python_level_network_connection(answer_env, answers_corpus, monkeypatch):
    env = answer_env()
    sid = env.new_session()

    def refuse(*args, **kwargs):
        raise AssertionError("the workflow tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for question, mode in ((QUESTION, "both"), ("completely unrelated words", "rag"), ("What dose should he take?", "rag")):
        assert env.ask(sid, question, mode).status_code == 201


def test_one_compiled_graph_is_shared_by_concurrent_runs(answer_env):
    env = answer_env()
    assert env.app.state.answer_pipeline.graph is env.app.state.answer_pipeline.graph
    other = answer_env()
    assert env.app.state.answer_pipeline.graph is other.app.state.answer_pipeline.graph  # compiled once per process


@pytest.mark.parametrize("node", NODE_ORDER)
def test_the_node_names_are_part_of_the_diagram(node):
    from app.graph.__main__ import mermaid
    assert node in mermaid()


def test_the_checked_in_diagram_is_the_one_the_compiled_graph_draws():
    from pathlib import Path

    from app.graph.__main__ import mermaid

    docs = Path(__file__).resolve().parents[2] / "docs"
    drawn = mermaid().strip()
    assert (docs / "orchestration.mmd").read_text(encoding="utf-8").strip() == drawn, "run: python -m app.graph --diagram > docs/orchestration.mmd"
    assert drawn in (docs / "ORCHESTRATION.md").read_text(encoding="utf-8")  # the document shows the same diagram
