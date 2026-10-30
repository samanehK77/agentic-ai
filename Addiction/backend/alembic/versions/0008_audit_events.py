"""Append-only audit log (Batch 09).

`audit_events` records who did what and how it went, as metadata only: never question, patient or chunk text, prompts,
answers, tokens or e-mail addresses (the allowed keys per event type are enforced by app/audit/events.py).

A trigger rejects every DELETE and every UPDATE except the one change PostgreSQL's own ON DELETE SET NULL makes when a
user is deleted (user_id: value -> NULL, all other columns unchanged), so audit rows survive user deletion.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-01
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

EVENT_TYPES = (
    "sign_in_succeeded", "sign_in_failed", "sign_out", "patient_viewed", "session_created", "question_submitted",
    "node_executed", "retrieval_executed", "llm_request", "citation_validated", "answer_returned", "pipeline_error",
    "access_denied", "feedback_submitted")
OUTCOMES = ("ok", "error", "denied", "skipped")


def _list(values) -> str:
    return ", ".join(repr(v) for v in values)


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE audit_events (
        event_id uuid NOT NULL DEFAULT gen_random_uuid(),
        occurred_at timestamptz NOT NULL DEFAULT now(),
        correlation_id uuid NOT NULL,
        request_id text,
        user_id uuid,
        session_id uuid,
        event_type text NOT NULL,
        outcome text NOT NULL,
        error_code text,
        latency_ms integer,
        seq smallint NOT NULL DEFAULT 0,
        metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        CONSTRAINT pk_audit_events PRIMARY KEY (event_id),
        CONSTRAINT fk_audit_events_user_id_users FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
        CONSTRAINT ck_audit_events_event_type_values CHECK (event_type IN ({_list(EVENT_TYPES)})),
        CONSTRAINT ck_audit_events_outcome_values CHECK (outcome IN ({_list(OUTCOMES)})),
        CONSTRAINT ck_audit_events_latency_not_negative CHECK (latency_ms IS NULL OR latency_ms >= 0),
        CONSTRAINT ck_audit_events_metadata_small_object CHECK (
            jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 4096),
        CONSTRAINT ck_audit_events_request_id_format CHECK (request_id IS NULL OR request_id ~ '^[A-Za-z0-9-]{{1,64}}$')
    )""")
    op.execute("CREATE INDEX ix_audit_events_user_occurred ON audit_events (user_id, occurred_at)")
    op.execute("CREATE INDEX ix_audit_events_session_occurred ON audit_events (session_id, occurred_at)")
    op.execute("CREATE INDEX ix_audit_events_correlation_id ON audit_events (correlation_id)")
    op.execute("CREATE INDEX ix_audit_events_type_occurred ON audit_events (event_type, occurred_at)")
    op.execute("""
    CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'UPDATE'
           AND OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
           AND (NEW.event_id, NEW.occurred_at, NEW.correlation_id, NEW.request_id, NEW.session_id, NEW.event_type,
                NEW.outcome, NEW.error_code, NEW.latency_ms, NEW.seq, NEW.metadata)
               IS NOT DISTINCT FROM
               (OLD.event_id, OLD.occurred_at, OLD.correlation_id, OLD.request_id, OLD.session_id, OLD.event_type,
                OLD.outcome, OLD.error_code, OLD.latency_ms, OLD.seq, OLD.metadata) THEN
            RETURN NEW;  -- the ON DELETE SET NULL of a deleted user
        END IF;
        RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP USING ERRCODE = 'integrity_constraint_violation';
    END $$""")
    op.execute("""
    CREATE TRIGGER trg_audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    op.execute("DROP TABLE IF EXISTS audit_events")
