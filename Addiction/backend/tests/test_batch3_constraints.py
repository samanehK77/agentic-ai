"""Rules of the Batch 03 tables, checked by trying to break them."""
import pytest
from sqlalchemy import text

from tests.test_constraints import INSERT_PATIENT, PATIENT, must_fail

PAPER = {"i": "p-1", "t": "Title", "d": "guide", "pub": "unknown", "y": "unknown", "n": "note"}
INSERT_PAPER = text("""INSERT INTO papers (paper_id, title, document_type, publisher, publication_year, source_note)
    VALUES (:i, :t, :d, :pub, :y, :n)""")


def test_valid_paper_inserts_with_default_status(conn):
    conn.execute(INSERT_PAPER, PAPER)
    assert conn.scalar(text("SELECT ingest_status FROM papers WHERE paper_id = 'p-1'")) == "not_ingested"


@pytest.mark.parametrize("change", [
    {"i": "Bad Id"}, {"i": "-x"}, {"d": "novel"}, {"y": "20x3"}, {"y": "999"}, {"y": ""},
    {"t": "  "}, {"pub": ""}, {"n": " "},
])
def test_paper_rules(conn, change):
    must_fail(conn, INSERT_PAPER, {**PAPER, **change})


def test_ingest_status_is_limited(conn):
    conn.execute(INSERT_PAPER, PAPER)
    must_fail(conn, text("UPDATE papers SET ingest_status = 'done' WHERE paper_id = 'p-1'"), {})


def new_session(conn, patient="P-099", title="t"):
    conn.execute(INSERT_PATIENT, PATIENT)
    return conn.scalar(text("INSERT INTO chat_sessions (patient_id, title) VALUES (:p, :t) RETURNING session_id"),
                       {"p": patient, "t": title})


def test_session_needs_an_existing_patient_and_a_valid_title(conn):
    new_session(conn)
    insert = text("INSERT INTO chat_sessions (patient_id, title) VALUES (:p, :t)")
    must_fail(conn, insert, {"p": "P-404", "t": "x"})
    must_fail(conn, insert, {"p": "P-099", "t": "   "})
    must_fail(conn, insert, {"p": "P-099", "t": "x" * 121})
    conn.execute(insert, {"p": "P-099", "t": "x" * 120})


def test_owner_id_is_nullable_and_must_reference_a_user(conn):
    conn.execute(INSERT_PATIENT, PATIENT)
    conn.execute(text("INSERT INTO chat_sessions (patient_id, title) VALUES ('P-099', 'legacy row without owner')"))
    fks = conn.scalar(text("SELECT count(*) FROM pg_constraint WHERE contype='f' AND conrelid='chat_sessions'::regclass"))
    assert fks == 2  # the patient link and the owner link (Batch 04)
    must_fail(conn, text("INSERT INTO chat_sessions (patient_id, title, owner_id) VALUES ('P-099', 't', gen_random_uuid())"), {})


def test_a_patient_with_sessions_cannot_be_deleted(conn):
    new_session(conn)
    must_fail(conn, text("DELETE FROM patients WHERE patient_id = 'P-099'"), {})


@pytest.mark.parametrize("values", [
    {"r": "system", "m": None, "c": "x"},
    {"r": "user", "m": "magic", "c": "x"},
    {"r": "user", "m": None, "c": ""},
    {"r": "user", "m": None, "c": "   "},
    {"r": "user", "m": None, "c": "x" * 8001},
])
def test_message_rules(conn, values):
    session_id = new_session(conn)
    must_fail(conn, text("INSERT INTO chat_messages (session_id, role, mode, content) VALUES (:s, :r, :m, :c)"),
              {"s": session_id, **values})


def test_messages_are_removed_with_their_session(conn):
    session_id = new_session(conn)
    conn.execute(text("INSERT INTO chat_messages (session_id, role, mode, content) VALUES (:s, 'user', NULL, 'hi')"),
                 {"s": session_id})
    conn.execute(text("DELETE FROM chat_sessions WHERE session_id = :s"), {"s": session_id})
    assert conn.scalar(text("SELECT count(*) FROM chat_messages")) == 0


def test_chat_message_may_use_every_allowed_mode(conn):
    session_id = new_session(conn)
    for mode in (None, "general_knowledge", "rag", "both"):
        conn.execute(text("INSERT INTO chat_messages (session_id, role, mode, content) VALUES (:s, 'assistant', :m, 'x')"),
                     {"s": session_id, "m": mode})
