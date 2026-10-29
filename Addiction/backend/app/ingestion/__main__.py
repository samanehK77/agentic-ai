"""Command line entry point:  python -m app.ingestion [--dry-run] [--paper ID] [--force] ...

Exit codes: 0 ok, 1 a document failed or needs OCR, 2 invalid configuration, 3 another ingestion is running.
"""
import argparse
import sys
from pathlib import Path

from app.ingestion.config import ConfigError, load_config
from app.ingestion.registry import load_registry
from app.ingestion.report import build_report, write_report
from app.ingestion.runner import EXIT_CONFIG, EXIT_LOCKED, run_ingestion
from app.ingestion.tokens import MiniLMTokenCounter, TokenCounter
from db.config import get_engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.ingestion", description="Ingest the registered research PDFs.")
    parser.add_argument("--dry-run", action="store_true", help="read and chunk, but write nothing to the database")
    parser.add_argument("--paper", metavar="PAPER_ID", help="only this registered document")
    parser.add_argument("--force", action="store_true", help="re-ingest even if the file and settings are unchanged")
    parser.add_argument("--chunk-target", type=int, help="target tokens per chunk (default 220)")
    parser.add_argument("--chunk-max", type=int, help="maximum tokens per chunk (default 250)")
    parser.add_argument("--chunk-overlap", type=int, help="overlap tokens between chunks (default 40)")
    parser.add_argument("--allow-over-limit", action="store_true", help="accept a maximum above the model's 256 tokens")
    parser.add_argument("--report-dir", type=Path, help="where the quality report is written")
    parser.add_argument("--show-sample", action="store_true", help="print a very short sample (60 characters) per document")
    return parser


def _print_summary(outcome, report: dict, show_sample: bool) -> None:
    header = f"{'paper_id':<62} {'status':<9} {'action':<9} {'pages':>5} {'low':>4} {'chunks':>6}  tokens min/med/max"
    print(header)
    print("-" * len(header))
    for doc in report["documents"]:
        tokens = doc["tokens"]
        print(f"{doc['paper_id']:<62} {doc['status']:<9} {doc['action']:<9} {doc['pages']:>5} {doc['low_text_pages']:>4} "
              f"{doc['chunks']:>6}  {tokens['min']}/{tokens['median']}/{tokens['max']}")
        if doc["reason"]:
            print(f"    reason: {doc['reason']}")
    for result, doc in zip(outcome.results, report["documents"]):
        if show_sample and result.chunks:
            print(f"    sample {result.paper_id}: {result.chunks[0].text[:60]!r}")
    if outcome.unregistered:
        print(f"{len(outcome.unregistered)} unregistered PDF(s) in the papers folder were NOT ingested: "
              + ", ".join(outcome.unregistered))


def main(argv: list[str] | None = None, *, engine=None, counter: TokenCounter | None = None, registry=None,
         config=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = config or load_config(
            chunk_target=args.chunk_target, chunk_max=args.chunk_max, chunk_overlap=args.chunk_overlap,
            allow_over_limit=True if args.allow_over_limit else None, report_dir=args.report_dir)
        for warning in config.validate():
            print(warning, file=sys.stderr)
        counter = counter or MiniLMTokenCounter(config.tokenizer_path)
        registry = registry if registry is not None else load_registry()
        outcome = run_ingestion(engine or get_engine(), config, counter, registry,
                                dry_run=args.dry_run, only_paper=args.paper, force=args.force)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return EXIT_CONFIG
    if outcome.locked:
        print("Another ingestion run is already in progress; nothing was done.", file=sys.stderr)
        return EXIT_LOCKED
    report = build_report(outcome, config, args.dry_run)
    path = write_report(report, config.report_dir)
    _print_summary(outcome, report, args.show_sample)
    print(f"Quality report (statistics only): {path.name} in the report folder")
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
