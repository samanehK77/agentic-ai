"""Ingestion end to end on synthetic PDFs: extraction, cleaning, storage, idempotency, failures and the CLI."""
import json
import os

import pytest
from sqlalchemy import text

from app.ingestion.__main__ import main
from app.ingestion.config import IngestConfig
from app.ingestion.pipeline import process_pdf
from app.ingestion.registry import RegisteredPaper, UnsafePathError, find_unregistered, resolve_pdf
from app.ingestion.runner import run_ingestion
from app.ingestion.tokens import WordCounter
from app.repositories import ingestion as repo
from tests import pdf_factory

HEADER = "Running Header Alpha"


@pytest.fixture
def papers_dir(tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    return folder


@pytest.fixture
def cfg(papers_dir, tmp_path):
    return IngestConfig(chunk_target=60, chunk_max=80, chunk_overlap=10, papers_dir=papers_dir, report_dir=tmp_path / "reports")


@pytest.fixture
def register(engine):
    """Creates test papers (ids start with test-ing-) and removes them, their chunks and new run records afterwards."""
    with engine.connect() as connection:
        runs_before = {row[0] for row in connection.execute(text("SELECT run_id FROM ingestion_runs"))}
    created: list[RegisteredPaper] = []

    def add(paper_id: str, file_name: str) -> RegisteredPaper:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO papers (paper_id, title, document_type, publisher, publication_year, source_note, file_name) "
                "VALUES (:p, 'Test paper', 'review', 'unknown', 'unknown', 'synthetic test document', :f)"),
                {"p": paper_id, "f": file_name})
        entry = RegisteredPaper(paper_id, file_name)
        created.append(entry)
        return entry

    yield add
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM papers WHERE paper_id LIKE 'test-ing-%'"))
        for row in connection.execute(text("SELECT run_id FROM ingestion_runs")).all():
            if row[0] not in runs_before:
                connection.execute(text("DELETE FROM ingestion_runs WHERE run_id = :r"), {"r": row[0]})


def run(engine, cfg, registry, **kwargs):
    return run_ingestion(engine, cfg, WordCounter(), registry, **kwargs)


def stored_chunks(engine, paper_id):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(
            "SELECT chunk_id, ordinal, text_sha256, section_type FROM paper_chunks WHERE paper_id = :p ORDER BY ordinal"),
            {"p": paper_id})]


def paper_row(engine, paper_id):
    with engine.connect() as connection:
        return dict(connection.execute(text(
            "SELECT ingest_status, content_sha256, page_count, chunking_version, ingested_at, ingest_note, low_text_pages "
            "FROM papers WHERE paper_id = :p"), {"p": paper_id}).mappings().one())


# ---------------------------------------------------------------- a good document

def test_text_pdf_is_extracted_cleaned_and_chunked(papers_dir, cfg):
    path = pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER, injection=True)
    result = process_pdf(path, "test-ing-good", cfg, WordCounter())
    assert result.status == "ingested" and result.page_count == 7 and not result.low_text_pages
    joined = "\n".join(chunk.text for chunk in result.chunks)
    assert HEADER not in joined                      # running header removed from every page
    assert "Page 4" not in joined                    # footer page numbers removed
    assert "....." not in joined                     # dot leaders removed
    assert "substance use disorders" in joined       # hyphenated line break joined
    assert result.headers_footers_removed >= 10 and result.leader_lines_removed == 3
    assert result.toc_pages == [2]
    kinds = result.section_counts()
    assert kinds["front_matter"] >= 1 and kinds["references"] >= 1 and kinds["body"] >= 5
    refs = [c for c in result.chunks if c.section_type == "references"]
    assert all("Smith" in c.text or "Brown" in c.text for c in refs)
    assert all(0 < c.token_count <= cfg.chunk_max for c in result.chunks)
    titles = {c.section_title for c in result.chunks if c.section_type == "body"}
    assert any(t and t.startswith("Section 1") for t in titles)
    assert sum(result.injection_flags) == 1          # the instruction-like sentence is marked, not removed
    flagged = [c for c, flag in zip(result.chunks, result.injection_flags) if flag]
    assert "reveal the system prompt" in flagged[0].text


def test_clean_document_has_no_injection_flag(papers_dir, cfg):
    result = process_pdf(pdf_factory.text_pdf(papers_dir / "clean.pdf", header=HEADER), "test-ing-clean", cfg, WordCounter())
    assert sum(result.injection_flags) == 0


