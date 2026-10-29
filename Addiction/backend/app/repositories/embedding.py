"""SQL used by the embedding CLI: eligibility, pending batches, the one-transaction-per-batch save, and the run lock."""
from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

ADVISORY_LOCK_KEY = 7_305_000_502  # distinct from the ingestion lock

# A chunk is embedded only if it is body or table_or_figure text of at least :min_tokens tokens.
ELIGIBLE = "(section_type IN ('body', 'table_or_figure') AND token_count >= :min_tokens)"
SCOPE = "(CAST(:paper_id AS text) IS NULL OR paper_id = :paper_id)"
SKIP_REASON = ("CASE WHEN section_type = 'references' THEN 'references' WHEN section_type = 'front_matter' "
               "THEN 'front_matter' ELSE 'too_short' END")


def try_lock(connection: Connection) -> bool:
    return bool(connection.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar())


def unlock(connection: Connection) -> None:
    connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})


def paper_exists(db: Session, paper_id: str) -> bool:
    return db.scalar(text("SELECT count(*) FROM papers WHERE paper_id = :p"), {"p": paper_id}) > 0


def classify(engine: Engine, min_tokens: int, paper_id: str | None, force: bool) -> None:
    """Brings embedding_status in line with the eligibility rule (one transaction).
    Ineligible chunks become 'skipped' (vector cleared); skipped chunks that became eligible go back to 'pending';
    with force, every eligible chunk is reset to 'pending' so that it is embedded again."""
    params = {"min_tokens": min_tokens, "paper_id": paper_id}
    reset = "embedding = NULL, embedding_fingerprint = NULL, embedded_at = NULL"
    with engine.begin() as connection:
        connection.execute(text(
            f"UPDATE paper_chunks SET embedding_status = 'skipped', {reset} "
            f"WHERE NOT {ELIGIBLE} AND embedding_status <> 'skipped' AND {SCOPE}"), params)
        connection.execute(text(
            f"UPDATE paper_chunks SET embedding_status = 'pending' "
            f"WHERE {ELIGIBLE} AND embedding_status = 'skipped' AND {SCOPE}"), params)
        if force:
            connection.execute(text(
                f"UPDATE paper_chunks SET embedding_status = 'pending', {reset} "
                f"WHERE {ELIGIBLE} AND embedding_status = 'embedded' AND {SCOPE}"), params)


def counts(db: Session, min_tokens: int, paper_id: str | None, fingerprint: str) -> dict:
    """What the table looks like for the chosen scope, derived from the eligibility rule (nothing is written)."""
    params = {"min_tokens": min_tokens, "paper_id": paper_id, "fp": fingerprint}
    row = db.execute(text(f"""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE {ELIGIBLE} AND embedding_status = 'embedded' AND embedding_fingerprint = :fp) AS embedded,
               count(*) FILTER (WHERE {ELIGIBLE} AND embedding_status = 'embedded'
                                AND embedding_fingerprint IS DISTINCT FROM :fp) AS stale,
               count(*) FILTER (WHERE {ELIGIBLE} AND embedding_status <> 'embedded') AS pending
        FROM paper_chunks WHERE {SCOPE}"""), params).mappings().one()
    reasons = dict(db.execute(text(
        f"SELECT {SKIP_REASON}, count(*) FROM paper_chunks WHERE NOT {ELIGIBLE} AND {SCOPE} GROUP BY 1"), params).all())
    return {**dict(row), "skipped": {k: reasons.get(k, 0) for k in ("references", "front_matter", "too_short")}}


def fetch_pending(db: Session, paper_id: str | None, limit: int) -> list[tuple[str, str]]:
    rows = db.execute(text(
        f"SELECT chunk_id, text FROM paper_chunks WHERE embedding_status = 'pending' AND {SCOPE} "
        "ORDER BY chunk_id LIMIT :k"), {"paper_id": paper_id, "k": limit}).all()
    return [(row[0], row[1]) for row in rows]


_SAVE = text("""
    UPDATE paper_chunks SET embedding = CAST(:v AS vector), embedding_fingerprint = :fp, embedded_at = now(),
                            embedding_status = 'embedded'
    WHERE chunk_id = :id AND embedding_status = 'pending'""").bindparams(bindparam("v", type_=Vector(384)))


def save_batch(engine: Engine, fingerprint: str, items: list[tuple[str, list[float]]]) -> None:
    """One transaction per batch: either every vector of the batch is stored or none."""
    with engine.begin() as connection:
        connection.execute(_SAVE, [{"id": chunk_id, "v": vector, "fp": fingerprint} for chunk_id, vector in items])
