"""Command line entry point:  python -m app.embedding [--dry-run] [--paper ID] [--force] [--batch-size N]

Exit codes: 0 ok, 1 something failed (or stale vectors need --force), 2 invalid configuration or model not installed,
3 another embedding run is in progress.
"""
import argparse
import sys

from app.embedding.config import load_config
from app.embedding.runner import EXIT_CONFIG, EXIT_LOCKED, run_embedding
from app.ingestion.config import ConfigError
from app.retrieval.embedder import EmbedderProvider, RetrievalUnavailable, load_embedder
from db.config import get_engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.embedding", description="Embed the eligible research chunks.")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen, write nothing, do not load the model")
    parser.add_argument("--paper", metavar="PAPER_ID", help="only this document")
    parser.add_argument("--force", action="store_true", help="re-embed every eligible chunk (needed after a model/fingerprint change)")
    parser.add_argument("--batch-size", type=int, help="chunks per batch (default 32, EMBED_BATCH_SIZE)")
    return parser


def main(argv: list[str] | None = None, *, engine=None, provider: EmbedderProvider | None = None, config=None,
         sleep=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = config or load_config(batch_size=args.batch_size)
        config.validate()
        provider = provider or EmbedderProvider(lambda: load_embedder(config.model_dir))
        kwargs = {"sleep": sleep} if sleep else {}
        outcome = run_embedding(engine or get_engine(), config, provider, paper_id=args.paper, force=args.force,
                                dry_run=args.dry_run, progress=print, **kwargs)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except RetrievalUnavailable as error:
        print(f"Cannot embed: {error}", file=sys.stderr)
        return EXIT_CONFIG
    if outcome.locked:
        print("Another embedding run is already in progress; nothing was done.", file=sys.stderr)
        return EXIT_LOCKED
    prefix = "DRY RUN (nothing written). Would embed" if outcome.dry_run else "Embedded"
    print(f"{prefix}: {outcome.pending_before if outcome.dry_run else outcome.embedded}")
    skipped = outcome.skipped
    print(f"Skipped: references={skipped.get('references', 0)}, front_matter={skipped.get('front_matter', 0)}, "
          f"too_short={skipped.get('too_short', 0)}")
    print(f"Failed: {outcome.failed}   Stale (other fingerprint): {outcome.stale}   Seconds: {outcome.seconds:.1f}")
    if outcome.error:
        print(f"Error: {outcome.error}", file=sys.stderr)
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