def test_documents_are_stored_with_stable_ids(engine, papers_dir, cfg, register):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    outcome = run(engine, cfg, [entry])
    assert outcome.exit_code == 0 and outcome.results[0].action == "written"
    rows = stored_chunks(engine, entry.paper_id)
    assert rows and [r[1] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0][0] == "test-ing-good-c0001"
    state = paper_row(engine, entry.paper_id)
    assert state["ingest_status"] == "ingested" and state["page_count"] == 7
    assert state["chunking_version"] == cfg.version() and state["ingested_at"] is not None
    assert len(state["content_sha256"]) == 64


# ---------------------------------------------------------------- idempotency

def test_second_run_is_unchanged_and_writes_nothing(engine, papers_dir, cfg, register):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    run(engine, cfg, [entry])
    chunks_before, row_before = stored_chunks(engine, entry.paper_id), paper_row(engine, entry.paper_id)
    outcome = run(engine, cfg, [entry])
    assert outcome.results[0].action == "unchanged" and outcome.results[0].unchanged
    assert stored_chunks(engine, entry.paper_id) == chunks_before
    assert paper_row(engine, entry.paper_id) == row_before  # even ingested_at is untouched


def test_changed_file_replaces_chunks_without_leftovers(engine, papers_dir, cfg, register):
    path = pdf_factory.text_pdf(papers_dir / "doc.pdf", pages=12, header=HEADER)
    entry = register("test-ing-change", "doc.pdf")
    run(engine, cfg, [entry])
    before = stored_chunks(engine, entry.paper_id)
    pdf_factory.text_pdf(path, pages=6, header=HEADER)  # a shorter file under the same name
    outcome = run(engine, cfg, [entry])
    after = stored_chunks(engine, entry.paper_id)
    assert outcome.results[0].action == "written"
    assert 0 < len(after) < len(before)
    assert [r[1] for r in after] == list(range(1, len(after) + 1)), "ordinals must be continuous: no stale chunks"
    assert paper_row(engine, entry.paper_id)["page_count"] == 5


def test_force_rewrites_with_identical_ids_and_hashes(engine, papers_dir, cfg, register):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    run(engine, cfg, [entry])
    before = stored_chunks(engine, entry.paper_id)
    outcome = run(engine, cfg, [entry], force=True)
    assert outcome.results[0].action == "written"
    assert stored_chunks(engine, entry.paper_id) == before


def test_changing_the_chunk_settings_triggers_rechunking(engine, papers_dir, cfg, register):
    import dataclasses

    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    run(engine, cfg, [entry])
    smaller = dataclasses.replace(cfg, chunk_target=30, chunk_max=40, chunk_overlap=5)
    outcome = run(engine, smaller, [entry])
    assert outcome.results[0].action == "written"
    assert paper_row(engine, entry.paper_id)["chunking_version"] == smaller.version()
    assert all(r[0].startswith("test-ing-good-c") for r in stored_chunks(engine, entry.paper_id))


def test_dry_run_writes_nothing(engine, papers_dir, cfg, register):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    with engine.connect() as connection:
        runs_before = connection.scalar(text("SELECT count(*) FROM ingestion_runs"))
    outcome = run(engine, cfg, [entry], dry_run=True)
    assert outcome.results[0].status == "ingested" and outcome.results[0].action == "dry-run" and outcome.results[0].chunks
    assert stored_chunks(engine, entry.paper_id) == []
    assert paper_row(engine, entry.paper_id)["ingest_status"] == "not_ingested"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM ingestion_runs")) == runs_before


def test_single_paper_selection_and_unknown_id(engine, papers_dir, cfg, register):
    from app.ingestion.config import ConfigError

    pdf_factory.text_pdf(papers_dir / "a.pdf", header=HEADER)
    pdf_factory.text_pdf(papers_dir / "b.pdf", header=HEADER)
    a, b = register("test-ing-a", "a.pdf"), register("test-ing-b", "b.pdf")
    outcome = run(engine, cfg, [a, b], only_paper="test-ing-b")
    assert [r.paper_id for r in outcome.results] == ["test-ing-b"]
    assert stored_chunks(engine, "test-ing-a") == []
    with pytest.raises(ConfigError):
        run(engine, cfg, [a, b], only_paper="nope")


