"""Execution trace of the answer workflow on chat_messages (Batch 08).

The trace holds statistics only (node names, durations, reason codes, counts, chunk ids): never question text,
patient text, chunk text, prompts or answers.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE chat_messages
        ADD COLUMN trace jsonb,
        ADD COLUMN graph_version text,
        ADD CONSTRAINT ck_chat_messages_trace_assistant_only CHECK (
            role = 'assistant' OR (trace IS NULL AND graph_version IS NULL)),
        ADD CONSTRAINT ck_chat_messages_trace_is_array CHECK (
            trace IS NULL OR jsonb_typeof(trace) = 'array'),
        ADD CONSTRAINT ck_chat_messages_graph_version_not_blank CHECK (
            graph_version IS NULL OR length(trim(graph_version)) > 0)""")


def downgrade() -> None:
    op.execute("""
    ALTER TABLE chat_messages
        DROP CONSTRAINT IF EXISTS ck_chat_messages_graph_version_not_blank,
        DROP CONSTRAINT IF EXISTS ck_chat_messages_trace_is_array,
        DROP CONSTRAINT IF EXISTS ck_chat_messages_trace_assistant_only,
        DROP COLUMN IF EXISTS graph_version,
        DROP COLUMN IF EXISTS trace""")
