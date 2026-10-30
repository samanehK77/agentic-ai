"""Operator diagnostics:  python -m app.diagnostics [--deep] [--json]

Reports booleans, counts and codes only (never URLs, keys, paths or secrets). Without --deep nothing is generated and the
embedding model is not loaded. --deep loads the embedding model and makes ONE tiny model call: use it only after the project
owner approved a real model call. Exit code 1 when any check fails (warnings do not fail)."""
import argparse
import json
import sys

from app.config import StartupError, load_settings
from app.diagnostics.checks import FAIL, Check, Context, overall, run_all
from app.retrieval.embedder import EmbedderProvider, load_embedder
from db.config import get_engine

MARK = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}


def render(checks: list[Check]) -> str:
    lines = []
    for check in checks:
        lines.append(f"[{MARK[check.status]}] {check.name}: {check.message}")
        if check.hint:
            lines.append(f"       how to fix: {check.hint}")
        if check.facts:
            lines.append("       " + ", ".join(f"{k}={v}" for k, v in check.facts.items()))
    lines.append(f"\nOverall: {overall(checks).upper()}. Results describe this machine and the configured model only.")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, context: Context | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.diagnostics", description="Operator diagnostics (no secrets in the output).")
    parser.add_argument("--deep", action="store_true",
                        help="also load the embedding model and make ONE tiny model call (only after the owner approved a real call)")
    parser.add_argument("--json", action="store_true", help="print the checks as JSON")
    args = parser.parse_args(argv)
    if context is None:
        try:
            settings = load_settings()
        except (StartupError, ValueError) as error:
            print(f"Configuration problem: {type(error).__name__}: {error}", file=sys.stderr)
            return 2
        context = Context(get_engine(), settings, EmbedderProvider(load_embedder), deep=args.deep)
    else:
        context.deep = args.deep
    checks = run_all(context)
    if args.json:
        print(json.dumps([c.__dict__ for c in checks], indent=2, default=str))
    else:
        print(render(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
