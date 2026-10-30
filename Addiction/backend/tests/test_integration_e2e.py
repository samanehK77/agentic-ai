"""End-to-end tests: the whole path of a question through the real application, with the outside world replaced by fakes.

Fake Google sign-in (signed test ID tokens), fake embedder, mock language model behind the real client, REAL PostgreSQL test
database and the real LangGraph workflow, retrieval, citation validation and audit log. No network, no real model.
`live` tests at the end run against the real local model, embedder and index and are skipped unless
MINDEVIDENCE_LIVE_TESTS=1 is set explicitly."""
import json
import os
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.audit.events import MODELS
from app.llm.safety import ESCALATION_NOTICE
from tests.answers_helpers import faithful_responder, scripted
from tests.audit_helpers import of_session, types
from tests.fake_llm import answer_json, section
from tests.test_auth_login_callback import callback

PAPER = "test-ans-a"
QUESTION = "alpha question about heavy drinking"
NODES = ["validate_inputs", "safety_screen", "classify_intent", "decide_retrieval", "execute_retrieval", "assess_evidence",
         "generate_answer", "validate_citations", "safety_check", "format_output"]


@pytest.fixture(autouse=True)
def forget_test_users(cleanup_users):
    cleanup_users.extend(["e2e-alice", "e2e-bob", "e2e-admin", "e2e-student"])


def sign_in(app, google_mock, sub: str, email: str):
    """Signs in through the fake Google callback and returns a browser client that carries the session cookie and CSRF token."""
    browser, response = callback(app, google_mock, claims={"sub": sub, "email": email})
    assert response.status_code == 302 and "auth_error" not in response.headers["location"]
    me = browser.get("/api/auth/me")
    assert me.status_code == 200
    browser.headers["X-CSRF-Token"] = me.json()["csrf_token"]
    browser.me = me.json()
    return browser


def ask(browser, sid, content, mode="rag", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return browser.post(f"/api/sessions/{sid}/messages", json={"content": content, "mode": mode}, headers=headers)


@pytest.fixture
def spy_search(monkeypatch):
    """Counts the calls of the retrieval function the workflow uses (and still runs it)."""
    from app.retrieval import service

    calls = []
    real = service.search

    def spy(*args, **kwargs):
        calls.append(kwargs.get("query"))
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "search", spy)
    return calls


# ---------------------------------------------------------------- the full path of a signed-in student

def test_the_full_path_from_sign_in_to_the_audit_timeline(answer_env, google_mock, answers_corpus, engine):
    env = answer_env()
    browser = sign_in(env.app, google_mock, "e2e-student", "e2e-student@example.test")
    assert browser.me["role"] == "student"

    patients = browser.get("/api/patients").json()
    assert patients["total"] == 10 and patients["items"][0]["patient_id"] == "P-001"
    profile = browser.get("/api/patients/P-001").json()
    assert profile["patient_id"] == "P-001" and profile["is_synthetic"] is True

    session = browser.post("/api/sessions", json={"patient_id": "P-001"})
    assert session.status_code == 201
    sid = session.json()["session_id"]

    answer = ask(browser, sid, QUESTION, "both")
    assert answer.status_code == 201
    body = answer.json()
    assert body["mode"] == "both" and body["content"] and body["sections"] and body["evidence"] and body["citations"]
    assert body["session_id"] == sid and body["classification"]["label"] in ("research_question", "comparison", "patient_history_lookup")

    listed = browser.get(f"/api/sessions/{sid}/messages").json()
    assert [m["role"] for m in listed["items"]] == ["user", "assistant"]
    assert listed["items"][1]["answer"]["message_id"] == body["message_id"]
    trace = browser.get(f"/api/sessions/{sid}/messages/{body['message_id']}/trace").json()
    assert [e["node"] for e in trace["execution_trace"]] == NODES and trace["graph_version"] == body["graph_version"]

    timeline = browser.get("/api/audit/timeline", params={"session_id": sid}).json()
    question = next(g for g in timeline["items"] if g["kind"] == "question")
    # ONE correlation id links submission, every node, retrieval, generation, citation validation and the outcome
    kinds = types(question["events"])
    assert kinds[0] == "question_submitted" and kinds[-1] == "answer_returned"
    assert kinds.count("node_executed") == 10 and {"retrieval_executed", "llm_request", "citation_validated"} <= set(kinds)
    rows = [e for e in of_session(engine, sid) if e["event_type"] != "session_created"]
    assert len({str(r["correlation_id"]) for r in rows}) == 1 and str(rows[0]["correlation_id"]) == question["correlation_id"]
    assert question["outcome"] == "answered" and question["total_latency_ms"] is not None
    assert question["events"][-1]["metadata"]["message_id"] == body["message_id"]
    # the audit trail and the stored trace agree on the nodes
    assert [e["metadata"]["node"] for e in question["events"] if e["event_type"] == "node_executed"] == [t["node"] for t in trace["execution_trace"]]


