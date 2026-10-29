"""Embeds the eligible chunks that are still pending. Idempotent: a second run finds nothing to do."""
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine

from app.embedding.config import EmbedConfig
from app.ingestion.config import ConfigError
from app.repositories import embedding as repo
from app.retrieval.embedder import DIMENSION, EmbedderProvider, RetrievalUnavailable

logger = logging.getLogger("mindevidence.embedding")

EXIT_OK, EXIT_PROBLEM, EXIT_CONFIG, EXIT_LOCKED = 0, 1, 2, 3


class EmbeddingError(Exception):
    """The model returned something unusable. Fails the run immediately (no retry)."""


@dataclass
class EmbedOutcome:
    embedded: int = 0
    failed: int = 0
    stale: int = 0
    pending_before: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    locked: bool = False
    dry_run: bool = False
    error: str | None = None

    @property
    def exit_code(self) -> int:
        if self.locked:
            return EXIT_LOCKED
        return EXIT_PROBLEM if (self.failed or self.stale or self.error) else EXIT_OK


def _retry(operation: Callable[[], object], config: EmbedConfig, sleep: Callable[[float], None]):
    """Transient database errors are retried with exponential backoff; anything else is raised at once."""
    for attempt in range(config.retry_attempts):
        try:
            return operation()
        except (OperationalError, DBAPIError) as error:
            if attempt == config.retry_attempts - 1 or not (isinstance(error, OperationalError) or error.connection_invalidated):
                raise
            delay = config.retry_base_seconds * (2 ** attempt)
            logger.warning("database error (%s), retrying in %.1fs", type(error.orig).__name__, delay)
            sleep(delay)


def _check(vectors: list[list[float]], expected: int) -> None:
    if len(vectors) != expected:
        raise EmbeddingError("The model returned the wrong number of vectors.")
    for vector in vectors:
        if len(vector) != DIMENSION:
            raise EmbeddingError(f"The model returned a vector with {len(vector)} dimensions, expected {DIMENSION}.")
        if abs(math.sqrt(sum(x * x for x in vector)) - 1.0) > 1e-3:
            raise EmbeddingError("The model returned a vector that is not L2-normalized.")


def run_embedding(engine: Engine, config: EmbedConfig, provider: EmbedderProvider, *, paper_id: str | None = None,
                  force: bool = False, dry_run: bool = False, sleep: Callable[[float], None] = time.sleep,
                  progress: Callable[[str], None] = lambda message: None) -> EmbedOutcome:
    started = time.perf_counter()
    outcome = EmbedOutcome(dry_run=dry_run)
    fingerprint = provider.fingerprint
    with Session(engine) as db:
        if paper_id is not None and not repo.paper_exists(db, paper_id):
            raise ConfigError(f"Unknown paper id {paper_id!r}.")
        before = repo.counts(db, config.min_tokens, paper_id, fingerprint)
    outcome.skipped, outcome.stale, outcome.pending_before = before["skipped"], before["stale"], before["pending"]

    if dry_run:
        if force:
            outcome.pending_before += before["embedded"] + before["stale"]
            outcome.stale = 0
        outcome.seconds = time.perf_counter() - started
        return outcome

    lock = engine.connect()
    try:
        if not repo.try_lock(lock):
            outcome.locked = True
            return outcome
        repo.classify(engine, config.min_tokens, paper_id, force)
        with Session(engine) as db:
            now = repo.counts(db, config.min_tokens, paper_id, fingerprint)
        outcome.skipped, outcome.stale, outcome.pending_before = now["skipped"], now["stale"], now["pending"]
        if outcome.stale:
            progress(f"{outcome.stale} embedded chunk(s) carry another model fingerprint; run again with --force to re-embed them.")
        if outcome.pending_before == 0:
            progress("0 pending: nothing to embed.")
        else:
            _embed_pending(engine, config, provider, paper_id, outcome, sleep, progress, fingerprint)
    except RetrievalUnavailable:
        raise
    finally:
        repo.unlock(lock)
        lock.close()
        outcome.seconds = time.perf_counter() - started
    return outcome


def _embed_pending(engine, config, provider, paper_id, outcome, sleep, progress, fingerprint) -> None:
    embedder = provider.get()  # RetrievalUnavailable propagates: the CLI explains how to install the model
    batches = math.ceil(outcome.pending_before / config.batch_size)
    done = 0
    while True:
        with Session(engine) as db:
            items = _retry(lambda: repo.fetch_pending(db, paper_id, config.batch_size), config, sleep)
        if not items:
            break
        try:
            vectors = embedder.embed([text for _, text in items])
            _check(vectors, len(items))
        except EmbeddingError as error:
            outcome.failed += len(items)
            outcome.error = str(error)
            return
        except Exception as error:  # model errors fail fast with a clear message (never the chunk text)
            outcome.failed += len(items)
            outcome.error = f"The embedding model failed ({type(error).__name__})."
            logger.error("embedding failed: %s", type(error).__name__)
            return
        try:
            _retry(lambda: repo.save_batch(engine, fingerprint, [(cid, vec) for (cid, _), vec in zip(items, vectors)]),
                   config, sleep)
        except (OperationalError, DBAPIError) as error:
            outcome.failed += len(items)
            outcome.error = f"The database kept failing ({type(error.orig).__name__})."
            return
        outcome.embedded += len(items)
        done += 1
        progress(f"batch {done}/{batches}: {outcome.embedded} embedded so far")
