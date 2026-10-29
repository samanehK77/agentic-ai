"""The embedding CLI with a fake embedder: eligibility, idempotency, batches, failures, locking, re-ingestion."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.embedding.__main__ import main
from app.embedding.config import EmbedConfig
from app.embedding.runner import run_embedding
from app.ingestion.config import ConfigError
from app.repositories import embedding as repo
from app.repositories import ingestion as ingestion_repo
from app.retrieval.embedder import EmbedderProvider, RetrievalUnavailable
from tests.fake_embedder import FINGERPRINT, FakeEmbedder, add_chunk, add_paper, unit

PAPER, OTHER = "test-emb-a", "test-emb-b"
CONFIG = EmbedConfig(min_tokens=20, batch_size=32, retry_base_seconds=0.0)
SECRET_TEXT = "CONFIDENTIAL-CHUNK-WORDS"


@pytest.fixture
def docs(engine):
    """Paper A: 3 eligible chunks (2 body, 1 table), 1 tiny, 1 references, 1 front matter; all start 'pending'. Paper B: 1 body."""
    with engine.begin() as c:
        add_paper(c, PAPER)
        add_paper(c, OTHER)
        words = {1: "alpha", 2: "beta", 3: "gamma", 4: "delta", 5: "alpha", 6: "beta"}
        spec = [(1, "body", 100), (2, "body", 100), (3, "table_or_figure", 30), (4, "body", 10),
                (5, "references", 100), (6, "front_matter", 100)]
        for ordinal, kind, tokens in spec:
            add_chunk(c, PAPER, ordinal, None, kind=kind, tokens=tokens, status="pending",
                      body=f"{SECRET_TEXT} {words[ordinal]}")
        add_chunk(c, OTHER, 1, None, status="pending", body=f"{SECRET_TEXT} epsilon")
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM papers WHERE paper_id IN (:a, :b)"), {"a": PAPER, "b": OTHER})


def provider_for(embedder=None):
    return EmbedderProvider.fixed(embedder or FakeEmbedder())


def run(engine, embedder=None, config=CONFIG, **kwargs):
    kwargs.setdefault("paper_id", PAPER)
    return run_embedding(engine, config, provider_for(embedder), **kwargs)


def states(engine, paper=PAPER):
    with engine.connect() as c:
        return {row[0]: row[1] for row in c.execute(text(
            "SELECT chunk_id, embedding_status FROM paper_chunks WHERE paper_id = :p"), {"p": paper})}


def row(engine, chunk_id):
    with engine.connect() as c:
        return dict(c.execute(text(
            "SELECT embedding_status AS status, embedding_fingerprint AS fp, embedded_at, "
            "vector_dims(embedding) AS dims, vector_norm(embedding) AS norm FROM paper_chunks WHERE chunk_id = :i"),
            {"i": chunk_id}).mappings().one())


# ---------------------------------------------------------------- eligibility and results

def test_only_eligible_chunks_are_embedded_and_the_rest_skipped(engine, docs):
    outcome = run(engine)
    assert outcome.embedded == 3 and outcome.failed == 0 and outcome.exit_code == 0
    assert outcome.skipped == {"references": 1, "front_matter": 1, "too_short": 1}
    assert states(engine) == {
        f"{PAPER}-c0001": "embedded", f"{PAPER}-c0002": "embedded", f"{PAPER}-c0003": "embedded",
        f"{PAPER}-c0004": "skipped", f"{PAPER}-c0005": "skipped", f"{PAPER}-c0006": "skipped"}


def test_vectors_have_384_dimensions_unit_norm_and_a_fingerprint(engine, docs):
    run(engine)
    stored = row(engine, f"{PAPER}-c0001")
    assert stored["status"] == "embedded" and stored["fp"] == FINGERPRINT and stored["embedded_at"] is not None
    assert stored["dims"] == 384 and stored["norm"] == pytest.approx(1.0, abs=1e-3)
    skipped = row(engine, f"{PAPER}-c0005")
    assert skipped["status"] == "skipped" and skipped["fp"] is None and skipped["dims"] is None


def test_the_embedder_receives_only_eligible_texts_in_chunk_order(engine, docs):
    embedder = FakeEmbedder()
    run(engine, embedder)
    texts = [t for call in embedder.calls for t in call]
    assert len(texts) == 3 and [t.split()[-1] for t in texts] == ["alpha", "beta", "gamma"]


def test_a_second_run_does_nothing(engine, docs):
    run(engine)
    before = {cid: row(engine, cid) for cid in states(engine)}
    embedder = FakeEmbedder()
    messages: list[str] = []
    outcome = run(engine, embedder, progress=messages.append)
    assert outcome.embedded == 0 and outcome.pending_before == 0 and outcome.exit_code == 0
    assert embedder.calls == [] and any("0 pending" in m for m in messages)
    assert {cid: row(engine, cid) for cid in states(engine)} == before  # not even embedded_at changed


def test_force_re_embeds_every_eligible_chunk(engine, docs):
    run(engine)
    first = row(engine, f"{PAPER}-c0001")["embedded_at"]
    embedder = FakeEmbedder()
    outcome = run(engine, embedder, force=True)
    assert outcome.embedded == 3 and sum(len(c) for c in embedder.calls) == 3
    assert row(engine, f"{PAPER}-c0001")["embedded_at"] > first
    assert states(engine)[f"{PAPER}-c0004"] == "skipped"


def test_dry_run_writes_nothing_and_does_not_load_the_model(engine, docs):
    def must_not_load():
        raise AssertionError("the model must not be loaded in a dry run")

    outcome = run_embedding(engine, CONFIG, EmbedderProvider(must_not_load), paper_id=PAPER, dry_run=True)
    assert outcome.dry_run and outcome.pending_before == 3 and outcome.embedded == 0
    assert outcome.skipped == {"references": 1, "front_matter": 1, "too_short": 1}
    assert set(states(engine).values()) == {"pending"}  # not even the skip classification was written


def test_the_paper_option_limits_the_scope(engine, docs):
    run(engine)
    assert set(states(engine, OTHER).values()) == {"pending"}
    outcome = run(engine, paper_id=OTHER)
    assert outcome.embedded == 1 and states(engine, OTHER) == {f"{OTHER}-c0001": "embedded"}


def test_unknown_paper_is_a_configuration_error(engine, docs):
    with pytest.raises(ConfigError):
        run(engine, paper_id="no-such-paper")


def test_changing_the_minimum_tokens_reclassifies_chunks(engine, docs):
    run(engine)
    lowered = EmbedConfig(min_tokens=5, batch_size=32, retry_base_seconds=0.0)
    outcome = run(engine, config=lowered)
    assert outcome.embedded == 1 and states(engine)[f"{PAPER}-c0004"] == "embedded"   # the 10-token chunk is now eligible
    raised = EmbedConfig(min_tokens=50, batch_size=32, retry_base_seconds=0.0)
    outcome = run(engine, config=raised)
    assert outcome.embedded == 0
    assert states(engine)[f"{PAPER}-c0003"] == "skipped" and row(engine, f"{PAPER}-c0003")["dims"] is None  # 30 tokens < 50


def test_stale_fingerprints_need_force(engine, docs):
    run(engine)
    with engine.begin() as c:
        c.execute(text("UPDATE paper_chunks SET embedding_fingerprint = 'old-model@1|dim=384|l2norm' WHERE chunk_id = :i"),
                  {"i": f"{PAPER}-c0001"})
    outcome = run(engine)
    assert outcome.stale == 1 and outcome.embedded == 0 and outcome.exit_code == 1
    assert row(engine, f"{PAPER}-c0001")["fp"] == "old-model@1|dim=384|l2norm"  # untouched without --force
    fixed = run(engine, force=True)
    assert fixed.embedded == 3 and fixed.stale == 0 and fixed.exit_code == 0
    assert row(engine, f"{PAPER}-c0001")["fp"] == FINGERPRINT


# ---------------------------------------------------------------- batches and failures

def test_chunks_are_embedded_in_batches_with_progress(engine, docs):
    small = EmbedConfig(min_tokens=20, batch_size=2, retry_base_seconds=0.0)
    embedder, messages = FakeEmbedder(), []
    outcome = run(engine, embedder, config=small, progress=messages.append)
    assert outcome.embedded == 3 and [len(c) for c in embedder.calls] == [2, 1]
    assert [m for m in messages if m.startswith("batch")] == ["batch 1/2: 2 embedded so far", "batch 2/2: 3 embedded so far"]


def test_a_model_failure_in_a_later_batch_keeps_the_finished_batches(engine, docs):
    class Flaky(FakeEmbedder):
        def embed(self, texts):
            if self.calls:
                raise RuntimeError(f"boom {SECRET_TEXT}")
            return super().embed(texts)

    small = EmbedConfig(min_tokens=20, batch_size=2, retry_base_seconds=0.0)
    outcome = run(engine, Flaky(), config=small)
    assert outcome.embedded == 2 and outcome.failed == 1 and outcome.exit_code == 1
    assert "RuntimeError" in outcome.error and SECRET_TEXT not in outcome.error  # a clear message without chunk text
    assert sorted(v for k, v in states(engine).items() if k.endswith(("c0001", "c0002", "c0003"))) == [
        "embedded", "embedded", "pending"]
    again = run(engine)  # the next run picks up exactly the missing chunk
    assert again.embedded == 1 and again.exit_code == 0


@pytest.mark.parametrize("bad", [[[0.5] * 10], [[0.0] * 384], [[2.0] + [0.0] * 383]])
def test_wrong_dimension_or_norm_fails_the_run_and_stores_nothing(engine, docs, bad):
    class Bad(FakeEmbedder):
        def embed(self, texts):
            return bad * len(texts)

    outcome = run(engine, Bad())
    assert outcome.failed == 3 and outcome.embedded == 0 and outcome.exit_code == 1 and outcome.error
    assert all(v != "embedded" for v in states(engine).values())


def test_transient_database_errors_are_retried_with_backoff(engine, docs, monkeypatch):
    real, attempts, sleeps = repo.save_batch, [], []

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise OperationalError("UPDATE", {}, Exception("server closed the connection"))
        return real(*args, **kwargs)

    monkeypatch.setattr(repo, "save_batch", flaky)
    config = EmbedConfig(min_tokens=20, batch_size=32, retry_base_seconds=1.0)
    outcome = run(engine, config=config, sleep=sleeps.append)
    assert outcome.embedded == 3 and outcome.exit_code == 0 and len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_a_database_that_keeps_failing_is_reported_not_raised(engine, docs, monkeypatch):
    def always(*args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception("down"))

    monkeypatch.setattr(repo, "save_batch", always)
    outcome = run(engine, sleep=lambda seconds: None)
    assert outcome.failed == 3 and outcome.exit_code == 1 and "database" in outcome.error


# ---------------------------------------------------------------- re-ingestion and locking

def test_re_ingested_chunks_come_back_as_pending(engine, docs):
    run(engine)
    assert states(engine)[f"{PAPER}-c0001"] == "embedded"
    new_chunks = [{
        "chunk_id": f"{PAPER}-c000{n}", "paper_id": PAPER, "ordinal": n, "text": f"fresh text alpha {n}", "token_count": 50,
        "page_start": 1, "page_end": 1, "section_title": None, "section_type": "body", "text_sha256": "e" * 64,
        "possible_injection": False} for n in (1, 2)]
    fields = {"ingest_status": "ingested", "content_sha256": "f" * 64, "page_count": 3, "chunking_version": "p1|test",
              "ingested_at": None, "low_text_pages": [], "ingest_note": None}
    ingestion_repo.replace_document(engine, PAPER, fields, new_chunks)
    assert states(engine) == {f"{PAPER}-c0001": "pending", f"{PAPER}-c0002": "pending"}  # the old vectors are gone with the old rows
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM paper_chunks WHERE paper_id = :p AND embedding IS NOT NULL"), {"p": PAPER}) == 0
    assert run(engine).embedded == 2


def test_a_second_run_cannot_overlap_the_first(engine, docs):
    with engine.connect() as other:
        assert repo.try_lock(other)
        try:
            outcome = run(engine)
        finally:
            repo.unlock(other)
    assert outcome.locked and outcome.exit_code == 3 and outcome.embedded == 0
    assert set(states(engine).values()) == {"pending"}
    assert run(engine).embedded == 3  # released again


# ---------------------------------------------------------------- command line

def test_cli_summary_and_exit_codes(engine, docs, capsys):
    code = main(["--paper", PAPER], engine=engine, provider=provider_for(), config=CONFIG)
    out = capsys.readouterr().out
    assert code == 0 and "Embedded: 3" in out and "references=1, front_matter=1, too_short=1" in out
    assert SECRET_TEXT not in out  # no chunk text is printed
    assert main(["--paper", PAPER], engine=engine, provider=provider_for(), config=CONFIG) == 0
    assert "0 pending" in capsys.readouterr().out
    assert main(["--paper", PAPER, "--dry-run"], engine=engine, provider=provider_for(), config=CONFIG) == 0


def test_cli_reports_a_missing_model_clearly(engine, docs, capsys):
    def missing():
        raise RetrievalUnavailable("sentence-transformers (and torch) are not installed. Install the requirements.")

    code = main(["--paper", PAPER], engine=engine, provider=EmbedderProvider(missing), config=CONFIG)
    assert code == 2 and "not installed" in capsys.readouterr().err
    assert set(states(engine).values()) <= {"pending", "skipped"}  # nothing was embedded


def test_cli_rejects_bad_settings_and_unknown_papers(engine, docs, capsys):
    assert main(["--batch-size", "0"], engine=engine, provider=provider_for()) == 2
    assert main(["--paper", "no-such-paper"], engine=engine, provider=provider_for(), config=CONFIG) == 2
    assert "Configuration error" in capsys.readouterr().err


def test_cli_exit_code_is_1_when_something_failed(engine, docs, capsys):
    class Broken(FakeEmbedder):
        def embed(self, texts):
            raise RuntimeError("model crashed")

    code = main(["--paper", PAPER], engine=engine, provider=provider_for(Broken()), config=CONFIG)
    captured = capsys.readouterr()
    assert code == 1 and "Failed: 3" in captured.out and "RuntimeError" in captured.err and SECRET_TEXT not in captured.out + captured.err


def test_the_fingerprint_is_pinned_to_the_batch_5_tokenizer_revision():
    from app.ingestion.config import TOKENIZER_REVISION
    from app.retrieval.embedder import MODEL_NAME, fingerprint

    assert fingerprint() == f"{MODEL_NAME}@{TOKENIZER_REVISION}|dim=384|l2norm"
    assert "latest" not in fingerprint() and len(TOKENIZER_REVISION) == 40
