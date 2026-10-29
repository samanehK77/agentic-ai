"""Migration 0003 on its own: upgrade from 0002 with existing rows, downgrade, and the new constraints."""
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from tests.conftest import alembic_config, recreate_database
from tests.test_constraints import INSERT_PATIENT, PATIENT, must_fail


def test_0003_keeps_existing_chat_sessions_and_downgrades_cleanly():
    url = recreate_database("test_migration3")
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0002")
        with engine.begin() as connection:
            connection.execute(INSERT_PATIENT, PATIENT)
            connection.execute(text("INSERT INTO chat_sessions (patient_id, title) VALUES ('P-099', 'created in batch 3')"))

        command.upgrade(config, "0003")
        tables = set(inspect(engine).get_table_names())
        assert {"users", "auth_sessions"} <= tables
        with engine.connect() as connection:
            row = connection.execute(text("SELECT title, owner_id FROM chat_sessions")).one()
        assert row == ("created in batch 3", None)  # the legacy row is untouched

        command.downgrade(config, "0002")
        tables = set(inspect(engine).get_table_names())
        assert "users" not in tables and "auth_sessions" not in tables
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM chat_sessions")) == 1
        command.upgrade(config, "head")
    finally:
        engine.dispose()


INSERT_USER = text("INSERT INTO users (google_sub, email, email_verified, role) VALUES (:s, 'a@example.test', true, :r) RETURNING id")


def test_google_sub_is_unique(conn):
    conn.execute(INSERT_USER, {"s": "dup", "r": "student"})
    must_fail(conn, INSERT_USER, {"s": "dup", "r": "student"})


@pytest.mark.parametrize("role", ["root", "Admin", ""])
def test_role_is_limited_to_student_and_admin(conn, role):
    must_fail(conn, INSERT_USER, {"s": "role-test", "r": role})


def test_role_defaults_to_student(conn):
    conn.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES ('d', 'd@example.test', true)"))
    assert conn.scalar(text("SELECT role FROM users WHERE google_sub = 'd'")) == "student"


def test_deleting_a_user_removes_their_login_sessions(conn):
    user_id = conn.scalar(INSERT_USER, {"s": "cascade", "r": "student"})
    conn.execute(text("INSERT INTO auth_sessions (user_id, token_hash, csrf_token, expires_at) "
                      "VALUES (:u, 'hash1', 'csrf', now() + interval '1 hour')"), {"u": user_id})
    conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
    assert conn.scalar(text("SELECT count(*) FROM auth_sessions WHERE user_id = :u"), {"u": user_id}) == 0


def test_token_hash_is_unique(conn):
    user_id = conn.scalar(INSERT_USER, {"s": "uniq-hash", "r": "student"})
    insert = text("INSERT INTO auth_sessions (user_id, token_hash, csrf_token, expires_at) "
                  "VALUES (:u, 'same', 'c', now() + interval '1 hour')")
    conn.execute(insert, {"u": user_id})
    must_fail(conn, insert, {"u": user_id})


def test_a_user_who_owns_chat_sessions_cannot_be_deleted(conn):
    conn.execute(INSERT_PATIENT, PATIENT)
    user_id = conn.scalar(INSERT_USER, {"s": "owner", "r": "student"})
    conn.execute(text("INSERT INTO chat_sessions (patient_id, title, owner_id) VALUES ('P-099', 't', :u)"), {"u": user_id})
    must_fail(conn, text("DELETE FROM users WHERE id = :u"), {"u": user_id})
