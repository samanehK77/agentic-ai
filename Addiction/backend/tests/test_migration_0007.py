"""Migration 0007 (execution trace and graph version on chat_messages) and the rules of the new columns."""
import threading
import time

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.answers.locks import KeyedLocks
from tests.conftest import alembic_config, recreate_database
from tests.test_constraints import must_fail

NEW_COLUMNS = {"trace", "graph_version"}


def test_0007_keeps_old_messages_and_downgrades_cleanly():
    url = recreate_database("test_migration7")
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0006")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES ('m7', 'm7@example.test', true)"))
            connection.execute(text("""
                INSERT INTO patients (patient_id, age_at_intake, gender, primary_category, intake_date, living_situation,
                    employment_status, social_context, co_occurring_symptoms, motivation_at_intake, background,
                    history_summary, treatment_summary)
                VALUES ('P-099', 40, 'man', 'alcohol', '2026-01-01', 'a', 'b', 'c', 'd', 'unknown', 'e', 'f', 'g')"""))
            connection.execute(text("INSERT INTO chat_sessions (patient_id, title, owner_id) SELECT 'P-099', 't', id FROM users"))
            connection.execute(text(
                "INSERT INTO chat_messages (session_id, role, mode, content) SELECT session_id, 'assistant', 'rag', 'old reply' FROM chat_sessions"))

        command.upgrade(config, "0007")
        assert NEW_COLUMNS <= {c["name"] for c in inspect(engine).get_columns("chat_messages")}
        with engine.connect() as connection:
            row = connection.execute(text("SELECT content, trace, graph_version FROM chat_messages")).one()
        assert row == ("old reply", None, None)  # answers stored before the graph simply have no trace

        command.downgrade(config, "0006")
        assert not NEW_COLUMNS & {c["name"] for c in inspect(engine).get_columns("chat_messages")}
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT content FROM chat_messages")) == "old reply"
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.fixture
def session_id(conn):
    conn.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES ('m7b', 'm7b@example.test', true)"))
    return conn.scalar(text(
        "INSERT INTO chat_sessions (patient_id, title, owner_id) SELECT 'P-001', 't', id FROM users WHERE google_sub = 'm7b' RETURNING session_id"))


INSERT = text("""INSERT INTO chat_messages (session_id, role, mode, content, trace, graph_version)
                 VALUES (:s, :role, 'rag', 'text', CAST(:t AS jsonb), :v)""")
VALID = {"role": "assistant", "t": '[{"node": "validate_inputs"}]', "v": "graph-v1"}


def test_an_assistant_message_with_a_trace_inserts(conn, session_id):
    conn.execute(INSERT, {**VALID, "s": session_id})
    conn.execute(INSERT, {**VALID, "s": session_id, "t": "[]"})  # an empty trace is a valid array


def test_user_messages_cannot_carry_a_trace_or_a_graph_version(conn, session_id):
    for change in ({"role": "user"}, {"role": "user", "t": None}, {"role": "user", "v": None}):
        must_fail(conn, INSERT, {**VALID, "s": session_id, **change})
    conn.execute(INSERT, {**VALID, "s": session_id, "role": "user", "t": None, "v": None})


@pytest.mark.parametrize("change", [{"t": '{"node": "x"}'}, {"t": '"text"'}, {"t": "1"}, {"v": ""}, {"v": "   "}])
def test_the_trace_must_be_an_array_and_the_version_not_blank(conn, session_id, change):
    must_fail(conn, INSERT, {**VALID, "s": session_id, **change})


# ---------------------------------------------------------------- the in-process lock that replaced the advisory lock

def test_the_keyed_lock_serializes_the_same_key_and_not_different_keys():
    locks = KeyedLocks()
    order = []

    def work(key, name, seconds):
        with locks.hold(key):
            order.append(f"{name}-in")
            time.sleep(seconds)
            order.append(f"{name}-out")

    a = threading.Thread(target=work, args=("k", "a", 0.3))
    b = threading.Thread(target=work, args=("k", "b", 0.0))
    c = threading.Thread(target=work, args=("other", "c", 0.0))
    a.start()
    time.sleep(0.1)
    b.start()
    c.start()
    for thread in (a, b, c):
        thread.join()
    assert order.index("a-out") < order.index("b-in")  # same key: b waited for a
    assert order.index("c-in") < order.index("a-out")  # another key: c did not wait
    assert not locks._locks  # entries are removed once nobody holds or waits


def test_the_keyed_lock_is_released_after_an_error():
    locks = KeyedLocks()
    with pytest.raises(RuntimeError):
        with locks.hold("k"):
            raise RuntimeError("boom")
    with locks.hold("k"):
        pass
