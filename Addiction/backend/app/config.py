"""Application settings, read from environment variables (or the project's .env via db.config)."""
import os
from dataclasses import dataclass

import db.config  # noqa: F401  (importing it loads the project's .env without overriding real environment variables)

DEFAULT_CORS_ORIGINS = "http://127.0.0.1:8000,http://localhost:8000"


class StartupError(RuntimeError):
    """Raised when the app is configured in a way it refuses to run with."""


@dataclass(frozen=True)
class Settings:
    app_env: str
    cors_origins: tuple[str, ...]


def load_settings() -> Settings:
    app_env = os.environ.get("APP_ENV", "").strip()
    if app_env != "development":
        raise StartupError(
            "Refusing to start: APP_ENV must be 'development'. This API has no authentication yet "
            "and is for local development only (see docs/API_ACCESS_POLICY.md)."
        )

    raw = os.environ.get("CORS_ORIGINS", "").strip() or DEFAULT_CORS_ORIGINS
    origins = tuple(item.strip() for item in raw.split(",") if item.strip())
    for origin in origins:
        if origin == "*" or not origin.startswith(("http://", "https://")):
            raise StartupError(f"Invalid CORS origin {origin!r}: use full origins such as http://127.0.0.1:8000 (no wildcard).")
    return Settings(app_env=app_env, cors_origins=origins)