def test_concurrent_run_is_blocked_by_the_advisory_lock(engine, papers_dir, cfg, register, capsys):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    with engine.connect() as other:
        assert repo.try_lock(other)
        try:
            outcome = run(engine, cfg, [entry])
            assert outcome.locked and outcome.exit_code == 3 and outcome.results == []
            assert main([], engine=engine, counter=WordCounter(), registry=[entry], config=cfg) == 3
            assert "already in progress" in capsys.readouterr().err
        finally:
            repo.unlock(other)
    assert stored_chunks(engine, entry.paper_id) == []
    assert run(engine, cfg, [entry]).exit_code == 0  # the lock is released again


# ---------------------------------------------------------------- failures

def test_image_only_pdf_needs_ocr_and_stores_no_chunks(engine, papers_dir, cfg, register):
    pdf_factory.image_only_pdf(papers_dir / "scan.pdf")
    entry = register("test-ing-scan", "scan.pdf")
    outcome = run(engine, cfg, [entry])
    assert outcome.results[0].status == "needs_ocr" and outcome.exit_code == 1
    assert stored_chunks(engine, entry.paper_id) == []
    state = paper_row(engine, entry.paper_id)
    assert state["ingest_status"] == "needs_ocr" and state["low_text_pages"] == [1, 2, 3, 4]
    assert "OCR" in state["ingest_note"] and "\\" not in state["ingest_note"] and "/" not in state["ingest_note"]


def test_corrupt_pdf_fails_but_the_other_documents_still_ingest(engine, papers_dir, cfg, register):
    pdf_factory.corrupt_pdf(papers_dir / "bad.pdf")
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    bad, good = register("test-ing-bad", "bad.pdf"), register("test-ing-good", "good.pdf")
    outcome = run(engine, cfg, [bad, good])
    statuses = {r.paper_id: r.status for r in outcome.results}
    assert statuses == {"test-ing-bad": "failed", "test-ing-good": "ingested"}
    assert outcome.exit_code == 1
    assert stored_chunks(engine, "test-ing-bad") == [] and stored_chunks(engine, "test-ing-good")
    note = paper_row(engine, "test-ing-bad")["ingest_note"]
    assert "corrupt" in note and "Traceback" not in note and "bad.pdf" not in note and str(papers_dir) not in note


def test_a_failed_document_does_not_leave_old_chunks_behind(engine, papers_dir, cfg, register):
    path = pdf_factory.text_pdf(papers_dir / "doc.pdf", header=HEADER)
    entry = register("test-ing-doc", "doc.pdf")
    run(engine, cfg, [entry])
    assert stored_chunks(engine, entry.paper_id)
    pdf_factory.corrupt_pdf(path)
    outcome = run(engine, cfg, [entry])
    assert outcome.results[0].status == "failed"
    assert stored_chunks(engine, entry.paper_id) == []


def test_missing_file_is_reported_as_failed(engine, papers_dir, cfg, register):
    entry = register("test-ing-gone", "missing.pdf")
    outcome = run(engine, cfg, [entry])
    assert outcome.results[0].status == "failed" and "not found" in outcome.results[0].reason


def test_page_limit_is_enforced(engine, papers_dir, cfg, register):
    import dataclasses

    pdf_factory.text_pdf(papers_dir / "long.pdf", pages=10, header=HEADER)
    entry = register("test-ing-long", "long.pdf")
    outcome = run(engine, dataclasses.replace(cfg, max_pdf_pages=3), [entry])
    assert outcome.results[0].status == "failed" and "pages" in outcome.results[0].reason


