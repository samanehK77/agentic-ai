"""Time budgets, the busy model, and the rule that no database connection or lock is held while the model works."""
import threading
import time

import httpx
import pytest
from sqlalchemy import text

from tests.answers_helpers import faithful_responder

QUESTION = "alpha question about heavy drinking"


def stored(engine, sid):
    with engine.connect() as c:
        return c.scalar(text("SELECT count(*) FROM chat_messages WHERE session_id = :s"), {"s": sid})


def test_no_database_connection_is_checked_out_while_the_model_works(answer_env, answers_corpus, engine):
    seen = []

    def watching(payload, call):
        seen.append(engine.pool.checkedout())
        return faithful_responder(payload, call)

    env = answer_env(watching)
    assert env.ask(env.new_session(), QUESTION, "rag").status_code == 201
    assert seen == [0]  # the request's session was released before the run and is only reopened to store the result


def test_a_slow_model_ends_the_run_with_workflow_timeout_and_stores_nothing(answer_env, answers_corpus, engine):
    def slow(payload, call):
        time.sleep(2.0)
        return faithful_responder(payload, call)

    env = answer_env(slow, llm_changes={"timeout_seconds": 1.0, "max_retries": 0}, settings_changes={"graph_total_timeout_seconds": 1.5})
    sid = env.new_session()
    started = time.perf_counter()
    response = env.ask(sid, QUESTION, "rag", key="timeout-key-1")
    assert response.status_code == 504 and response.json()["error"]["code"] in ("workflow_timeout", "llm_timeout")
    assert time.perf_counter() - started < 1.9  # it did not wait for the model to finish
    assert stored(engine, sid) == 0


def test_a_slow_retrieval_ends_the_run_with_workflow_timeout(answer_env, answers_corpus, engine):
    env = answer_env(settings_changes={"graph_retrieval_timeout_seconds": 0.3})
    real = env.embedder.embed

    def slow(texts):
        time.sleep(1.0)
        return real(texts)

    env.embedder.embed = slow
    sid = env.new_session()
    response = env.ask(sid, QUESTION, "rag")
    assert response.status_code == 504 and response.json()["error"]["code"] == "workflow_timeout"
    assert env.provider.count == 0 and stored(engine, sid) == 0


def test_the_total_budget_must_exceed_the_model_timeout(engine):
    import dataclasses

    from app.config import StartupError, load_settings
    from app.main import create_app
    from tests.fake_llm import llm_settings

    settings = dataclasses.replace(load_settings(), llm=llm_settings(timeout_seconds=100.0), graph_total_timeout_seconds=50.0)
    with pytest.raises(StartupError, match="GRAPH_TOTAL_TIMEOUT_SECONDS"):
        create_app(engine=engine, settings=settings)


def test_the_remaining_workflow_time_caps_the_model_call(answer_env, answers_corpus):
    """The client is told how much time is left: its own per-call timeout can never outlast the workflow."""
    seen = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["read"] = request.extensions["timeout"]["read"]
        return httpx.Response(200, json={"model": "m", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    from app.llm.deepseek import DeepSeekClient
    from app.llm.base import LLMMessage
    from tests.fake_llm import llm_settings

    client = DeepSeekClient(llm_settings(timeout_seconds=100.0), transport=httpx.MockTransport(capture))
    client.complete([LLMMessage("user", "x")], timeout=2.0)
    assert seen["read"] <= 2.0
    from app.llm.base import LLMTimeout
    with pytest.raises(LLMTimeout):
        client.complete([LLMMessage("user", "x")], timeout=0)  # nothing left: no call is made


def test_a_second_question_waits_for_a_free_model_slot_and_then_gets_busy(answer_env, answers_corpus, engine):
    def slow(payload, call):
        time.sleep(0.8)
        return faithful_responder(payload, call)

    env = answer_env(slow, llm_changes={"max_concurrency": 1, "queue_wait_seconds": 0.2})
    sid = env.new_session()
    results = {}

    def ask(name, content):
        results[name] = env.ask(sid, content, "general_knowledge")

    first = threading.Thread(target=ask, args=("first", "alpha first question"))
    second = threading.Thread(target=ask, args=("second", "alpha second question"))
    first.start()
    time.sleep(0.25)
    second.start()
    first.join()
    second.join()
    assert results["first"].status_code == 201
    busy = results["second"]
    assert busy.status_code == 503 and busy.json()["error"]["code"] == "llm_unavailable"
    assert busy.headers["Retry-After"] == "30" and "busy" in busy.json()["error"]["message"]
    assert env.provider.count == 1 and stored(engine, sid) == 2  # the busy question stored nothing


def test_a_question_that_waits_less_than_the_queue_limit_is_answered(answer_env, answers_corpus):
    def slow(payload, call):
        time.sleep(0.3)
        return faithful_responder(payload, call)

    env = answer_env(slow, llm_changes={"max_concurrency": 1, "queue_wait_seconds": 5.0})
    sid = env.new_session()
    codes = []

    def ask(content):
        codes.append(env.ask(sid, content, "general_knowledge").status_code)

    threads = [threading.Thread(target=ask, args=(f"alpha question {n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
        time.sleep(0.05)
    for thread in threads:
        thread.join()
    assert codes == [201, 201] and env.provider.count == 2


def test_the_browser_may_read_the_retry_hint_cross_origin(answer_env):
    env = answer_env()
    response = env.client.get("/api/health", headers={"Origin": "http://localhost:8000"})
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "retry-after" in exposed and "x-request-id" in exposed
