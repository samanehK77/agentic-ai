"""Test fixtures. Tests run against throwaway databases named <POSTGRES_DB>_test*, never the real one."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

# The API refuses to start unless APP_ENV=development, so tests set it before importing the app.
os.environ["APP_ENV"] = "development"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from db.config import get_database_url  # noqa: E402
from db.seed import seed  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["sqlalchemy_url"] = url
    return config


def recreate_database(suffix: str):
    """Drop and create <POSTGRES_DB>_<suffix>; returns its URL."""
    base = get_database_url()
    name = f"{base.database}_{suffix}"
    assert name.endswith(f"_{suffix}") and suffix.startswith("test"), "refusing to touch a non-test database"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return base.set(database=name)


@pytest.fixture(scope="session")
def engine():
    url = recreate_database("test")
    command.upgrade(alembic_config(url), "head")
    eng = create_engine(url)
    seed(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """A connection whose changes are always rolled back."""
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


@pytest.fixture(scope="session")
def client(engine):
    """A test client for the real app wired to the seeded test database."""
    with TestClient(create_app(engine=engine)) as test_client:
        yield test_client


@pytest.fixture
def clean_chat(engine):
    """Removes chat sessions (and, by cascade, messages) created during a test."""
    yield
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM chat_sessions"))
