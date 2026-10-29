"""Structured answers on chat_messages, with idempotency keys.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-30
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE chat_messages
        ADD COLUMN response jsonb,
        ADD COLUMN generation jsonb,
        ADD COLUMN idempotency_key text,
        ADD COLUMN request_hash text,
        ADD CONSTRAINT ck_chat_messages_idempotency_key_format CHECK (
            idempotency_key IS NULL OR idempotency_key ~ '^[A-Za-z0-9._-]{8,64}$'),
        ADD CONSTRAINT ck_chat_messages_request_hash_format CHECK (
            request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'),
        ADD CONSTRAINT ck_chat_messages_key_and_hash_together CHECK (
            (idempotency_key IS NULL) = (request_hash IS NULL)),
        ADD CONSTRAINT ck_chat_messages_answer_fields_assistant_only CHECK (
            role = 'assistant' OR (response IS NULL AND generation IS NULL AND idempotency_key IS NULL))""")
    op.execute("""
    CREATE UNIQUE INDEX uq_chat_messages_session_idempotency
        ON chat_messages (session_id, idempotency_key) WHERE idempotency_key IS NOT NULL""")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_chat_messages_session_idempotency")
    op.execute("""
    ALTER TABLE chat_messages
        DROP CONSTRAINT IF EXISTS ck_chat_messages_answer_fields_assistant_only,
        DROP CONSTRAINT IF EXISTS ck_chat_messages_key_and_hash_together,
        DROP CONSTRAINT IF EXISTS ck_chat_messages_request_hash_format,
        DROP CONSTRAINT IF EXISTS ck_chat_messages_idempotency_key_format,
        DROP COLUMN IF EXISTS request_hash,
        DROP COLUMN IF EXISTS idempotency_key,
        DROP COLUMN IF EXISTS generation,
        DROP COLUMN IF EXISTS response""")
