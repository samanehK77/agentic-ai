"""python -m app.graph --diagram   prints the Mermaid diagram of the COMPILED graph (what docs/orchestration.mmd holds)."""
import argparse
import sys

from app.graph import build_graph


def mermaid() -> str:
    return build_graph().get_graph().draw_mermaid()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.graph", description="Inspect the answer workflow graph.")
    parser.add_argument("--diagram", action="store_true", help="print the Mermaid diagram of the compiled graph")
    args = parser.parse_args(argv)
    if not args.diagram:
        parser.print_help()
        return 2
    sys.stdout.write(mermaid().rstrip("\n") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
