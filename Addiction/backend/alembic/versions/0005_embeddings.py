"""Embeddings on paper_chunks (pgvector). No ANN index: exact search is enough at this size (see docs/RETRIEVAL.md).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
    ALTER TABLE paper_chunks
        ADD COLUMN embedding vector(384),
        ADD COLUMN embedding_fingerprint text,
        ADD COLUMN embedded_at timestamptz,
        ADD COLUMN embedding_status text NOT NULL DEFAULT 'pending',
        ADD CONSTRAINT ck_paper_chunks_embedding_status_values CHECK (
            embedding_status IN ('pending', 'embedded', 'skipped')),
        ADD CONSTRAINT ck_paper_chunks_embedding_consistent CHECK (
            (embedding IS NOT NULL) = (embedding_status = 'embedded' AND embedding_fingerprint IS NOT NULL))""")
    op.execute("CREATE INDEX ix_paper_chunks_embedding_status ON paper_chunks (embedding_status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_paper_chunks_embedding_status")
    op.execute("""
    ALTER TABLE paper_chunks
        DROP CONSTRAINT IF EXISTS ck_paper_chunks_embedding_consistent,
        DROP CONSTRAINT IF EXISTS ck_paper_chunks_embedding_status_values,
        DROP COLUMN IF EXISTS embedding_status,
        DROP COLUMN IF EXISTS embedded_at,
        DROP COLUMN IF EXISTS embedding_fingerprint,
        DROP COLUMN IF EXISTS embedding""")
    op.execute("DROP EXTENSION IF EXISTS vector")
