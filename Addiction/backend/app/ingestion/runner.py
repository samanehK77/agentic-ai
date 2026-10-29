"""Runs the pipeline for the registered documents and writes the results to the database.

Rules: one advisory lock for the whole run; per document, unchanged input (same file hash and chunking_version)
writes nothing; a changed document is replaced in a single transaction.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.ingestion.config import ConfigError, IngestConfig
from app.ingestion.extract import file_sha256
from app.ingestion.pipeline import DocResult, chunk_rows, process_pdf
from app.ingestion.registry import RegisteredPaper, UnsafePathError, find_unregistered, resolve_pdf
from app.ingestion.tokens import TokenCounter
from app.repositories import ingestion as repo

logger = logging.getLogger("mindevidence.ingestion")

EXIT_OK, EXIT_PROBLEM, EXIT_CONFIG, EXIT_LOCKED = 0, 1, 2, 3


@dataclass
class RunOutcome:
    results: list[DocResult] = field(default_factory=list)
    unregistered: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    locked: bool = False
    run_id: str | None = None

    @property
    def exit_code(self) -> int:
        if self.locked:
            return EXIT_LOCKED
        return EXIT_PROBLEM if any(r.status in ("failed", "needs_ocr") for r in self.results) else EXIT_OK


def _unchanged_result(db: Session, paper_id: str, sha: str, summary: dict) -> DocResult:
    result = DocResult(paper_id=paper_id, status=summary["ingest_status"], reason=summary["ingest_note"],
                       content_sha256=sha, page_count=summary["page_count"] or 0,
                       low_text_pages=list(summary["low_text_pages"] or []), unchanged=True, action="unchanged")
    result.stored = summary  # statistics straight from the database
    return result


def _fields(result: DocResult, config: IngestConfig, now: datetime) -> dict:
    return {
        "ingest_status": result.status, "content_sha256": result.content_sha256,
        "page_count": result.page_count or None, "chunking_version": config.version(), "ingested_at": now,
        "low_text_pages": result.low_text_pages, "ingest_note": result.reason,
    }


def run_ingestion(engine: Engine, config: IngestConfig, counter: TokenCounter, registry: list[RegisteredPaper], *,
                  dry_run: bool = False, only_paper: str | None = None, force: bool = False) -> RunOutcome:
    selected = [entry for entry in registry if only_paper in (None, entry.paper_id)]
    if only_paper and not selected:
        raise ConfigError(f"Unknown paper id {only_paper!r}. Registered ids come from db/seed_data/papers.json.")

    outcome = RunOutcome(started_at=datetime.now(timezone.utc), unregistered=find_unregistered(config.papers_dir, registry))
    version = config.version()

    lock_connection = None
    if not dry_run:
        lock_connection = engine.connect()
        if not repo.try_lock(lock_connection):
            lock_connection.close()
            outcome.locked = True
            return outcome
    run_id = None
    try:
        if not dry_run:
            run_id = repo.create_run(engine, config.public_summary())
            outcome.run_id = str(run_id)
        for entry in selected:
            outcome.results.append(_process_entry(engine, config, counter, entry, version, dry_run, force))
        outcome.finished_at = datetime.now(timezone.utc)
        if run_id:
            problems = any(r.status in ("failed", "needs_ocr") for r in outcome.results)
            repo.finish_run(engine, run_id, "completed_with_errors" if problems else "completed", {
                r.paper_id: {"status": r.status, "action": r.action, "pages": r.page_count,
                             "low_text_pages": len(r.low_text_pages), "chunks": len(r.chunks) or
                             getattr(r, "stored", {}).get("chunks", 0)} for r in outcome.results})
    except Exception:
        if run_id:
            repo.finish_run(engine, run_id, "failed", {})
        raise
    finally:
        if lock_connection is not None:
            repo.unlock(lock_connection)
            lock_connection.close()
    return outcome


def _process_entry(engine: Engine, config: IngestConfig, counter: TokenCounter, entry: RegisteredPaper,
                   version: str, dry_run: bool, force: bool) -> DocResult:
    try:
        path: Path = resolve_pdf(config.papers_dir, entry.file_name)
    except UnsafePathError as error:
        result = DocResult(paper_id=entry.paper_id, status="failed", reason=str(error), action="rejected")
        return _store(engine, result, config, dry_run)

    with Session(engine) as db:
        state = repo.get_state(db, entry.paper_id)
        if state is None:
            return DocResult(paper_id=entry.paper_id, status="failed", action="rejected",
                             reason="The paper is not in the database. Run: python -m db.seed")
        try:
            sha = file_sha256(path)
        except OSError:
            sha = None
        if (sha and not force and state["content_sha256"] == sha and state["chunking_version"] == version
                and state["ingest_status"] != "not_ingested"):
            return _unchanged_result(db, entry.paper_id, sha, repo.stored_summary(db, entry.paper_id))

    result = process_pdf(path, entry.paper_id, config, counter)
    return _store(engine, result, config, dry_run)


def _store(engine: Engine, result: DocResult, config: IngestConfig, dry_run: bool) -> DocResult:
    if dry_run:
        result.action = result.action or "dry-run"
        return result
    now = datetime.now(timezone.utc)
    repo.replace_document(engine, result.paper_id, _fields(result, config, now),
                          chunk_rows(result.paper_id, result) if result.status == "ingested" else [])
    result.action = result.action or "written"
    return result
