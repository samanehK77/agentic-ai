"""SQL for the append-only audit log. Inserts take the connection of the audit service's own session; reads take the
caller's session. Nothing here updates or deletes (a trigger would refuse)."""
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Session

COLUMNS = ("event_id, occurred_at, correlation_id, request_id, user_id, session_id, event_type, outcome, error_code, "
           "latency_ms, seq, metadata")

INSERT = text("""
    INSERT INTO audit_events (occurred_at, correlation_id, request_id, user_id, session_id, event_type, outcome, error_code,
                              latency_ms, seq, metadata)
    VALUES (COALESCE(:occurred_at, clock_timestamp()), :correlation_id, :request_id, :user_id, :session_id, :event_type,
            :outcome, :error_code, :latency_ms, :seq, CAST(:metadata AS jsonb))""")


def insert_many(db: Session, rows: list[dict]) -> None:
    db.execute(INSERT, [{**row, "metadata": json.dumps(row["metadata"])} for row in rows])


def lock_feedback(db: Session, message_id: str) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"feedback:{message_id}"})


def find_feedback(db: Session, user_id: UUID, session_id: UUID, message_id: str) -> dict | None:
    """The user's first feedback on a message (call it after lock_feedback)."""
    row = db.execute(text("""
        SELECT metadata, correlation_id FROM audit_events
        WHERE event_type = 'feedback_submitted' AND user_id = :u AND session_id = :s AND metadata->>'message_id' = :m
        ORDER BY occurred_at, seq LIMIT 1"""), {"u": user_id, "s": session_id, "m": message_id}).mappings().first()
    return dict(row) if row else None


def correlation_of_answer(db: Session, session_id: UUID, message_id: str) -> UUID | None:
    return db.scalar(text("""
        SELECT correlation_id FROM audit_events
        WHERE event_type = 'answer_returned' AND session_id = :s AND metadata->>'message_id' = :m
        ORDER BY occurred_at LIMIT 1"""), {"s": session_id, "m": message_id})


def chunking_version(db: Session) -> str | None:
    """The chunking version most ingested papers carry; None if nothing is ingested."""
    return db.scalar(text("""
        SELECT chunking_version FROM papers WHERE chunking_version IS NOT NULL
        GROUP BY chunking_version ORDER BY count(*) DESC, chunking_version LIMIT 1"""))


# ---------------------------------------------------------------- timeline (a student's own session)

def timeline_groups(db: Session, user_id: UUID, session_id: UUID, limit: int, offset: int) -> tuple[list[UUID], int]:
    """Correlation ids of the session's events, newest group first, with the total number of groups."""
    total = db.scalar(text("SELECT count(DISTINCT correlation_id) FROM audit_events WHERE session_id = :s AND user_id = :u"),
                      {"s": session_id, "u": user_id})
    ids = db.scalars(text("""
        SELECT correlation_id FROM audit_events WHERE session_id = :s AND user_id = :u
        GROUP BY correlation_id ORDER BY min(occurred_at) DESC, correlation_id LIMIT :n OFFSET :o"""),
        {"s": session_id, "u": user_id, "n": limit, "o": offset}).all()
    return list(ids), total or 0


def events_of_groups(db: Session, user_id: UUID, session_id: UUID, correlation_ids: list[UUID]) -> list[dict]:
    if not correlation_ids:
        return []
    statement = text(f"""
        SELECT {COLUMNS} FROM audit_events
        WHERE session_id = :s AND user_id = :u AND correlation_id = ANY(:ids)
        ORDER BY occurred_at, seq, event_id""").bindparams(bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))))
    return [dict(r) for r in db.execute(statement, {"s": session_id, "u": user_id, "ids": correlation_ids}).mappings().all()]


# ---------------------------------------------------------------- administrator views (metadata only)

def _where(event_type, user_id, outcome, date_from: datetime | None, date_to: datetime | None) -> tuple[str, dict]:
    clauses, params = [], {}
    for name, value in (("event_type", event_type), ("user_id", user_id), ("outcome", outcome)):
        if value is not None:
            clauses.append(f"{name} = :{name}")
            params[name] = value
    if date_from is not None:
        clauses.append("occurred_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        clauses.append("occurred_at < :date_to")
        params["date_to"] = date_to
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_events(db: Session, event_type, user_id, outcome, date_from, date_to, limit: int, offset: int) -> tuple[list[dict], int]:
    where, params = _where(event_type, user_id, outcome, date_from, date_to)
    total = db.scalar(text(f"SELECT count(*) FROM audit_events{where}"), params)
    rows = db.execute(text(f"""
        SELECT {COLUMNS} FROM audit_events{where} ORDER BY occurred_at DESC, seq DESC, event_id LIMIT :n OFFSET :o"""),
        {**params, "n": limit, "o": offset}).mappings().all()
    return [dict(r) for r in rows], total or 0


def summary(db: Session, date_from, date_to) -> dict:
    where, params = _where(None, None, None, date_from, date_to)
    per_day = db.execute(text(f"""
        SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day, event_type, count(*) AS count FROM audit_events{where}
        GROUP BY 1, 2 ORDER BY 1, 2"""), params).mappings().all()
    totals = db.execute(text(f"""
        SELECT count(*) FILTER (WHERE event_type = 'answer_returned' AND outcome = 'ok') AS answered_total,
               count(*) FILTER (WHERE event_type = 'answer_returned' AND outcome = 'ok'
                                AND metadata->>'result' = 'no_evidence') AS no_evidence,
               count(*) FILTER (WHERE event_type = 'pipeline_error') AS errors,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
                   FILTER (WHERE event_type = 'answer_returned' AND outcome = 'ok') AS p50,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                   FILTER (WHERE event_type = 'answer_returned' AND outcome = 'ok') AS p95
        FROM audit_events{where}"""), params).mappings().one()
    return {"per_day": [dict(r) for r in per_day], **dict(totals)}
