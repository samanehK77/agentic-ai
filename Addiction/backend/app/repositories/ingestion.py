"""SQL used by the ingestion CLI: the run lock, run records and the per-document replace transaction."""
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

# Arbitrary constant: every ingestion run asks for the same PostgreSQL advisory lock.
ADVISORY_LOCK_KEY = 7_305_000_501


def try_lock(connection: Connection) -> bool:
    """Session-level lock held for as long as this connection stays open."""
    return bool(connection.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar())


def unlock(connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})


def get_state(db: Session, paper_id: str) -> dict | None:
    row = db.execute(text(
        "SELECT paper_id, content_sha256, chunking_version, ingest_status FROM papers WHERE paper_id = :p"),
        {"p": paper_id}).mappings().first()
    return dict(row) if row else None


def create_run(engine: Engine, config: dict) -> UUID:
    with engine.begin() as connection:
        return connection.execute(text(
            "INSERT INTO ingestion_runs (config) VALUES (CAST(:c AS jsonb)) RETURNING run_id"),
            {"c": json.dumps(config)}).scalar_one()


def finish_run(engine: Engine, run_id: UUID, status: str, results: dict) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE ingestion_runs SET finished_at = :now, status = :s, results = CAST(:r AS jsonb) WHERE run_id = :id"),
            {"now": datetime.now(timezone.utc), "s": status, "r": json.dumps(results), "id": run_id})


def replace_document(engine: Engine, paper_id: str, fields: dict, chunks: list[dict]) -> None:
    """One transaction: update the paper row, delete its old chunks, insert the new ones.
    Either everything is replaced or nothing changes (no stale or partial chunks)."""
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE papers SET ingest_status = :ingest_status, content_sha256 = :content_sha256, page_count = :page_count,
                chunking_version = :chunking_version, ingested_at = :ingested_at, low_text_pages = :low_text_pages,
                ingest_note = :ingest_note
            WHERE paper_id = :paper_id"""), {**fields, "paper_id": paper_id})
        connection.execute(text("DELETE FROM paper_chunks WHERE paper_id = :p"), {"p": paper_id})
        if chunks:
            connection.execute(text("""
                INSERT INTO paper_chunks (chunk_id, paper_id, ordinal, text, token_count, page_start, page_end,
                                          section_title, section_type, text_sha256, possible_injection)
                VALUES (:chunk_id, :paper_id, :ordinal, :text, :token_count, :page_start, :page_end,
                        :section_title, :section_type, :text_sha256, :possible_injection)"""), chunks)


def stored_summary(db: Session, paper_id: str) -> dict:
    """Statistics of what is already stored (used to report an 'unchanged' document without re-reading it)."""
    row = db.execute(text("""
        SELECT p.ingest_status, p.page_count, p.low_text_pages, p.ingest_note,
               count(c.chunk_id) AS chunks, min(c.token_count) AS tmin,
               percentile_disc(0.5) WITHIN GROUP (ORDER BY c.token_count) AS tmed, max(c.token_count) AS tmax,
               count(*) FILTER (WHERE c.possible_injection) AS injection
        FROM papers p LEFT JOIN paper_chunks c ON c.paper_id = p.paper_id
        WHERE p.paper_id = :p GROUP BY p.paper_id"""), {"p": paper_id}).mappings().one()
    kinds = dict(db.execute(text(
        "SELECT section_type, count(*) FROM paper_chunks WHERE paper_id = :p GROUP BY section_type"), {"p": paper_id}).all())
    return {**dict(row), "section_types": kinds}
