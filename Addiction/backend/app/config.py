"""Application settings, read from environment variables (or the project's .env via db.config)."""
import os
from dataclasses import dataclass

import db.config  # noqa: F401  (importing it loads the project's .env without overriding real environment variables)

# Cookies are host-scoped, so every URL uses the host name localhost (never 127.0.0.1).
DEFAULT_CORS_ORIGINS = "http://localhost:8000"
DEFAULT_FRONTEND_URL = "http://localhost:8000"
MIN_SESSION_SECRET_LENGTH = 32
DEFAULT_IDLE_MINUTES = 30
DEFAULT_MAX_HOURS = 8


class StartupError(RuntimeError):
    """Raised when the app is configured in a way it refuses to run with."""


@dataclass(frozen=True)
class Settings:
    app_env: str
    cors_origins: tuple[str, ...]
    session_secret: str
    frontend_url: str = DEFAULT_FRONTEND_URL
    cookie_secure: bool = False
    admin_emails: frozenset[str] = frozenset()
    session_idle_minutes: int = DEFAULT_IDLE_MINUTES
    session_max_hours: int = DEFAULT_MAX_HOURS
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) < 1:
        raise StartupError(f"{name} must be a positive whole number.")
    return int(raw)


def _cookie_secure() -> bool:
    raw = os.environ.get("COOKIE_SECURE", "").strip().lower()
    if raw in ("", "false"):
        return False
    if raw == "true":
        return True
    raise StartupError("COOKIE_SECURE must be 'true' or 'false'.")


def load_settings() -> Settings:
    app_env = os.environ.get("APP_ENV", "").strip()
    if app_env != "development":
        raise StartupError(
            "Refusing to start: APP_ENV must be 'development'. This API still runs over plain HTTP "
            "for local development only (see docs/API_ACCESS_POLICY.md)."
        )

    raw = os.environ.get("CORS_ORIGINS", "").strip() or DEFAULT_CORS_ORIGINS
    origins = tuple(item.strip() for item in raw.split(",") if item.strip())
    for origin in origins:
        if origin == "*" or not origin.startswith(("http://", "https://")):
            raise StartupError(f"Invalid CORS origin {origin!r}: use full origins such as http://localhost:8000 (no wildcard).")

    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < MIN_SESSION_SECRET_LENGTH:
        raise StartupError(
            f"Refusing to start: SESSION_SECRET must be set and at least {MIN_SESSION_SECRET_LENGTH} characters "
            "(see docs/GOOGLE_AUTH_SETUP.md for how to generate one)."
        )

    frontend_url = os.environ.get("FRONTEND_URL", "").strip() or DEFAULT_FRONTEND_URL
    if not frontend_url.startswith(("http://", "https://")):
        raise StartupError("FRONTEND_URL must be a full URL such as http://localhost:8000.")

    admin_emails = frozenset(
        item.strip().lower() for item in os.environ.get("ADMIN_EMAILS", "").split(",") if item.strip())

    return Settings(
        app_env=app_env,
        cors_origins=origins,
        session_secret=secret,
        frontend_url=frontend_url.rstrip("/"),
        cookie_secure=_cookie_secure(),
        admin_emails=admin_emails,
        session_idle_minutes=_positive_int("SESSION_IDLE_MINUTES", DEFAULT_IDLE_MINUTES),
        session_max_hours=_positive_int("SESSION_MAX_HOURS", DEFAULT_MAX_HOURS),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", "").strip(),
    )