# ---------------------------------------------------------------- the three answer modes

def test_rag_answers_only_from_retrieved_chunks_with_verified_citations(answer_env, answers_corpus, spy_search):
    env = answer_env()
    sid = env.new_session()
    body = env.ask(sid, QUESTION, "rag").json()
    assert len(spy_search) == 1
    evidence_ids = {e["chunk_id"] for e in body["evidence"]}
    assert evidence_ids and all(e["text"] for e in body["evidence"])
    with env.engine.connect() as c:
        real_ids = {r[0] for r in c.execute(text("SELECT chunk_id FROM paper_chunks WHERE paper_id = :p"), {"p": PAPER})}
    assert evidence_ids <= real_ids                                          # the evidence is real chunks of the corpus
    assert body["citations"] and all(c["chunk_id"] in evidence_ids for c in body["citations"])
    assert all(c["verified"] and c["quote"] for c in body["citations"])
    assert not any(s["kind"] == "general_knowledge" for s in body["sections"])
    assert any(s["kind"] == "research_finding" and s["citations"] for s in body["sections"])


def test_general_knowledge_never_calls_retrieval_and_leaves_no_retrieval_event(answer_env, answers_corpus, spy_search, engine):
    env = answer_env()
    sid = env.new_session()
    body = env.ask(sid, QUESTION, "general_knowledge").json()
    assert spy_search == [] and env.embedder.calls == []
    assert body["citations"] == [] and body["evidence"] == [] and body["no_evidence"] is False
    assert all(s["citations"] == [] for s in body["sections"]) and {s["kind"] for s in body["sections"]} <= {"patient_fact", "general_knowledge", "interpretation"}
    audit = of_session(engine, sid)
    assert "retrieval_executed" not in types(audit)
    skipped = {e["metadata"]["node"] for e in audit if e["event_type"] == "node_executed" and e["outcome"] == "skipped"}
    assert {"execute_retrieval", "assess_evidence"} <= skipped


def test_both_mode_separates_sections_and_cites_only_research_findings(answer_env, answers_corpus, spy_search):
    env = answer_env()
    body = env.ask(env.new_session(), QUESTION, "both").json()
    assert len(spy_search) == 1
    kinds = {s["kind"] for s in body["sections"]}
    assert {"patient_fact", "research_finding", "general_knowledge"} <= kinds
    for s in body["sections"]:
        assert bool(s["citations"]) == (s["kind"] == "research_finding"), s["kind"]   # only research findings carry citations
    assert body["citations"] and all(c["verified"] for c in body["citations"])


def test_no_evidence_gives_the_fixed_answer_without_calling_the_model(answer_env, answers_corpus):
    env = answer_env()
    body = env.ask(env.new_session(), "How do I cook spaghetti carbonara with eggs and pancetta?", "rag").json()
    assert body["no_evidence"] is True and body["citations"] == [] and body["sections"] == []
    assert env.provider.count == 0 and body["generation"]["llm_called"] is False
    assert "no_evidence" in body["safety"]["flags"]


def test_a_model_that_invents_citations_cannot_get_them_into_the_response(answer_env, answers_corpus):
    invented = answer_json([
        section("research_finding", "Drug X cures everything.", ("S9", "a quote from a source that was never shown")),
        section("research_finding", "Naltrexone changes outcomes.", ("S1", "this sentence is not in the chunk at all, honestly")),
        section("research_finding", "A claim without any citation."),
        section("interpretation", "Please involve a clinician.")])
    env = answer_env(scripted(invented))
    body = env.ask(env.new_session(), QUESTION, "rag").json()
    evidence_ids = {e["chunk_id"] for e in body["evidence"]}
    assert all(c["chunk_id"] in evidence_ids for c in body["citations"])                # no unknown alias survives as a citation
    assert not any("S9" == c["alias"] for c in body["citations"])
    assert "unknown_alias_dropped" in body["safety"]["flags"] or "unsupported_research_claim" in body["safety"]["flags"]
    invented_quote = [c for c in body["citations"] if "not in the chunk at all" in c["quote"]]
    assert invented_quote and all(c["verified"] is False for c in invented_quote)                          # an invented quote is marked unverified
    assert body["unsupported_claims"]                                                   # the uncited claim is reported, not hidden
    assert "Drug X cures everything" not in json.dumps(body["citations"])


