"""Papers metadata, chat sessions and chat messages.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE papers (
        paper_id text NOT NULL,
        title text NOT NULL,
        document_type text NOT NULL,
        publisher text NOT NULL,
        publication_year text NOT NULL,
        source_note text NOT NULL,
        ingest_status text NOT NULL DEFAULT 'not_ingested',
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_papers PRIMARY KEY (paper_id),
        CONSTRAINT ck_papers_id_format CHECK (paper_id ~ '^[a-z0-9][a-z0-9-]*$'),
        CONSTRAINT ck_papers_document_type_values CHECK (document_type IN ('guideline', 'guide', 'review', 'unknown')),
        CONSTRAINT ck_papers_ingest_status_values CHECK (ingest_status IN ('not_ingested', 'ingested', 'failed')),
        CONSTRAINT ck_papers_year_format CHECK (publication_year ~ '^(unknown|[0-9]{4})$'),
        CONSTRAINT ck_papers_text_not_blank CHECK (
            length(trim(title)) > 0 AND length(trim(publisher)) > 0 AND length(trim(source_note)) > 0)
    )""")

    op.execute("""
    CREATE TABLE chat_sessions (
        session_id uuid NOT NULL DEFAULT gen_random_uuid(),
        patient_id text NOT NULL,
        title text NOT NULL,
        owner_id uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_chat_sessions PRIMARY KEY (session_id),
        CONSTRAINT fk_chat_sessions_patient_id_patients
            FOREIGN KEY (patient_id) REFERENCES patients (patient_id) ON DELETE RESTRICT,
        CONSTRAINT ck_chat_sessions_title_length CHECK (length(trim(title)) BETWEEN 1 AND 120)
    )""")
    op.execute("CREATE INDEX ix_chat_sessions_patient_created ON chat_sessions (patient_id, created_at)")

    op.execute("""
    CREATE TABLE chat_messages (
        message_id uuid NOT NULL DEFAULT gen_random_uuid(),
        session_id uuid NOT NULL,
        role text NOT NULL,
        mode text,
        content text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_chat_messages PRIMARY KEY (message_id),
        CONSTRAINT fk_chat_messages_session_id_chat_sessions
            FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id) ON DELETE CASCADE,
        CONSTRAINT ck_chat_messages_role_values CHECK (role IN ('user', 'assistant')),
        CONSTRAINT ck_chat_messages_mode_values CHECK (
            mode IS NULL OR mode IN ('general_knowledge', 'rag', 'both')),
        CONSTRAINT ck_chat_messages_content_length CHECK (length(trim(content)) > 0 AND length(content) <= 8000)
    )""")
    op.execute("CREATE INDEX ix_chat_messages_session_created ON chat_messages (session_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_messages")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
    op.execute("DROP TABLE IF EXISTS papers")
