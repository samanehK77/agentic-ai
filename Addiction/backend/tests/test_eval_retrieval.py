"""The evaluation script's logic (ranks, Recall@k, MRR, file checks) with the fake embedder and hand-made chunks."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.eval_retrieval import (
    DEFAULT_QUERIES, QueryFileError, check_patterns, distribution, evaluate, first_relevant_rank, load_queries, main, summarize)
from app.retrieval.embedder import EmbedderProvider
from tests.fake_embedder import FakeEmbedder, add_chunk, add_paper, unit

P1, P2 = "test-evl-a", "test-evl-b"


@pytest.fixture
def corpus(engine):
    with engine.begin() as c:
        add_paper(c, P1)
        add_paper(c, P2)
        add_chunk(c, P1, 1, unit(("alpha", 1)), body="alpha chunk about naltrexone")
        add_chunk(c, P1, 2, unit(("alpha", 1), ("beta", 1)), body="a second chunk about acamprosate")
        add_chunk(c, P2, 1, unit(("beta", 1)), body="beta chunk about naltrexone")
    yield
    with engine.begin() as c:
        c.execute(text("DELETE FROM papers WHERE paper_id IN (:a, :b)"), {"a": P1, "b": P2})


QUERIES = [
    {"id": "q1", "kind": "in_domain", "query": "alpha", "expected_papers": [P1], "patterns": ["naltrexone"]},
    {"id": "q2", "kind": "in_domain", "query": "alpha", "expected_papers": [P1], "patterns": ["acamprosate"]},
    {"id": "q3", "kind": "in_domain", "query": "alpha", "expected_papers": [P2], "patterns": ["nothing matches this"]},
    {"id": "q4", "kind": "out_of_domain", "query": "completely unrelated words"},
]


def test_relevance_needs_the_right_paper_and_a_matching_pattern():
    hit = {"paper_id": P1, "text": "About Naltrexone dosing"}
    assert first_relevant_rank([hit], QUERIES[0]) == 1
    assert first_relevant_rank([{**hit, "paper_id": P2}], QUERIES[0]) is None   # right words, wrong paper
    assert first_relevant_rank([{**hit, "text": "nothing"}], QUERIES[0]) is None   # right paper, no pattern


def test_summary_metrics():
    metrics = summarize([1, 3, None, 6])
    assert metrics["queries"] == 4
    assert metrics["recall@1"] == 0.25 and metrics["recall@3"] == 0.5 and metrics["recall@5"] == 0.5
    assert metrics["mrr"] == pytest.approx((1 + 1 / 3 + 0 + 1 / 6) / 4)
    assert summarize([])["mrr"] is None


def test_distribution():
    assert distribution([0.2, 0.4, 0.9]) == {"n": 3, "min": 0.2, "median": 0.4, "max": 0.9}
    assert distribution([])["median"] is None


def test_evaluate_runs_the_real_search_path(engine, corpus):
    with Session(engine) as db:
        report = evaluate(db, EmbedderProvider.fixed(FakeEmbedder()), QUERIES, top_k=10)
    ranks = {q["id"]: q.get("rank") for q in report["per_query"]}
    assert ranks == {"q1": 1, "q2": 2, "q3": None, "q4": None}   # alpha ranks P1 chunk 1 first, then chunk 2
    assert report["weakest"] == ["q3"]
    assert report["metrics"]["recall@1"] == pytest.approx(1 / 3) and report["metrics"]["recall@3"] == pytest.approx(2 / 3)
    assert report["top1_similarity"]["in_domain"]["max"] == pytest.approx(1.0, abs=1e-3)
    assert report["top1_similarity"]["out_of_domain"]["max"] == pytest.approx(0.0, abs=1e-3)   # unrelated query scores ~0


def test_pattern_check_counts_chunks_without_running_the_retriever(engine, corpus):
    with Session(engine) as db:
        assert dict(check_patterns(db, QUERIES)) == {"q1": 1, "q2": 1, "q3": 0}


def test_the_shipped_query_file_is_valid_and_large_enough():
    queries = load_queries(DEFAULT_QUERIES)
    in_domain = [q for q in queries if q["kind"] == "in_domain"]
    assert len(in_domain) >= 12 and len([q for q in queries if q["kind"] == "out_of_domain"]) >= 4
    covered = {paper for q in in_domain for paper in q["expected_papers"]}
    assert len(covered) == 5  # every document is expected by at least one query


@pytest.mark.parametrize("content", [
    '{"queries": [{"id": "a", "kind": "in_domain", "query": "q"}]}',                                   # no labels
    '{"queries": [{"id": "a", "kind": "odd", "query": "q"}]}',
    '{"queries": [{"id": "a", "kind": "in_domain", "query": "q", "expected_papers": ["p"], "patterns": ["("]}]}',
    '{"queries": [{"id": "a", "kind": "out_of_domain", "query": "q"}, {"id": "a", "kind": "out_of_domain", "query": "r"}]}',
    "not json", "{}",
])
def test_bad_query_files_are_rejected(tmp_path, content):
    path = tmp_path / "queries.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(QueryFileError):
        load_queries(path)


def test_cli_prints_the_disclaimer_and_writes_a_statistics_only_report(engine, corpus, tmp_path, capsys):
    path = tmp_path / "queries.json"
    path.write_text(json.dumps({"queries": QUERIES}), encoding="utf-8")
    code = main(["--queries", str(path), "--report-dir", str(tmp_path / "reports")], engine=engine,
                provider=EmbedderProvider.fixed(FakeEmbedder()))
    out = capsys.readouterr().out
    assert code == 0 and "not a statistically meaningful benchmark" in out and "Recall@1" in out and "MRR" in out
    assert "naltrexone" not in out  # no chunk text is printed
    report_file = next((tmp_path / "reports").glob("eval-*.json"))
    assert "naltrexone" not in report_file.read_text(encoding="utf-8")


def test_cli_reports_a_missing_index_clearly(engine, tmp_path, capsys):
    path = tmp_path / "queries.json"
    path.write_text(json.dumps({"queries": QUERIES[3:]}), encoding="utf-8")
    code = main(["--queries", str(path), "--report-dir", str(tmp_path / "r")], engine=engine,
                provider=EmbedderProvider.fixed(FakeEmbedder()))
    assert code == 2 and "python -m app.embedding" in capsys.readouterr().err
