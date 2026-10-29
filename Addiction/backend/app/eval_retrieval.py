"""Smoke-level retrieval evaluation:  python -m app.eval_retrieval [--queries FILE] [--top-k 10] [--check-patterns]

Runs the queries in eval/retrieval_queries.json through the SAME search code as the API and prints Recall@1/3/5, MRR and
the similarity scores of in-domain versus out-of-domain queries.

HONEST LIMITS: this is a small check with keyword-based relevance labels, not a statistically meaningful benchmark. The
numbers say how this retriever behaved on these few queries and nothing more. The labels (expected papers and keyword
patterns) were written from what the documents are about, not from the retriever's output.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.ingestion.config import PROJECT_ROOT
from app.retrieval import service
from app.retrieval.embedder import EmbedderProvider, load_embedder
from db.config import get_engine

DEFAULT_QUERIES = Path(__file__).resolve().parents[1] / "eval" / "retrieval_queries.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "eval_reports"
KS = (1, 3, 5)

DISCLAIMER = ("This is a small smoke-level check with keyword-based labels, not a statistically meaningful benchmark. "
              "Do not read more into these numbers than what they say about these queries.")


class QueryFileError(ValueError):
    pass


def load_queries(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        queries = data["queries"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise QueryFileError(f"Cannot read the query file ({type(error).__name__}).") from None
    seen = set()
    for item in queries:
        for key in ("id", "kind", "query"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise QueryFileError(f"Every query needs a non-empty {key!r}: {item!r:.80}")
        if item["id"] in seen:
            raise QueryFileError(f"Duplicate query id {item['id']!r}.")
        seen.add(item["id"])
        if item["kind"] not in ("in_domain", "out_of_domain"):
            raise QueryFileError(f"Query {item['id']!r}: kind must be 'in_domain' or 'out_of_domain'.")
        if item["kind"] == "in_domain":
            if not item.get("expected_papers") or not item.get("patterns"):
                raise QueryFileError(f"In-domain query {item['id']!r} needs expected_papers and patterns.")
            for pattern in item["patterns"]:
                try:
                    re.compile(pattern)
                except re.error:
                    raise QueryFileError(f"Query {item['id']!r}: invalid pattern {pattern!r}.") from None
    return queries


def is_relevant(hit: dict, query: dict) -> bool:
    return hit["paper_id"] in query["expected_papers"] and any(
        re.search(pattern, hit["text"], re.IGNORECASE) for pattern in query["patterns"])


def first_relevant_rank(hits: list[dict], query: dict) -> int | None:
    for position, hit in enumerate(hits, start=1):
        if is_relevant(hit, query):
            return position
    return None


def summarize(ranks: list[int | None]) -> dict:
    """Recall@k and MRR over in-domain queries; rank None means no relevant chunk in the retrieved list."""
    total = len(ranks)
    if total == 0:
        return {"queries": 0, **{f"recall@{k}": None for k in KS}, "mrr": None}
    return {"queries": total, **{f"recall@{k}": sum(r is not None and r <= k for r in ranks) / total for k in KS},
            "mrr": sum(1 / r for r in ranks if r) / total}


def distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min": None, "median": None, "max": None}
    return {"n": len(values), "min": min(values), "median": median(values), "max": max(values)}


def evaluate(db: Session, provider: EmbedderProvider, queries: list[dict], top_k: int) -> dict:
    per_query = []
    for query in queries:
        outcome = service.search(db, provider, query=query["query"], top_k=top_k, paper_id=None, min_similarity=None)
        hits = outcome["results"]
        entry = {"id": query["id"], "kind": query["kind"], "top1_similarity": hits[0]["similarity"] if hits else None,
                 "hits": [{"chunk_id": h["chunk_id"], "paper_id": h["paper_id"], "similarity": h["similarity"],
                           "relevant": is_relevant(h, query) if query["kind"] == "in_domain" else None} for h in hits]}
        if query["kind"] == "in_domain":
            entry["rank"] = first_relevant_rank(hits, query)
        per_query.append(entry)
    in_domain = [q for q in per_query if q["kind"] == "in_domain"]
    out_domain = [q for q in per_query if q["kind"] == "out_of_domain"]
    return {
        "top_k": top_k, "per_query": per_query, "metrics": summarize([q["rank"] for q in in_domain]),
        "top1_similarity": {"in_domain": distribution([q["top1_similarity"] for q in in_domain if q["top1_similarity"] is not None]),
                            "out_of_domain": distribution([q["top1_similarity"] for q in out_domain if q["top1_similarity"] is not None])},
        "weakest": [q["id"] for q in sorted(in_domain, key=lambda q: (q["rank"] is not None, -(q["rank"] or 0)))
                    if q["rank"] is None or q["rank"] > 5],
    }


def check_patterns(db: Session, queries: list[dict]) -> list[tuple[str, int]]:
    """Label sanity (NOT retrieval): how many embedded chunks of the expected papers contain a pattern at all."""
    rows = []
    for query in queries:
        if query["kind"] != "in_domain":
            continue
        regex = "|".join(f"(?:{p})" for p in query["patterns"])
        count = db.scalar(text(
            "SELECT count(*) FROM paper_chunks WHERE paper_id = ANY(:papers) AND embedding_status = 'embedded' AND text ~* :re"),
            {"papers": query["expected_papers"], "re": regex})
        rows.append((query["id"], count))
    return rows


def _fmt(value, digits=3):
    return "n/a" if value is None else f"{value:.{digits}f}"


def print_report(report: dict, queries: list[dict]) -> None:
    by_id = {q["id"]: q for q in queries}
    print(DISCLAIMER + "\n")
    for entry in report["per_query"]:
        label = "" if entry["kind"] == "out_of_domain" else f"  first relevant rank: {entry['rank'] or 'none in top ' + str(report['top_k'])}"
        print(f"[{entry['kind']}] {entry['id']}{label}")
        print(f"    query: {by_id[entry['id']]['query'][:90]}")
        for position, hit in enumerate(entry["hits"][:3], start=1):
            mark = {True: " REL", False: "", None: ""}[hit["relevant"]]
            print(f"    {position}. {hit['similarity']:.3f}  {hit['chunk_id']}{mark}")
    metrics = report["metrics"]
    print(f"\nIn-domain queries: {metrics['queries']}")
    print("Recall@1 {}  Recall@3 {}  Recall@5 {}  MRR {}".format(
        *(_fmt(metrics[f"recall@{k}"]) for k in KS), _fmt(metrics["mrr"])))
    for name in ("in_domain", "out_of_domain"):
        d = report["top1_similarity"][name]
        print(f"Top-1 cosine similarity, {name.replace('_', '-')} (n={d['n']}): min {_fmt(d['min'])}  "
              f"median {_fmt(d['median'])}  max {_fmt(d['max'])}")
    print("Weakest in-domain queries (no relevant chunk in the top 5): " + (", ".join(report["weakest"]) or "none"))
    print("\n" + DISCLAIMER)


def main(argv: list[str] | None = None, *, engine=None, provider: EmbedderProvider | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval_retrieval", description="Smoke-level retrieval check.")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--check-patterns", action="store_true",
                        help="only report how many chunks of the expected papers contain each pattern (label sanity)")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args(argv)
    if not 1 <= args.top_k <= 20:
        print("--top-k must be between 1 and 20.", file=sys.stderr)
        return 2
    try:
        queries = load_queries(args.queries)
    except QueryFileError as error:
        print(f"Query file problem: {error}", file=sys.stderr)
        return 2
    engine = engine or get_engine()
    if args.check_patterns:
        with Session(engine) as db:
            for query_id, count in check_patterns(db, queries):
                print(f"{query_id:<42} chunks containing a pattern in the expected papers: {count}" + ("   <-- none!" if count == 0 else ""))
        return 0
    provider = provider or EmbedderProvider(load_embedder)
    try:
        with Session(engine) as db:
            report = evaluate(db, provider, queries, args.top_k)
    except ApiError as error:
        print(f"Cannot evaluate: {error.message}", file=sys.stderr)
        return 2
    print_report(report, queries)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = args.report_dir / f"eval-{stamp}.json"
    path.write_text(json.dumps({"note": DISCLAIMER, **report}, indent=2), encoding="utf-8")
    print(f"Statistics-only report: {path.name} in the report folder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
