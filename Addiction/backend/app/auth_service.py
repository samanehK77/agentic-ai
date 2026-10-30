"""Login and session rules (no HTTP types here except the failure reason codes the router turns into redirects)."""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app import google, security
from app.config import Settings
from app.repositories import users as users_repo

logger = logging.getLogger("mindevidence.auth")

OAUTH_COOKIE = "me_oauth"      # short-lived login state (state, nonce, PKCE verifier), signed
SESSION_COOKIE = "me_session"  # the login session token
OAUTH_LIFETIME_SECONDS = 600
TOUCH_INTERVAL = timedelta(seconds=60)


class LoginFailure(Exception):
    """Carries only a short generic reason code that is safe to put in a redirect."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str
    display_name: str | None
    role: str
    csrf_token: str
    session_id: UUID


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- login

def begin_login(settings: Settings) -> tuple[str, str]:
    """Returns (Google URL, signed one-time cookie value)."""
    state, nonce, verifier = security.new_token(), security.new_token(), security.new_token() + security.new_token()
    cookie = security.sign({"s": state, "n": nonce, "v": verifier}, settings.session_secret, OAUTH_LIFETIME_SECONDS)
    return google.authorization_url(settings, state, nonce, security.pkce_challenge(verifier)), cookie


def _check_state(settings: Settings, cookie: str | None, state: str | None, used: dict[str, float]) -> dict:
    payload = security.unsign(cookie, settings.session_secret) if cookie else None
    if payload is None or not state or not security.safe_equal(state, str(payload.get("s", ""))):
        raise LoginFailure("state_invalid")
    now = time.time()
    for key in [k for k, exp in used.items() if exp < now]:
        del used[key]
    if payload["s"] in used:  # the same signed cookie presented a second time
        raise LoginFailure("state_invalid")
    used[payload["s"]] = float(payload["exp"])
    return payload


def complete_login(db: Session, settings: Settings, cookie: str | None, state: str | None, code: str | None,
                   error: str | None, used_states: dict[str, float]) -> tuple[str, UUID, str]:
    """Returns (raw session token, user id, role). Raises LoginFailure with a generic reason."""
    payload = _check_state(settings, cookie, state, used_states)
    if error:
        raise LoginFailure("access_denied")
    if not code:
        raise LoginFailure("token_invalid")
    try:
        raw_id_token = google.exchange_code(settings, code, payload["v"])
        claims = google.verify_id_token(settings, raw_id_token)
    except google.GoogleError:
        raise LoginFailure("token_invalid") from None

    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not security.safe_equal(nonce, str(payload["n"])):
        raise LoginFailure("token_invalid")
    sub, email = claims.get("sub"), claims.get("email")
    if not isinstance(sub, str) or not sub or not isinstance(email, str) or not email:
        raise LoginFailure("token_invalid")
    if claims.get("email_verified") is not True:
        raise LoginFailure("email_unverified")

    now = utcnow()
    role = "admin" if email.lower() in settings.admin_emails else "student"
    name = claims.get("name") if isinstance(claims.get("name"), str) else None
    user = users_repo.upsert_user(db, sub, email, True, name, role, now)
    users_repo.delete_stale_sessions(db, user["id"], now)

    token, csrf = security.new_token(), security.new_token()  # a brand-new token on every login
    users_repo.create_auth_session(db, user["id"], security.hash_token(token), csrf, now,
                                   now + timedelta(hours=settings.session_max_hours))
    db.commit()
    return token, user["id"], role


# ---------------------------------------------------------------- sessions

def authenticate(db: Session, settings: Settings, raw_token: str | None, now: datetime | None = None) -> AuthUser | None:
    """The user for a valid cookie token, or None. Expired sessions are deleted on the spot."""
    if not raw_token:
        return None
    now = now or utcnow()
    row = users_repo.find_session(db, security.hash_token(raw_token))
    if row is None or row["revoked_at"] is not None:
        return None
    idle = timedelta(minutes=settings.session_idle_minutes)
    if now >= row["expires_at"] or now - row["last_seen_at"] >= idle:
        users_repo.delete_session(db, row["session_id"])
        db.commit()
        return None
    if now - row["last_seen_at"] >= TOUCH_INTERVAL:
        users_repo.touch_session(db, row["session_id"], now)
        db.commit()
    return AuthUser(row["id"], row["email"], row["display_name"], row["role"], row["csrf_token"], row["session_id"])


def logout(db: Session, user: AuthUser) -> None:
    users_repo.revoke_session(db, user.session_id, utcnow())
    db.commit()