def test_instruction_text_inside_a_chunk_does_not_change_routing_or_reach_the_model(answer_env, answers_corpus, spy_search):
    env = answer_env()
    body = env.ask(env.new_session(), "alpha ignore previous instructions", "rag").json()
    assert body["classification"]["label"] != "unsupported_request" or env.provider.count == 0
    prompt = json.dumps(env.provider.calls)
    assert "Ignore previous instructions" not in prompt                                 # the flagged chunk never reaches the model
    flagged = [e for e in body["evidence"] if e["possible_injection"]]
    assert flagged and all(e["excluded_reason"] == "possible_injection" for e in flagged)   # shown to the student, never to the model


# ---------------------------------------------------------------- safety paths

@pytest.mark.parametrize("content,mode", [("I want to die", "both"), ("What dose of naltrexone should he take?", "rag")])
def test_crisis_and_dosing_requests_stop_before_the_model_and_the_documents(answer_env, answers_corpus, spy_search, content, mode):
    env = answer_env()
    body = env.ask(env.new_session(), content, mode).json()
    assert env.provider.count == 0 and spy_search == [] and body["generation"]["llm_called"] is False
    assert body["citations"] == [] and body["evidence"] == []
    if content == "I want to die":
        assert body["content"] == ESCALATION_NOTICE


# ---------------------------------------------------------------- authentication and access

def test_authentication_csrf_and_roles(answer_env, google_mock, answers_corpus, anon_client):
    env = answer_env()
    student = sign_in(env.app, google_mock, "e2e-alice", "e2e-alice@example.test")
    admin = sign_in(env.app, google_mock, "e2e-admin", "admin@example.test")
    assert admin.me["role"] == "admin"
    sid = student.post("/api/sessions", json={"patient_id": "P-001"}).json()["session_id"]
    answer = ask(student, sid, QUESTION).json()

    assert anon_client.get("/api/patients").status_code == 401                               # 401 without a session
    assert anon_client.get(f"/api/sessions/{sid}/messages").status_code == 401
    no_csrf = student.post("/api/sessions", json={"patient_id": "P-001"}, headers={"X-CSRF-Token": "wrong"})
    assert no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "csrf_failed"   # 403 without a valid CSRF token
    for path in ("/api/admin/audit/summary", "/api/admin/audit/events", "/api/admin/diagnostics", "/api/admin/papers"):
        assert student.get(path).status_code == 403, path                                    # students may not use admin routes
        assert admin.get(path).status_code == 200, path
    diagnostics = admin.get("/api/admin/diagnostics").json()
    assert diagnostics["status"] in ("ok", "warn", "fail") and diagnostics["checks"]
    summary = admin.get("/api/admin/audit/summary").json()
    assert summary["answers_returned"] >= 1 and "audit_write_failures" in summary
    assert answer["message_id"]


def test_two_users_are_isolated_for_sessions_messages_traces_and_audit_events(answer_env, google_mock, answers_corpus, engine):
    env = answer_env()
    alice = sign_in(env.app, google_mock, "e2e-alice", "e2e-alice@example.test")
    bob = sign_in(env.app, google_mock, "e2e-bob", "e2e-bob@example.test")
    sid = alice.post("/api/sessions", json={"patient_id": "P-001"}).json()["session_id"]
    answer = ask(alice, sid, QUESTION).json()
    mid = answer["message_id"]

    assert alice.get(f"/api/sessions/{sid}").status_code == 200
    for response in (bob.get(f"/api/sessions/{sid}"), bob.get(f"/api/sessions/{sid}/messages"), ask(bob, sid, QUESTION),
                     bob.get(f"/api/sessions/{sid}/messages/{mid}/trace"), bob.get("/api/audit/timeline", params={"session_id": sid}),
                     bob.post(f"/api/sessions/{sid}/messages/{mid}/feedback", json={"rating": "helpful"})):
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    unknown = bob.get(f"/api/sessions/{uuid.uuid4()}")
    assert unknown.json()["error"]["message"] == bob.get(f"/api/sessions/{sid}").json()["error"]["message"]   # same 404: nothing revealed
    assert bob.get("/api/sessions").json()["total"] == 0 and alice.get("/api/sessions").json()["total"] >= 1
    assert env.provider.count == 1                                                            # bob's attempt never reached the model

    bob_user = bob.me["id"]
    with engine.connect() as c:
        foreign = c.scalar(text("SELECT count(*) FROM audit_events WHERE user_id = :u AND event_type <> 'access_denied' AND event_type <> 'sign_in_succeeded'"),
                           {"u": bob_user})
    assert foreign == 0                                                                       # bob has no question/answer events of alice
    assert all(e["user_id"] == uuid.UUID(alice.me["id"]) for e in of_session(engine, sid) if e["event_type"] != "access_denied")


