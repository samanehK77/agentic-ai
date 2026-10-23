"""Database settings. Credentials come only from environment variables (or the project's .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url

# The .env file sits in the project root (Addiction/). Existing environment variables win.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

QUERIES_DIR = Path(__file__).resolve().parent / "queries"
SEED_DIR = Path(__file__).resolve().parent / "seed_data"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Environment variable {name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def get_database_url() -> URL:
    explicit = os.environ.get("DATABASE_URL", "").strip()
    if explicit:
        return make_url(explicit)
    return URL.create(
        "postgresql+psycopg",
        username=_required("POSTGRES_USER"),
        password=_required("POSTGRES_PASSWORD"),
        # 127.0.0.1, not "localhost": on Windows "localhost" can resolve to IPv6 and hang,
        # while docker-compose.yml publishes the port on 127.0.0.1 only.
        host=os.environ.get("POSTGRES_HOST", "").strip() or "127.0.0.1",
        port=int(os.environ.get("POSTGRES_PORT", "").strip() or 5432),
        database=_required("POSTGRES_DB"),
    )


def get_engine(url: URL | None = None) -> Engine:
    return create_engine(url or get_database_url(), future=True)
