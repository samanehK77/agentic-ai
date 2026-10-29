"""Migration 0005 (pgvector columns on paper_chunks) and the rules of the new columns."""
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DataError

from tests.conftest import alembic_config, recreate_database
from tests.fake_embedder import FINGERPRINT, add_chunk, add_paper, unit
from tests.test_constraints import must_fail

NEW_COLUMNS = {"embedding", "embedding_fingerprint", "embedded_at", "embedding_status"}


def test_0005_applies_with_existing_chunks_and_downgrades_cleanly():
    url = recreate_database("test_migration5")
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0004")
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO papers (paper_id, title, document_type, publisher, publication_year, source_note) "
                "VALUES ('mig-paper', 'T', 'review', 'unknown', 'unknown', 'n')"))
            connection.execute(text(
                "INSERT INTO paper_chunks (chunk_id, paper_id, ordinal, text, token_count, page_start, page_end, "
                "section_type, text_sha256) VALUES ('mig-paper-c0001', 'mig-paper', 1, 'old chunk', 5, 1, 1, 'body', :h)"),
                {"h": "a" * 64})
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")) == 0

        command.upgrade(config, "0005")
        assert NEW_COLUMNS <= {c["name"] for c in inspect(engine).get_columns("paper_chunks")}
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")) == 1
            row = connection.execute(text(
                "SELECT embedding_status, embedding, embedding_fingerprint, embedded_at FROM paper_chunks")).one()
        assert row == ("pending", None, None, None)  # existing chunks simply wait for the embedding CLI
        with engine.connect() as connection:  # no approximate index was created
            indexes = connection.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename = 'paper_chunks'")).scalars().all()
        assert not any("hnsw" in i.lower() or "ivfflat" in i.lower() for i in indexes)

        command.downgrade(config, "0004")
        assert not NEW_COLUMNS & {c["name"] for c in inspect(engine).get_columns("paper_chunks")}
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")) == 0
            assert connection.scalar(text("SELECT count(*) FROM paper_chunks")) == 1  # the chunk itself is untouched
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.fixture
def paper(conn):
    add_paper(conn, "test-mig5")
    return "test-mig5"


def test_a_valid_embedded_chunk_inserts(conn, paper):
    add_chunk(conn, paper, 1, unit(("alpha", 1)))
    assert conn.scalar(text("SELECT embedding_status FROM paper_chunks WHERE chunk_id = 'test-mig5-c0001'")) == "embedded"


def test_status_defaults_to_pending_for_plain_inserts(conn, paper):
    conn.execute(text(
        "INSERT INTO paper_chunks (chunk_id, paper_id, ordinal, text, token_count, page_start, page_end, section_type, "
        "text_sha256) VALUES ('test-mig5-c0002', :p, 2, 't', 5, 1, 1, 'body', :h)"), {"p": paper, "h": "a" * 64})
    assert conn.scalar(text("SELECT embedding_status FROM paper_chunks WHERE chunk_id = 'test-mig5-c0002'")) == "pending"


UPDATES = [
    "UPDATE paper_chunks SET embedding_status = 'done'",                                   # not an allowed value
    "UPDATE paper_chunks SET embedding_status = 'embedded', embedding = NULL",              # embedded needs a vector
    "UPDATE paper_chunks SET embedding_status = 'embedded', embedding_fingerprint = NULL",  # embedded needs a fingerprint
    "UPDATE paper_chunks SET embedding_status = 'pending'",                                 # a vector with status pending
    "UPDATE paper_chunks SET embedding_status = 'skipped'",                                 # a vector with status skipped
]


@pytest.mark.parametrize("sql", UPDATES)
def test_embedding_rules(conn, paper, sql):
    add_chunk(conn, paper, 1, unit(("alpha", 1)))
    must_fail(conn, text(sql + " WHERE paper_id = :p"), {"p": paper})


def test_a_vector_of_the_wrong_dimension_is_rejected(conn, paper):
    add_chunk(conn, paper, 1, unit(("alpha", 1)))
    with pytest.raises(DataError, match="384"):
        conn.execute(text("UPDATE paper_chunks SET embedding = '[1,2,3]' WHERE paper_id = :p"), {"p": paper})


def test_clearing_an_embedding_for_skipping_is_allowed(conn, paper):
    add_chunk(conn, paper, 1, unit(("alpha", 1)))
    conn.execute(text(
        "UPDATE paper_chunks SET embedding = NULL, embedding_fingerprint = NULL, embedded_at = NULL, "
        "embedding_status = 'skipped' WHERE paper_id = :p"), {"p": paper})
    assert conn.scalar(text("SELECT embedding_status FROM paper_chunks WHERE paper_id = :p"), {"p": paper}) == "skipped"


def test_exact_cosine_search_works_in_sql(conn, paper):
    add_chunk(conn, paper, 1, unit(("alpha", 1)))
    add_chunk(conn, paper, 2, unit(("beta", 1)))
    query = "[" + ",".join(str(x) for x in unit(("alpha", 1))) + "]"
    first = conn.scalar(text(
        "SELECT chunk_id FROM paper_chunks WHERE paper_id = :p AND embedding_status = 'embedded' "
        "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 1"), {"p": paper, "q": query})
    assert first == "test-mig5-c0001"
    assert FINGERPRINT.startswith("fake-model")