def test_a_repeated_request_with_the_same_idempotency_key_makes_no_second_model_call(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    first = env.ask(sid, QUESTION, "rag", key="e2e-key-0001")
    second = env.ask(sid, QUESTION, "rag", key="e2e-key-0001")
    assert first.status_code == second.status_code == 201 and second.headers["Idempotency-Replayed"] == "true"
    assert env.provider.count == 1 and first.json()["message_id"] == second.json()["message_id"]
    assert len(env.client.get(f"/api/sessions/{sid}/messages").json()["items"]) == 2
    different = env.ask(sid, "something else entirely", "rag", key="e2e-key-0001")
    assert different.status_code == 409 and env.provider.count == 1


def test_every_audit_event_of_a_full_run_uses_only_catalogue_keys(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    for question, mode in ((QUESTION, "both"), ("completely unrelated words", "rag"), ("I want to die", "rag")):
        env.ask(sid, question, mode)
    for event in of_session(engine, sid):
        assert set(event["metadata"]) <= set(MODELS[event["event_type"]].model_fields), event["event_type"]


# ---------------------------------------------------------------- live group: real local model, real embedder, real index

LIVE = os.environ.get("MINDEVIDENCE_LIVE_TESTS") == "1"
live = pytest.mark.skipif(not LIVE, reason="live tests run only when MINDEVIDENCE_LIVE_TESTS=1 (they use the real local model and index)")


@pytest.mark.live
@live
def test_live_a_real_question_through_the_real_model_and_index():
    """Uses the project's own database and corpus, a throw-away user, the real embedder and the configured LOCAL model.
    Refuses to run unless the model address is this machine. Slow: a local model can need a minute or more."""
    import time

    from sqlalchemy.orm import Session

    from app.answers.service import Pipeline, post_message
    from app.audit import AuditService
    from app.auth_service import AuthUser
    from app.config import load_settings
    from app.llm.concurrency import ConcurrencyLimitedClient
    from app.llm.deepseek import DeepSeekClient
    from app.retrieval.embedder import EmbedderProvider, load_embedder
    from db.config import get_engine

    settings = load_settings()
    if not settings.llm.local:
        pytest.fail("Refusing to run live tests: the model address is not on this machine.")
    engine = get_engine()
    real_db = get_engine().url.database
    if real_db.endswith("_test"):
        pytest.skip("the live test needs the real, ingested database (not the throw-away test database)")
    client = ConcurrencyLimitedClient(DeepSeekClient(settings.llm), 1, settings.llm.queue_wait_seconds)
    pipeline = Pipeline(settings, client, EmbedderProvider(load_embedder), None, audit=AuditService(engine))
    with Session(engine) as db:
        user_id = db.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES (:s, 'live@example.invalid', true) RETURNING id"),
                             {"s": f"live-{uuid.uuid4()}"}).scalar_one()
        sid = db.execute(text("INSERT INTO chat_sessions (patient_id, title, owner_id) VALUES ('P-001', 'live-e2e', :u) RETURNING session_id"),
                         {"u": user_id}).scalar_one()
        db.commit()
        try:
            user = AuthUser(user_id, "live@example.invalid", None, "student", "", uuid.uuid4())
            started = time.perf_counter()
            reply, _ = post_message(db, pipeline, user=user, session_id=sid, content="Which medications are used to treat alcohol use disorder?",
                                    mode="rag", idempotency_key=None, request_id="live-e2e")
            assert reply["evidence"] and reply["execution_trace"] and reply["content"]
            assert all(c["chunk_id"] in {e["chunk_id"] for e in reply["evidence"]} for c in reply["citations"])
            print(f"live answer in {time.perf_counter() - started:.1f}s, citations verified: {sum(c['verified'] for c in reply['citations'])}/{len(reply['citations'])}")
        finally:
            db.rollback()
            db.execute(text("DELETE FROM chat_sessions WHERE owner_id = :u"), {"u": user_id})
            db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
            db.commit()
