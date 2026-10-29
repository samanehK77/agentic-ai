"""Document ingestion: ingestion fields on papers, paper_chunks, ingestion_runs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE papers
        ADD COLUMN file_name text,
        ADD COLUMN content_sha256 text,
        ADD COLUMN page_count integer,
        ADD COLUMN chunking_version text,
        ADD COLUMN ingested_at timestamptz,
        ADD COLUMN doi text,
        ADD COLUMN metadata_source text NOT NULL DEFAULT 'project_list',
        ADD COLUMN low_text_pages integer[] NOT NULL DEFAULT '{}',
        ADD COLUMN ingest_note text,
        ADD CONSTRAINT ck_papers_metadata_source_values CHECK (metadata_source IN ('project_list', 'document_text')),
        ADD CONSTRAINT ck_papers_file_name_bare CHECK (
            file_name IS NULL OR (length(trim(file_name)) > 0 AND file_name !~ '[/\\\\]')),
        ADD CONSTRAINT ck_papers_sha256_format CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
        ADD CONSTRAINT ck_papers_page_count_positive CHECK (page_count IS NULL OR page_count > 0)""")
    op.execute("ALTER TABLE papers DROP CONSTRAINT ck_papers_ingest_status_values")
    op.execute("""
    ALTER TABLE papers ADD CONSTRAINT ck_papers_ingest_status_values
        CHECK (ingest_status IN ('not_ingested', 'ingested', 'failed', 'needs_ocr'))""")

    op.execute("""
    CREATE TABLE paper_chunks (
        chunk_id text NOT NULL,
        paper_id text NOT NULL,
        ordinal integer NOT NULL,
        text text NOT NULL,
        token_count integer NOT NULL,
        page_start integer NOT NULL,
        page_end integer NOT NULL,
        section_title text,
        section_type text NOT NULL,
        text_sha256 text NOT NULL,
        possible_injection boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_paper_chunks PRIMARY KEY (chunk_id),
        CONSTRAINT fk_paper_chunks_paper_id_papers FOREIGN KEY (paper_id) REFERENCES papers (paper_id) ON DELETE CASCADE,
        CONSTRAINT ck_paper_chunks_id_format CHECK (chunk_id ~ '^[a-z0-9][a-z0-9-]*-c[0-9]{4,}$'),
        CONSTRAINT ck_paper_chunks_key_matches_paper CHECK (chunk_id LIKE paper_id || '-c%'),
        CONSTRAINT ck_paper_chunks_ordinal_positive CHECK (ordinal >= 1),
        CONSTRAINT ck_paper_chunks_text_not_blank CHECK (length(trim(text)) > 0),
        CONSTRAINT ck_paper_chunks_token_count_positive CHECK (token_count > 0),
        CONSTRAINT ck_paper_chunks_pages_valid CHECK (page_start >= 1 AND page_end >= page_start),
        CONSTRAINT ck_paper_chunks_section_type_values CHECK (
            section_type IN ('body', 'table_or_figure', 'references', 'front_matter')),
        CONSTRAINT ck_paper_chunks_sha256_format CHECK (text_sha256 ~ '^[0-9a-f]{64}$')
    )""")
    op.execute("CREATE INDEX ix_paper_chunks_paper_id ON paper_chunks (paper_id)")
    op.execute("CREATE UNIQUE INDEX ix_paper_chunks_paper_ordinal ON paper_chunks (paper_id, ordinal)")

    op.execute("""
    CREATE TABLE ingestion_runs (
        run_id uuid NOT NULL DEFAULT gen_random_uuid(),
        started_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz,
        status text NOT NULL DEFAULT 'running',
        config jsonb NOT NULL DEFAULT '{}'::jsonb,
        results jsonb NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT pk_ingestion_runs PRIMARY KEY (run_id),
        CONSTRAINT ck_ingestion_runs_status_values CHECK (
            status IN ('running', 'completed', 'completed_with_errors', 'failed'))
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingestion_runs")
    op.execute("DROP TABLE IF EXISTS paper_chunks")
    op.execute("UPDATE papers SET ingest_status = 'failed' WHERE ingest_status = 'needs_ocr'")
    op.execute("ALTER TABLE papers DROP CONSTRAINT IF EXISTS ck_papers_ingest_status_values")
    op.execute("""
    ALTER TABLE papers ADD CONSTRAINT ck_papers_ingest_status_values
        CHECK (ingest_status IN ('not_ingested', 'ingested', 'failed'))""")
    op.execute("""
    ALTER TABLE papers
        DROP CONSTRAINT IF EXISTS ck_papers_page_count_positive,
        DROP CONSTRAINT IF EXISTS ck_papers_sha256_format,
        DROP CONSTRAINT IF EXISTS ck_papers_file_name_bare,
        DROP CONSTRAINT IF EXISTS ck_papers_metadata_source_values,
        DROP COLUMN IF EXISTS ingest_note,
        DROP COLUMN IF EXISTS low_text_pages,
        DROP COLUMN IF EXISTS metadata_source,
        DROP COLUMN IF EXISTS doi,
        DROP COLUMN IF EXISTS ingested_at,
        DROP COLUMN IF EXISTS chunking_version,
        DROP COLUMN IF EXISTS page_count,
        DROP COLUMN IF EXISTS content_sha256,
        DROP COLUMN IF EXISTS file_name""")