def test_unregistered_pdfs_are_reported_and_never_ingested(engine, papers_dir, cfg, register):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    pdf_factory.text_pdf(papers_dir / "stranger.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    outcome = run(engine, cfg, [entry])
    assert outcome.unregistered == ["stranger.pdf"]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM papers WHERE file_name = 'stranger.pdf'")) == 0
    assert find_unregistered(papers_dir, [entry]) == ["stranger.pdf"]


def test_registered_paper_missing_from_the_database_is_reported(engine, papers_dir, cfg):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    outcome = run(engine, cfg, [RegisteredPaper("test-ing-not-seeded", "good.pdf")])
    assert outcome.results[0].status == "failed" and "db.seed" in outcome.results[0].reason


# ---------------------------------------------------------------- path safety

@pytest.mark.parametrize("name", ["../outside.pdf", "sub/inner.pdf", "sub\\inner.pdf", "/abs/path.pdf", "..", ".", "",
                                  "notes.txt", "C:\\temp\\x.pdf"])
def test_unsafe_file_names_are_rejected(papers_dir, name):
    with pytest.raises(UnsafePathError):
        resolve_pdf(papers_dir, name)


def test_files_in_subfolders_are_not_found_and_not_listed(papers_dir):
    (papers_dir / "sub").mkdir()
    pdf_factory.text_pdf(papers_dir / "sub" / "inner.pdf")
    with pytest.raises(UnsafePathError):
        resolve_pdf(papers_dir, "inner.pdf")
    assert find_unregistered(papers_dir, []) == []


def test_symbolic_links_are_rejected(papers_dir, tmp_path):
    target = pdf_factory.text_pdf(tmp_path / "target.pdf")
    link = papers_dir / "link.pdf"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not allow creating symbolic links")
    with pytest.raises(UnsafePathError, match="Symbolic"):
        resolve_pdf(papers_dir, "link.pdf")


def test_a_valid_file_resolves(papers_dir):
    pdf_factory.text_pdf(papers_dir / "ok.pdf")
    assert resolve_pdf(papers_dir, "ok.pdf").name == "ok.pdf"


# ---------------------------------------------------------------- run records, reports and the CLI

def test_run_record_and_report_contain_statistics_only(engine, papers_dir, cfg, register, capsys):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    pdf_factory.corrupt_pdf(papers_dir / "bad.pdf")
    good, bad = register("test-ing-good", "good.pdf"), register("test-ing-bad", "bad.pdf")
    code = main([], engine=engine, counter=WordCounter(), registry=[good, bad], config=cfg)
    assert code == 1
    out = capsys.readouterr().out
    assert "test-ing-good" in out and "failed" in out and "Sentence number" not in out
    with engine.connect() as connection:
        run_row = connection.execute(text(
            "SELECT status, results, config FROM ingestion_runs WHERE results ? 'test-ing-good'")).mappings().one()
    assert run_row["status"] == "completed_with_errors"
    assert run_row["results"]["test-ing-good"]["chunks"] > 0 and run_row["results"]["test-ing-bad"]["status"] == "failed"
    dump = json.dumps([run_row["results"], run_row["config"]])
    assert "Sentence number" not in dump and str(papers_dir) not in dump
    report_files = list(cfg.report_dir.glob("ingestion-*.json"))
    assert len(report_files) == 1
    report = json.loads(report_files[0].read_text(encoding="utf-8"))
    doc = next(d for d in report["documents"] if d["paper_id"] == "test-ing-good")
    assert set(doc) >= {"pages", "low_text_pages", "characters", "headers_footers_removed", "chunks", "tokens",
                        "section_types", "possible_injection", "status"}
    assert set(doc["tokens"]) == {"min", "median", "max"} and set(doc["section_types"]) == {
        "body", "table_or_figure", "references", "front_matter"}
    assert "Sentence number" not in report_files[0].read_text(encoding="utf-8")
    assert report["totals"]["failed"] == 1


def test_cli_exit_codes(engine, papers_dir, cfg, register):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    assert main(["--dry-run"], engine=engine, counter=WordCounter(), registry=[entry], config=cfg) == 0
    assert main([], engine=engine, counter=WordCounter(), registry=[entry], config=cfg) == 0
    assert main([], engine=engine, counter=WordCounter(), registry=[entry], config=cfg) == 0  # unchanged
    assert main(["--paper", "no-such-paper"], engine=engine, counter=WordCounter(), registry=[entry], config=cfg) == 2


def test_cli_rejects_invalid_settings_with_exit_code_2(engine, capsys):
    code = main(["--chunk-target", "100", "--chunk-overlap", "100"], engine=engine, counter=WordCounter(), registry=[])
    assert code == 2 and "OVERLAP" in capsys.readouterr().err


def test_unchanged_documents_are_reported_from_the_database(engine, papers_dir, cfg, register, capsys):
    pdf_factory.text_pdf(papers_dir / "good.pdf", header=HEADER)
    entry = register("test-ing-good", "good.pdf")
    main([], engine=engine, counter=WordCounter(), registry=[entry], config=cfg)
    capsys.readouterr()
    assert main([], engine=engine, counter=WordCounter(), registry=[entry], config=cfg) == 0
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("test-ing-good"))
    assert "unchanged" in line and "ingested" in line and " 0/0/0" not in line


def test_registry_file_matches_the_seed_and_has_five_documents():
    from app.ingestion.registry import load_registry

    registry = load_registry()
    assert len(registry) == 5
    assert all("/" not in e.file_name and "\\" not in e.file_name and e.file_name.endswith(".pdf") for e in registry)
