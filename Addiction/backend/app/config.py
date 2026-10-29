"""Application settings, read from environment variables (or the project's .env via db.config)."""
import os
from dataclasses import dataclass, field

import db.config  # noqa: F401  (importing it loads the project's .env without overriding real environment variables)
from app.llm.config import LLMConfigError, LLMSettings, load_llm_settings

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
    # Default similarity threshold for search and answers. 0.45 sits between the Batch 06 evaluation's in-domain top-1
    # minimum (0.63) and out-of-domain maximum (0.28); that rests on a very small sample (docs/RETRIEVAL.md).
    retrieval_min_similarity: float | None = 0.45
    retrieval_rate_limit_per_minute: int = 30
    retrieval_warmup: bool = False
    answer_rate_limit_per_minute: int = 10
    answer_top_k: int = 5
    graph_total_timeout_seconds: float = 480.0  # the whole answer workflow; must exceed LLM_TIMEOUT_SECONDS
    graph_retrieval_timeout_seconds: float = 60.0
    llm: LLMSettings = field(default_factory=LLMSettings)

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


def _retrieval_threshold() -> float | None:
    raw = os.environ.get("RETRIEVAL_MIN_SIMILARITY", "").strip()
    if not raw:
        return 0.45  # the default (see Settings)
    if raw.lower() == "none":
        return None  # explicitly no threshold
    try:
        value = float(raw)
    except ValueError:
        raise StartupError("RETRIEVAL_MIN_SIMILARITY must be a number between 0 and 1, or 'none'.") from None
    if not 0 <= value <= 1:
        raise StartupError("RETRIEVAL_MIN_SIMILARITY must be a number between 0 and 1.")
    return value


def _seconds(name: str, default: float, low: float = 1, high: float = 3600) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise StartupError(f"{name} must be a number of seconds.") from None
    if not low <= value <= high:
        raise StartupError(f"{name} must be between {low:g} and {high:g} seconds.")
    return value


def _flag(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("", "false"):
        return False
    if raw == "true":
        return True
    raise StartupError(f"{name} must be 'true' or 'false'.")


def _llm_settings() -> LLMSettings:
    try:
        return load_llm_settings()
    except LLMConfigError as error:
        raise StartupError(str(error)) from None


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
        retrieval_min_similarity=_retrieval_threshold(),
        retrieval_rate_limit_per_minute=_positive_int("RETRIEVAL_RATE_LIMIT_PER_MINUTE", 30),
        retrieval_warmup=_flag("RETRIEVAL_WARMUP"),
        answer_rate_limit_per_minute=_positive_int("ANSWER_RATE_LIMIT_PER_MINUTE", 10),
        answer_top_k=min(_positive_int("ANSWER_TOP_K", 5), 20),
        graph_total_timeout_seconds=_seconds("GRAPH_TOTAL_TIMEOUT_SECONDS", 480.0),
        graph_retrieval_timeout_seconds=_seconds("GRAPH_RETRIEVAL_TIMEOUT_SECONDS", 60.0),
        llm=_llm_settings(),
    )
