"""Users and login sessions (all SQL for Batch 04 authentication)."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

USER_COLUMNS = "id, email, display_name, role"


def upsert_user(db: Session, sub: str, email: str, email_verified: bool, display_name: str | None,
                role: str, now: datetime) -> dict:
    """Identity key is `sub`: a changed email updates the same row. Role is recomputed at every login."""
    row = db.execute(text(f"""
        INSERT INTO users (google_sub, email, email_verified, display_name, role, created_at, updated_at, last_login_at)
        VALUES (:sub, :email, :verified, :name, :role, :now, :now, :now)
        ON CONFLICT (google_sub) DO UPDATE SET
            email = EXCLUDED.email, email_verified = EXCLUDED.email_verified,
            display_name = EXCLUDED.display_name, role = EXCLUDED.role,
            updated_at = EXCLUDED.updated_at, last_login_at = EXCLUDED.last_login_at
        RETURNING {USER_COLUMNS}"""),
        {"sub": sub, "email": email, "verified": email_verified, "name": display_name, "role": role, "now": now},
    ).mappings().one()
    return dict(row)


def create_auth_session(db: Session, user_id: UUID, token_hash: str, csrf_token: str,
                        now: datetime, expires_at: datetime) -> None:
    db.execute(text("""
        INSERT INTO auth_sessions (user_id, token_hash, csrf_token, created_at, last_seen_at, expires_at)
        VALUES (:user_id, :token_hash, :csrf, :now, :now, :expires_at)"""),
        {"user_id": user_id, "token_hash": token_hash, "csrf": csrf_token, "now": now, "expires_at": expires_at})


def delete_stale_sessions(db: Session, user_id: UUID, now: datetime) -> None:
    """Lazy cleanup: expired sessions, and sessions revoked more than a day ago."""
    db.execute(text("""
        DELETE FROM auth_sessions
        WHERE user_id = :user_id
          AND (expires_at < :now OR (revoked_at IS NOT NULL AND revoked_at < :now - interval '1 day'))"""),
        {"user_id": user_id, "now": now})


def find_session(db: Session, token_hash: str) -> dict | None:
    row = db.execute(text("""
        SELECT s.id AS session_id, s.csrf_token, s.last_seen_at, s.expires_at, s.revoked_at,
               u.id, u.email, u.display_name, u.role
        FROM auth_sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = :token_hash"""), {"token_hash": token_hash}).mappings().first()
    return dict(row) if row else None


def touch_session(db: Session, session_id: UUID, now: datetime) -> None:
    db.execute(text("UPDATE auth_sessions SET last_seen_at = :now WHERE id = :id"), {"now": now, "id": session_id})


def delete_session(db: Session, session_id: UUID) -> None:
    db.execute(text("DELETE FROM auth_sessions WHERE id = :id"), {"id": session_id})


def revoke_session(db: Session, session_id: UUID, now: datetime) -> None:
    db.execute(text("UPDATE auth_sessions SET revoked_at = :now WHERE id = :id AND revoked_at IS NULL"),
               {"now": now, "id": session_id})
