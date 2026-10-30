"""Privacy by construction: the audit log of real runs contains no question, patient or chunk text, prompts, answers,
titles, tokens, keys, e-mail addresses, IP addresses or user agents."""
import json
import re

import httpx
import pytest
from sqlalchemy import text

from tests.audit_helpers import of_user, read
from tests.fake_llm import TEST_KEY

SECRET_QUESTION = "alpha CONFIDENTIAL-QUESTION-WORDS about heavy drinking zebra-marker"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
IPV4 = re.compile(r"(?<!\d)\d{1,3}(\.\d{1,3}){3}(?!\d)")
IPV6 = re.compile(r"(?:[0-9a-fA-F]{1,4}:){2,}")


def dump(events: list[dict]) -> str:
    """Every stored field except the timestamp (whose hh:mm:ss would look like an IPv6 address to the scan)."""
    return json.dumps([{k: v for k, v in e.items() if k != "occurred_at"} for e in events], default=str, sort_keys=True)


def test_nothing_sensitive_is_stored_for_a_full_run_of_every_kind(answer_env, answers_corpus, engine, clean_chat):
    env = answer_env(role="student")
    # the user's e-mail address (for the scan) and the patient's facts
    with engine.connect() as c:
        email = c.scalar(text("SELECT email FROM users WHERE id = :u"), {"u": env.login["user_id"]})
        facts = [v for row in c.execute(text(
            "SELECT living_situation, background, history_summary, treatment_summary, social_context FROM patients WHERE patient_id = 'P-001'")) for v in row]
        chunks = [r[0] for r in c.execute(text("SELECT text FROM paper_chunks WHERE paper_id = 'test-ans-a'"))]
    assert email and facts and chunks
    title = "Private-Title-Marker"
    sid = env.client.post("/api/sessions", json={"patient_id": "P-001", "title": title}).json()["session_id"]
    env.client.get("/api/patients/P-001")
    answers = []
    for question, mode in ((SECRET_QUESTION, "both"), (SECRET_QUESTION, "rag"), ("What dose of naltrexone should he take zebra-marker?", "rag"),
                           ("I want to die zebra-marker", "both"), ("completely unrelated words zebra-marker", "rag"),
                           ("How is he doing zebra-marker?", "general_knowledge")):
        response = env.ask(sid, question, mode)
        assert response.status_code == 201
        answers.append(response.json())
    message_id = answers[0]["message_id"]
    assert env.client.post(f"/api/sessions/{sid}/messages/{message_id}/feedback",
                           json={"rating": "helpful", "reason": "clear"}).status_code == 201
    env.client.post("/api/auth/logout")

    blob = dump(of_user(engine, env.login["user_id"]))
    assert len(blob) > 3000                                                   # there is a lot to scan
    forbidden = [SECRET_QUESTION, "CONFIDENTIAL-QUESTION-WORDS", "zebra-marker", "heavy drinking", title, email, email.split("@")[0],
                 TEST_KEY, env.login["token"], env.login["csrf"], "Bearer", "testclient", "python-httpx", "User-Agent", "testserver",
                 "127.0.0.1", "localhost", "naltrexone", "dose", "ESCALATION"]
    for answer in answers:
        forbidden += [answer["content"][:60]] if answer["content"] else []
        for section in answer["sections"]:
            forbidden.append(section["text"][:40])
    forbidden += [f[:30] for f in facts if f] + [c[:40] for c in chunks]
    for needle in filter(None, forbidden):
        assert needle not in blob, needle
    for pattern in (EMAIL, IPV4, IPV6):
        assert not pattern.search(blob), pattern.pattern


def test_a_failed_run_stores_no_provider_text_or_keys(answer_env, answers_corpus, engine):
    env = answer_env(lambda p, n: httpx.Response(500, json={"error": f"{TEST_KEY} provider said: leaked words"}), llm_changes={"max_retries": 0})
    sid = env.new_session()
    assert env.ask(sid, SECRET_QUESTION, "rag").status_code == 503
    blob = dump(read(engine, "session_id = :s", s=sid))
    for needle in (TEST_KEY, "leaked words", "provider said", "CONFIDENTIAL-QUESTION-WORDS", SECRET_QUESTION):
        assert needle not in blob


def test_the_stored_metadata_only_uses_the_documented_keys(answer_env, answers_corpus, engine):
    from app.audit.events import MODELS

    env = answer_env()
    sid = env.new_session()
    env.ask(sid, SECRET_QUESTION, "both")
    for event in read(engine, "session_id = :s", s=sid):
        allowed = set(MODELS[event["event_type"]].model_fields)
        assert set(event["metadata"]) <= allowed, (event["event_type"], set(event["metadata"]) - allowed)
        assert event["event_type"] != "answer_returned" or "content" not in event["metadata"]


def test_the_question_event_holds_a_length_not_the_text(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, SECRET_QUESTION, "rag")
    submitted = next(e for e in read(engine, "session_id = :s", s=sid) if e["event_type"] == "question_submitted")
    assert submitted["metadata"]["question_chars"] == len(SECRET_QUESTION)
    assert not any(isinstance(v, str) and len(v) > 40 for v in submitted["metadata"].values())


def test_no_forbidden_column_or_event_type_exists_for_email_features(engine):
    with engine.connect() as c:
        definition = c.scalar(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_audit_events_event_type_values'"))
        columns = {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_events'"))}
    assert "mail" not in definition.lower() and "gmail" not in definition.lower()
    assert not {"email", "ip", "ip_address", "user_agent", "question", "content", "prompt", "answer"} & columns
