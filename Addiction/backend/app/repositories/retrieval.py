"""Exact cosine search over embedded chunks. Every filter is in the WHERE clause, before ORDER BY ... LIMIT."""
from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

SEARCHABLE_TYPES = ("body", "table_or_figure")

_INDEX_STATE = text("""
    SELECT count(*) FILTER (WHERE embedding_status = 'embedded') AS embedded,
           array_agg(DISTINCT embedding_fingerprint) FILTER (WHERE embedding_status = 'embedded') AS fingerprints
    FROM paper_chunks""")

_SEARCH = text("""
    SELECT c.chunk_id, c.paper_id, p.title, c.section_title, c.section_type, c.page_start, c.page_end, c.text,
           1 - (c.embedding <=> CAST(:q AS vector)) AS similarity, c.possible_injection
    FROM paper_chunks c JOIN papers p ON p.paper_id = c.paper_id
    WHERE c.embedding_status = 'embedded'
      AND c.section_type IN ('body', 'table_or_figure')
      AND (CAST(:paper_id AS text) IS NULL OR c.paper_id = :paper_id)
      AND (CAST(:max_distance AS double precision) IS NULL OR (c.embedding <=> CAST(:q AS vector)) <= :max_distance)
    ORDER BY c.embedding <=> CAST(:q AS vector), c.chunk_id
    LIMIT :k""").bindparams(bindparam("q", type_=Vector(384)))


def index_state(db: Session) -> tuple[int, list[str]]:
    """(number of embedded chunks, the distinct fingerprints they carry)."""
    row = db.execute(_INDEX_STATE).one()
    return row.embedded, list(row.fingerprints or [])


def search(db: Session, vector: list[float], k: int, paper_id: str | None, min_similarity: float | None) -> list[dict]:
    max_distance = None if min_similarity is None else 1.0 - min_similarity
    rows = db.execute(_SEARCH, {"q": vector, "k": k, "paper_id": paper_id, "max_distance": max_distance}).mappings()
    return [dict(row) for row in rows]
