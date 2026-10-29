"""Users, login sessions and chat session ownership.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE users (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        google_sub text NOT NULL,
        email text NOT NULL,
        email_verified boolean NOT NULL,
        display_name text,
        role text NOT NULL DEFAULT 'student',
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        last_login_at timestamptz,
        CONSTRAINT pk_users PRIMARY KEY (id),
        CONSTRAINT uq_users_google_sub UNIQUE (google_sub),
        CONSTRAINT ck_users_role_values CHECK (role IN ('student', 'admin')),
        CONSTRAINT ck_users_sub_not_blank CHECK (length(trim(google_sub)) > 0)
    )""")

    op.execute("""
    CREATE TABLE auth_sessions (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL,
        token_hash text NOT NULL,
        csrf_token text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        CONSTRAINT pk_auth_sessions PRIMARY KEY (id),
        CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        CONSTRAINT uq_auth_sessions_token_hash UNIQUE (token_hash)
    )""")
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)")

    # Rows created in Batch 03 keep owner_id NULL; the API never shows them to anyone.
    op.execute("""
    ALTER TABLE chat_sessions
        ADD CONSTRAINT fk_chat_sessions_owner_id_users FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT""")
    op.execute("CREATE INDEX ix_chat_sessions_owner_created ON chat_sessions (owner_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_owner_created")
    op.execute("ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS fk_chat_sessions_owner_id_users")
    op.execute("DROP TABLE IF EXISTS auth_sessions")
    op.execute("DROP TABLE IF EXISTS users")
