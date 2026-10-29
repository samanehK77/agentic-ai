"""Migration 0006 (answers on chat_messages) and the rules of the new columns."""
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from tests.conftest import alembic_config, recreate_database
from tests.test_constraints import must_fail

NEW_COLUMNS = {"response", "generation", "idempotency_key", "request_hash"}


def test_0006_applies_to_existing_messages_and_downgrades_cleanly():
    url = recreate_database("test_migration6")
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0005")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES ('m6', 'm6@example.test', true)"))
            connection.execute(text("""
                INSERT INTO patients (patient_id, age_at_intake, gender, primary_category, intake_date, living_situation,
                    employment_status, social_context, co_occurring_symptoms, motivation_at_intake, background,
                    history_summary, treatment_summary)
                VALUES ('P-099', 40, 'man', 'alcohol', '2026-01-01', 'a', 'b', 'c', 'd', 'unknown', 'e', 'f', 'g')"""))
            connection.execute(text(
                "INSERT INTO chat_sessions (patient_id, title, owner_id) SELECT 'P-099', 't', id FROM users"))
            connection.execute(text(
                "INSERT INTO chat_messages (session_id, role, mode, content) SELECT session_id, 'assistant', 'rag', 'old reply' FROM chat_sessions"))

        command.upgrade(config, "0006")
        assert NEW_COLUMNS <= {c["name"] for c in inspect(engine).get_columns("chat_messages")}
        with engine.connect() as connection:
            row = connection.execute(text("SELECT content, response, generation, idempotency_key, request_hash FROM chat_messages")).one()
        assert row == ("old reply", None, None, None, None)  # old messages are untouched

        command.downgrade(config, "0005")
        assert not NEW_COLUMNS & {c["name"] for c in inspect(engine).get_columns("chat_messages")}
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT content FROM chat_messages")) == "old reply"
            assert connection.scalar(text(
                "SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_chat_messages_session_idempotency'")) == 0
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.fixture
def session_id(conn):
    conn.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES ('m6b', 'm6b@example.test', true)"))
    return conn.scalar(text(
        "INSERT INTO chat_sessions (patient_id, title, owner_id) SELECT 'P-001', 't', id FROM users WHERE google_sub = 'm6b' RETURNING session_id"))


INSERT = text("""INSERT INTO chat_messages (session_id, role, mode, content, response, generation, idempotency_key, request_hash)
                 VALUES (:s, :role, 'rag', 'text', CAST(:r AS jsonb), CAST(:g AS jsonb), :k, :h)""")
VALID = {"role": "assistant", "r": '{"v": 1}', "g": '{"llm_called": true}', "k": "key-12345678", "h": "a" * 64}


def test_a_valid_assistant_message_with_an_answer_inserts(conn, session_id):
    conn.execute(INSERT, {**VALID, "s": session_id})


def test_user_messages_cannot_carry_answers_or_keys(conn, session_id):
    for change in ({"role": "user"}, {"role": "user", "r": None, "g": '{}'}, {"role": "user", "r": None, "g": None}):
        must_fail(conn, INSERT, {**VALID, "s": session_id, **change})


@pytest.mark.parametrize("change", [
    {"k": "short"}, {"k": "has space in key"}, {"k": "x" * 65}, {"k": "semi;colon;key1"}, {"h": "not-a-hash"}, {"h": "A" * 64},
    {"k": None},          # a hash without a key
    {"h": None},          # a key without a hash
])
def test_key_and_hash_rules(conn, session_id, change):
    must_fail(conn, INSERT, {**VALID, "s": session_id, **change})


def test_the_key_is_unique_per_session_but_not_globally(conn, session_id):
    conn.execute(INSERT, {**VALID, "s": session_id})
    must_fail(conn, INSERT, {**VALID, "s": session_id})  # same session, same key
    other = conn.scalar(text("INSERT INTO chat_sessions (patient_id, title, owner_id) SELECT 'P-001', 't2', id FROM users "
                             "WHERE google_sub = 'm6b' RETURNING session_id"))
    conn.execute(INSERT, {**VALID, "s": other})        # same key in another session is fine


def test_messages_without_a_key_may_repeat(conn, session_id):
    for _ in range(3):
        conn.execute(INSERT, {**VALID, "s": session_id, "k": None, "h": None})


def test_deleting_a_session_removes_its_answers(conn, session_id):
    conn.execute(INSERT, {**VALID, "s": session_id})
    conn.execute(text("DELETE FROM chat_sessions WHERE session_id = :s"), {"s": session_id})
    assert conn.scalar(text("SELECT count(*) FROM chat_messages WHERE session_id = :s"), {"s": session_id}) == 0
