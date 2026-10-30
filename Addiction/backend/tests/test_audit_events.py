"""Migration 0008 and the table: constraints, the append-only trigger, user deletion, and the metadata rules per event type."""
import json
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.audit.events import EVENT_TYPES, MAX_METADATA_BYTES, MODELS, RejectedMetadata, check_metadata
from app.audit.service import AuditService, Event
from tests.conftest import alembic_config, create_user_session, recreate_database
from tests.test_constraints import must_fail

INSERT = text("""INSERT INTO audit_events (correlation_id, user_id, event_type, outcome, latency_ms, metadata)
                 VALUES (:c, :u, :t, :o, :l, CAST(:m AS jsonb)) RETURNING event_id""")


def row(**changes):
    return {"c": uuid.uuid4(), "u": None, "t": "sign_out", "o": "ok", "l": None, "m": "{}", **changes}


# ---------------------------------------------------------------- migration

def test_0008_creates_the_table_and_downgrades_cleanly():
    url = recreate_database("test_migration8")
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0007")
        assert "audit_events" not in inspect(engine).get_table_names()
        command.upgrade(config, "0008")
        inspector = inspect(engine)
        assert "audit_events" in inspector.get_table_names()
        indexes = {i["name"] for i in inspector.get_indexes("audit_events")}
        assert {"ix_audit_events_user_occurred", "ix_audit_events_session_occurred", "ix_audit_events_correlation_id",
                "ix_audit_events_type_occurred"} <= indexes
        command.downgrade(config, "0007")
        assert "audit_events" not in inspect(engine).get_table_names()
        with engine.connect() as c:  # the trigger function went with it
            assert c.scalar(text("SELECT count(*) FROM pg_proc WHERE proname = 'audit_events_append_only'")) == 0
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_the_event_type_list_in_the_database_matches_the_catalogue(conn):
    definition = conn.scalar(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_audit_events_event_type_values'"))
    for event_type in EVENT_TYPES:
        assert f"'{event_type}'" in definition
    assert definition.count("'") == 2 * len(EVENT_TYPES)
    assert set(MODELS) == set(EVENT_TYPES)


# ---------------------------------------------------------------- constraints

def test_a_valid_event_inserts(conn):
    conn.execute(INSERT, row())
    conn.execute(INSERT, row(t="answer_returned", l=120, m='{"result": "answered"}'))


@pytest.mark.parametrize("change", [
    {"t": "email_sent"}, {"t": "gmail_summary_sent"}, {"o": "maybe"}, {"l": -1}, {"m": "[]"}, {"m": '"text"'},
    {"m": json.dumps({"k": "x" * 5000})},
])
def test_constraints_reject_bad_rows(conn, change):
    must_fail(conn, INSERT, row(**change))


def test_a_request_id_must_be_a_safe_short_string(conn):
    sql = text("INSERT INTO audit_events (correlation_id, request_id, event_type, outcome) VALUES (:c, :r, 'sign_out', 'ok')")
    conn.execute(sql, {"c": uuid.uuid4(), "r": "abc-123"})
    for bad in ("has space", "x" * 65, "semi;colon", "a@b.c"):
        must_fail(conn, sql, {"c": uuid.uuid4(), "r": bad})


# ---------------------------------------------------------------- append-only

def test_update_and_delete_are_rejected(engine):
    with engine.begin() as c:
        event_id = c.scalar(INSERT, row())
    for statement in ("UPDATE audit_events SET outcome = 'error' WHERE event_id = :e",
                      "UPDATE audit_events SET metadata = '{}' WHERE event_id = :e",
                      "UPDATE audit_events SET user_id = gen_random_uuid() WHERE event_id = :e",
                      "DELETE FROM audit_events WHERE event_id = :e"):
        with pytest.raises(Exception, match="append-only"):
            with engine.begin() as c:
                c.execute(text(statement), {"e": event_id})
    with engine.connect() as c:
        assert c.scalar(text("SELECT outcome FROM audit_events WHERE event_id = :e"), {"e": event_id}) == "ok"


def test_deleting_a_user_keeps_the_events_and_clears_only_user_id(engine):
    login = create_user_session(engine)
    corr = uuid.uuid4()
    with engine.begin() as c:
        event_id = c.scalar(INSERT, row(c=corr, u=login["user_id"], t="session_created", m='{"patient_id": "P-001"}'))
    with engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :u"), {"u": login["user_id"]})
    with engine.connect() as c:
        user_id, event_type, meta = c.execute(
            text("SELECT user_id, event_type, metadata FROM audit_events WHERE event_id = :e"), {"e": event_id}).one()
    assert user_id is None and event_type == "session_created" and meta == {"patient_id": "P-001"}


# ---------------------------------------------------------------- metadata rules

def test_every_event_type_has_a_model_that_forbids_extra_keys():
    for event_type, model in MODELS.items():
        assert model.model_config["extra"] == "forbid", event_type


@pytest.mark.parametrize("event_type,metadata", [
    ("sign_out", {"email": "a@b.co"}),
    ("sign_out", {"anything": 1}),
    ("question_submitted", {"question_chars": 5, "mode": "rag", "idempotent": False, "config_fingerprint": "abc", "question": "hi"}),
    ("answer_returned", {"result": "answered", "content": "text"}),
    ("node_executed", {"node": "x", "status": "ok", "reason": "free text"}),
    ("access_denied", {"route": "r", "reason_code": "not_owner", "user_agent": "x"}),
    ("feedback_submitted", {"message_id": str(uuid.uuid4()), "rating": "helpful", "comment": "free text"}),
    ("llm_request", {"status": "ok", "prompt": "text"}),
])
def test_forbidden_keys_are_rejected(event_type, metadata):
    with pytest.raises(RejectedMetadata):
        check_metadata(event_type, metadata)


@pytest.mark.parametrize("value", ["x" * 121, "has a space", "someone@example.com", "10.0.0.1 ", "two\nlines", "semi;colon", "<b>"])
def test_strings_must_be_short_and_free_of_spaces_and_at_signs(value):
    with pytest.raises(RejectedMetadata):
        check_metadata("access_denied", {"route": value, "reason_code": "not_owner"})


def test_values_have_the_right_types_and_ranges():
    for bad in ({"citations": -1}, {"citations": "three"}, {"citations": 10 ** 6}):
        with pytest.raises(RejectedMetadata):
            check_metadata("citation_validated", {"citations": 1, "verified": 1, "unsupported_claims": 0, "sections": 1, **bad})
    with pytest.raises(RejectedMetadata):
        check_metadata("sign_in_succeeded", {"role": "root"})
    with pytest.raises(RejectedMetadata):
        check_metadata("answer_returned", {"result": "maybe"})
    with pytest.raises(RejectedMetadata):
        check_metadata("patient_viewed", {"patient_id": "P-1"})


def test_lists_and_dicts_are_capped_and_flat():
    ok = {"node": "execute_retrieval", "status": "ok", "counts": {"chunks": 3, "top_similarity": 0.8, "flag": True},
          "chunk_ids": ["paper-c0001"]}
    assert check_metadata("node_executed", ok)["counts"]["chunks"] == 3
    with pytest.raises(RejectedMetadata):
        check_metadata("node_executed", {**ok, "chunk_ids": [f"p-c{i:04d}" for i in range(21)]})
    with pytest.raises(RejectedMetadata):
        check_metadata("node_executed", {**ok, "counts": {f"k{i}": i for i in range(21)}})
    with pytest.raises(RejectedMetadata):
        check_metadata("node_executed", {**ok, "counts": {"nested": {"a": 1}}})
    with pytest.raises(RejectedMetadata):
        check_metadata("node_executed", {**ok, "chunk_ids": ["not a chunk id"]})


def test_the_total_size_is_capped():
    assert MAX_METADATA_BYTES == 4096
    ids = [f"{'a' * 90}-c{i:04d}" for i in range(20)]  # 20 maximum-size ids: about 2 KB, still fine
    assert check_metadata("retrieval_executed", {"attempt": 1, "chunks": 20, "chunk_ids": ids})


def test_a_rejected_event_is_not_stored_is_logged_without_its_value_and_is_counted(engine, caplog):
    audit = AuditService(engine)
    secret = "secret-value-from-user@example.com"
    corr = uuid.uuid4()
    with caplog.at_level("WARNING", logger="mindevidence.audit"):
        ok = audit.record_many([Event("sign_out", "ok", {"email": secret})], correlation_id=corr)
    assert ok is True and audit.failures == 1  # the request goes on; the rejection is counted
    assert secret not in caplog.text and "audit_event_rejected" in caplog.text and "email" in caplog.text  # key names only
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM audit_events WHERE correlation_id = :c"), {"c": corr}) == 0
