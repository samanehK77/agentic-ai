"""Migration 0004 on its own, plus the rules of the new tables and columns."""
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from tests.conftest import alembic_config, recreate_database
from tests.test_constraints import must_fail

NEW_PAPER_COLUMNS = {"file_name", "content_sha256", "page_count", "chunking_version", "ingested_at", "doi",
                     "metadata_source", "low_text_pages", "ingest_note"}


def test_0004_applies_to_existing_rows_and_downgrades_cleanly():
    url = recreate_database("test_migration4")
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0003")
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO papers (paper_id, title, document_type, publisher, publication_year, source_note) "
                "VALUES ('old-paper', 'Old', 'guide', 'unknown', 'unknown', 'made in batch 3')"))

        command.upgrade(config, "0004")
        inspector = inspect(engine)
        assert NEW_PAPER_COLUMNS <= {c["name"] for c in inspector.get_columns("papers")}
        assert {"paper_chunks", "ingestion_runs"} <= set(inspector.get_table_names())
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT ingest_status, metadata_source, low_text_pages, file_name FROM papers")).one()
        assert row == ("not_ingested", "project_list", [], None)  # the old row got safe defaults

        with engine.begin() as connection:
            connection.execute(text("UPDATE papers SET ingest_status = 'needs_ocr'"))
        command.downgrade(config, "0003")
        inspector = inspect(engine)
        assert not NEW_PAPER_COLUMNS & {c["name"] for c in inspector.get_columns("papers")}
        assert not {"paper_chunks", "ingestion_runs"} & set(inspector.get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT ingest_status FROM papers")) == "failed"  # needs_ocr did not exist before
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_0004_itself_adds_no_vector_column_or_extension():
    """Batch 05 stops at 0004: embeddings arrive with migration 0005."""
    url = recreate_database("test_migration4b")
    engine = create_engine(url)
    try:
        command.upgrade(alembic_config(url), "0004")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")) == 0
            columns = connection.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'paper_chunks'")).scalars().all()
        assert not any("embed" in c or "vector" in c for c in columns)
    finally:
        engine.dispose()


PAPER = "test-mig-paper"
INSERT_PAPER = text(
    "INSERT INTO papers (paper_id, title, document_type, publisher, publication_year, source_note) "
    "VALUES (:p, 'T', 'review', 'unknown', 'unknown', 'note')")
INSERT_CHUNK = text(
    "INSERT INTO paper_chunks (chunk_id, paper_id, ordinal, text, token_count, page_start, page_end, section_type, text_sha256) "
    "VALUES (:id, :p, :o, :t, :n, :ps, :pe, :k, :h)")
CHUNK = {"id": f"{PAPER}-c0001", "p": PAPER, "o": 1, "t": "text", "n": 5, "ps": 1, "pe": 1, "k": "body", "h": "c" * 64}


@pytest.fixture
def paper(conn):
    conn.execute(INSERT_PAPER, {"p": PAPER})
    return PAPER


def test_a_valid_chunk_inserts(conn, paper):
    conn.execute(INSERT_CHUNK, CHUNK)
    assert conn.scalar(text("SELECT possible_injection FROM paper_chunks WHERE chunk_id = :i"), {"i": CHUNK["id"]}) is False


@pytest.mark.parametrize("change", [
    {"id": "Bad Id-c0001"}, {"id": "other-paper-c0001"}, {"id": f"{PAPER}-c1"}, {"o": 0}, {"t": "   "}, {"n": 0},
    {"ps": 0, "pe": 0}, {"ps": 5, "pe": 4}, {"k": "appendix"}, {"h": "short"},
])
def test_chunk_rules(conn, paper, change):
    must_fail(conn, INSERT_CHUNK, {**CHUNK, **change})


def test_ordinal_is_unique_per_paper(conn, paper):
    conn.execute(INSERT_CHUNK, CHUNK)
    must_fail(conn, INSERT_CHUNK, {**CHUNK, "id": f"{PAPER}-c0002"})  # same ordinal 1 under another id


def test_deleting_a_paper_deletes_its_chunks(conn, paper):
    conn.execute(INSERT_CHUNK, CHUNK)
    conn.execute(text("DELETE FROM papers WHERE paper_id = :p"), {"p": PAPER})
    assert conn.scalar(text("SELECT count(*) FROM paper_chunks WHERE paper_id = :p"), {"p": PAPER}) == 0


def test_chunks_need_an_existing_paper(conn):
    must_fail(conn, INSERT_CHUNK, CHUNK)


@pytest.mark.parametrize("sql", [
    "UPDATE papers SET ingest_status = 'done'",
    "UPDATE papers SET metadata_source = 'guess'",
    "UPDATE papers SET file_name = 'sub/folder.pdf'",
    "UPDATE papers SET file_name = 'sub\\folder.pdf'",
    "UPDATE papers SET file_name = '  '",
    "UPDATE papers SET content_sha256 = 'xyz'",
    "UPDATE papers SET page_count = 0",
])
def test_paper_ingestion_columns_are_constrained(conn, paper, sql):
    must_fail(conn, text(sql + " WHERE paper_id = :p"), {"p": PAPER})


def test_needs_ocr_is_an_allowed_status_and_old_values_still_are(conn, paper):
    for status in ("not_ingested", "ingested", "failed", "needs_ocr"):
        conn.execute(text("UPDATE papers SET ingest_status = :s WHERE paper_id = :p"), {"s": status, "p": PAPER})


@pytest.mark.parametrize("status,ok", [("running", True), ("completed", True), ("completed_with_errors", True),
                                       ("failed", True), ("paused", False)])
def test_ingestion_run_status(conn, status, ok):
    statement = text("INSERT INTO ingestion_runs (status) VALUES (:s)")
    if ok:
        conn.execute(statement, {"s": status})
    else:
        must_fail(conn, statement, {"s": status})
