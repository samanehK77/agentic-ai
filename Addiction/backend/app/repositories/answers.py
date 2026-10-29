"""SQL for chat answers: idempotency lookup and lock, recent turns, the one-transaction insert of a turn, and the
read-time join of cited/shown chunks."""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def find_by_key(db: Session, session_id: UUID, key: str) -> dict | None:
    row = db.execute(text("""
        SELECT message_id, session_id, mode, content, created_at, response, generation, request_hash, trace, graph_version
        FROM chat_messages WHERE session_id = :s AND idempotency_key = :k"""), {"s": session_id, "k": key}).mappings().first()
    return dict(row) if row else None


def recent_turns(db: Session, session_id: UUID, limit: int) -> list[tuple[str, str]]:
    """The last `limit` messages as (role, text), oldest first."""
    rows = db.execute(text("""
        SELECT role, content FROM chat_messages WHERE session_id = :s
        ORDER BY created_at DESC, message_id DESC LIMIT :n"""), {"s": session_id, "n": limit}).all()
    return [(row[0], row[1]) for row in reversed(rows)]


def insert_turn(db: Session, *, session_id: UUID, mode: str, question: str, answer_content: str, response: dict,
                generation: dict, key: str | None, request_hash: str, trace: list | None = None,
                graph_version: str | None = None) -> dict:
    """Inserts the user message and the assistant message (explicit clock_timestamp() so their order is stable even
    inside one transaction). Returns the assistant row."""
    user_id = db.execute(text("""
        INSERT INTO chat_messages (session_id, role, mode, content, created_at)
        VALUES (:s, 'user', :m, :c, clock_timestamp()) RETURNING message_id"""),
        {"s": session_id, "m": mode, "c": question}).scalar_one()
    row = db.execute(text("""
        INSERT INTO chat_messages (session_id, role, mode, content, response, generation, idempotency_key, request_hash, trace,
                                   graph_version, created_at)
        VALUES (:s, 'assistant', :m, :c, CAST(:r AS jsonb), CAST(:g AS jsonb), :k, :h, CAST(:t AS jsonb), :v, clock_timestamp())
        RETURNING message_id, session_id, mode, content, created_at, response, generation, trace, graph_version"""),
        {"s": session_id, "m": mode, "c": answer_content, "r": json.dumps(response), "g": json.dumps(generation),
         "k": key, "h": request_hash if key else None, "t": None if trace is None else json.dumps(trace),
         "v": graph_version}).mappings().one()
    result = dict(row)
    result["user_message_id"] = user_id
    return result


def chunk_rows(db: Session, chunk_ids: list[str]) -> dict[str, dict]:
    """Current state of the given chunks (with the paper title). Missing chunks are simply absent from the result."""
    if not chunk_ids:
        return {}
    rows = db.execute(text("""
        SELECT c.chunk_id, c.paper_id, p.title AS source_title, c.section_title, c.section_type, c.page_start, c.page_end,
               c.text, c.text_sha256, c.possible_injection
        FROM paper_chunks c JOIN papers p ON p.paper_id = c.paper_id WHERE c.chunk_id = ANY(:ids)"""),
        {"ids": chunk_ids}).mappings()
    return {row["chunk_id"]: dict(row) for row in rows}


def get_trace(db: Session, session_id: UUID, message_id: UUID) -> dict | None:
    """The stored execution trace of one assistant message of the session (None if there is no such message)."""
    row = db.execute(text("""
        SELECT message_id, graph_version, trace FROM chat_messages
        WHERE session_id = :s AND message_id = :m AND role = 'assistant'"""), {"s": session_id, "m": message_id}).mappings().first()
    return dict(row) if row else None
