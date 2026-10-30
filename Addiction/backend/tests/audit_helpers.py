"""Helpers for the audit tests: reading events back by user, session or correlation id."""
from sqlalchemy import text

COLUMNS = "event_id, occurred_at, correlation_id, request_id, user_id, session_id, event_type, outcome, error_code, latency_ms, seq, metadata"


def read(engine, where: str, **params) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(text(f"SELECT {COLUMNS} FROM audit_events WHERE {where} ORDER BY occurred_at, seq, event_id"), params)
        return [dict(r) for r in rows.mappings()]


def of_session(engine, session_id) -> list[dict]:
    return read(engine, "session_id = :s", s=session_id)


def of_user(engine, user_id, event_type: str | None = None) -> list[dict]:
    if event_type:
        return read(engine, "user_id = :u AND event_type = :t", u=user_id, t=event_type)
    return read(engine, "user_id = :u", u=user_id)


def types(events: list[dict]) -> list[str]:
    return [e["event_type"] for e in events]


def last_question(engine, session_id) -> list[dict]:
    """The events of the newest question of a session (one correlation group)."""
    events = of_session(engine, session_id)
    submitted = [e for e in events if e["event_type"] == "question_submitted"]
    assert submitted, "no question_submitted event"
    cid = submitted[-1]["correlation_id"]
    return [e for e in events if e["correlation_id"] == cid]
