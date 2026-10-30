"""The comparative evaluation: question file, statistics, resumable runs with the scripted model, live refusal, the report."""
import dataclasses
import json

import pytest

from app import eval_report, eval_system as es
from app.config import load_settings
from app.retrieval.embedder import EmbedderProvider
from tests.fake_embedder import FakeEmbedder
from tests.fake_llm import llm_settings

DOC_IDS = {"cochrane-combined-interventions-alcohol-use-disorder-2025", "nida-principles-of-drug-addiction-treatment",
           "psychosocial-interventions-for-alcohol-use-disorder-review", "who-mhgap-guideline-2023", "who-mhgap-intervention-guide-v2"}


# ---------------------------------------------------------------- the question file

def test_the_question_file_covers_every_document_and_every_required_kind():
    questions = es.load_questions()
    assert 12 <= len(questions) <= 15
    kinds = [q["kind"] for q in questions]
    assert kinds.count("patient_history") >= 1 and kinds.count("comparison") >= 1 and kinds.count("out_of_domain") >= 2 and kinds.count("dose_request") >= 1
    covered = {p for q in questions for p in q.get("expected_papers", [])}
    assert covered == DOC_IDS                                              # at least one question per document
    assert len({q["id"] for q in questions}) == len(questions)
    for q in questions:
        if q["kind"] in ("research", "comparison"):
            assert q["expected_papers"] and q["patterns"]


def test_the_expected_papers_are_registered_papers():
    from pathlib import Path

    seed = json.loads((Path(__file__).resolve().parents[1] / "db" / "seed_data" / "papers.json").read_text(encoding="utf-8"))
    ids = {p["paper_id"] for p in (seed["papers"] if isinstance(seed, dict) else seed)}
    assert DOC_IDS == ids


@pytest.mark.parametrize("bad", [{"questions": [{"id": "a", "kind": "nonsense", "question": "q", "patient_id": "P-001"}]},
                                 {"questions": [{"id": "a", "kind": "research", "question": "q", "patient_id": "P-001"}]},
                                 {"questions": [{"id": "a", "kind": "dose_request", "question": "q", "patient_id": "P-001"}] * 2}, {"nope": 1}])
def test_bad_question_files_are_rejected(tmp_path, bad):
    path = tmp_path / "q.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(es.QuestionFileError):
        es.load_questions(path)


# ---------------------------------------------------------------- statistics

def test_percentiles_and_stats_show_n():
    assert es.percentile([], 0.95) is None and es.percentile([5], 0.95) == 5
    assert es.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5) in (5, 6) and es.percentile(list(range(1, 21)), 0.95) == 20
    assert es.stats([1.0, 3.0]) == {"n": 2, "median": 2.0, "p95": 3.0} and es.stats([])["n"] == 0


def run(question_id, kind, mode, **changes):
    base = {"type": "run", "question_id": question_id, "kind": kind, "mode": mode, "wall_s": 10.0, "error_code": None, "http_status": None,
            "outcome": "answered", "classification": "research_question", "llm_called": True, "citations": 2, "verified": 1, "cited_relevant": 1,
            "unsupported_claims": 1, "repair_attempted": False, "tokens_per_s": 5.0}
    return {**base, **changes}


QUESTIONS = {"r1": {"id": "r1", "kind": "research", "expected_classification": "research_question"},
             "o1": {"id": "o1", "kind": "out_of_domain", "expected_classification": "research_question"},
             "d1": {"id": "d1", "kind": "dose_request", "expected_classification": "unsupported_request"}}


def test_failed_runs_stay_in_every_share_that_says_so():
    runs = [run("r1", "research", "rag"), run("r1", "research", "rag", repeat=2, repair_attempted=True),
            run("r1", "research", "rag", repeat=3, error_code="llm_bad_output", http_status=502, outcome="error:llm_bad_output", wall_s=147.0,
                llm_called=False, citations=0, verified=0)]
    s = es.summarize_runs(runs, QUESTIONS)["rag"]
    assert s["runs"] == 3 and s["errors"] == 1 and s["error_codes"] == {"llm_bad_output": 1}
    assert s["model_runs"] == 3                                            # the 502 counts as a model run
    assert s["first_try_valid_json"] == pytest.approx(1 / 3) and s["repair_needed"] == pytest.approx(2 / 3)  # a repair that failed still counts as needed
    assert s["failed_after_repair_or_timeout"] == pytest.approx(1 / 3)
    assert s["quote_verified_share"] == 0.5 and s["wall_s_all_runs"]["n"] == 3 and s["wall_s"]["n"] == 2


def test_per_run_checks_for_no_evidence_safety_and_classification():
    ok = es.question_checks(QUESTIONS["o1"], run("o1", "out_of_domain", "rag", outcome="no_evidence", llm_called=False))
    assert ok["no_evidence_ok"] is True and ok["classification_ok"] is True
    bad = es.question_checks(QUESTIONS["o1"], run("o1", "out_of_domain", "rag", outcome="answered", llm_called=True))
    assert bad["no_evidence_ok"] is False
    assert es.question_checks(QUESTIONS["o1"], run("o1", "out_of_domain", "general_knowledge"))["no_evidence_ok"] is None  # GK is not gated by evidence
    assert es.question_checks(QUESTIONS["d1"], run("d1", "dose_request", "rag", outcome="unsupported", llm_called=False, classification="unsupported_request"))["safety_ok"] is True
    assert es.question_checks(QUESTIONS["d1"], run("d1", "dose_request", "rag", outcome="answered"))["safety_ok"] is False
    wrong = es.question_checks(QUESTIONS["r1"], run("r1", "research", "rag", outcome="no_evidence", llm_called=False))
    assert wrong["wrongly_no_evidence"] is True


# ---------------------------------------------------------------- running (scripted model, test database)

@pytest.fixture
def env(engine, answers_corpus):
    settings = dataclasses.replace(load_settings(), retrieval_min_similarity=0.5)
    return {"engine": engine, "provider": EmbedderProvider.fixed(FakeEmbedder()), "settings": settings}


IDS = ["--ids", "q01-nida-principles", "q09-history-first-treatment", "q12-out-cooking", "q14-dose-request"]


def test_an_automated_run_covers_every_mode_and_keeps_all_runs(env, tmp_path):
    code = es.main(["run", *IDS, "--report-dir", str(tmp_path)], **env)
    assert code == 0
    (state,) = list(tmp_path.glob("system-automated-*.jsonl"))
    records = es.read_state(state)
    assert [r["type"] for r in records[:2]] == ["meta", "retrieval"]
    runs = [r for r in records if r["type"] == "run"]
    assert len(runs) == 4 * 3 and {r["mode"] for r in runs} == set(es.MODES)
    meta = records[0]
    assert meta["run_type"] == "automated" and meta["model"] == "scripted-mock" and meta["config"]["config_fingerprint"] and meta["disclaimer"]
    by = {(r["question_id"], r["mode"]): r for r in runs}
    dose = by[("q14-dose-request", "rag")]
    assert dose["outcome"] == "unsupported" and dose["llm_called"] is False
    assert by[("q12-out-cooking", "rag")]["outcome"] == "no_evidence" and by[("q12-out-cooking", "rag")]["llm_called"] is False
    assert by[("q01-nida-principles", "general_knowledge")]["evidence_chunks"] == 0 and by[("q01-nida-principles", "general_knowledge")]["citations"] == 0
    assert by[("q01-nida-principles", "rag")]["retrieval_needed"] is True            # (the fake embedder finds nothing for this text)
    history = by[("q09-history-first-treatment", "rag")]
    assert history["retrieval_needed"] is False and history["evidence_chunks"] == 0 and history["llm_called"] is True


def test_limit_and_resume_skip_finished_runs_without_repeating_them(env, tmp_path):
    assert es.main(["run", *IDS, "--limit", "5", "--report-dir", str(tmp_path)], **env) == 0
    (state,) = list(tmp_path.glob("system-automated-*.jsonl"))
    assert len([r for r in es.read_state(state) if r["type"] == "run"]) == 5
    assert es.main(["run", *IDS, "--resume", str(state), "--report-dir", str(tmp_path)], **env) == 0
    runs = [r for r in es.read_state(state) if r["type"] == "run"]
    assert len(runs) == 12 and len({(r["question_id"], r["mode"]) for r in runs}) == 12   # finished once each, no duplicates
    assert len([r for r in es.read_state(state) if r["type"] == "meta"]) == 1


def test_repeat_adds_numbered_runs(env, tmp_path):
    es.main(["run", "--ids", "q01-nida-principles", "--modes", "rag", "--repeat", "2", "--report-dir", str(tmp_path)], **env)
    (state,) = list(tmp_path.glob("system-automated-*.jsonl"))
    assert sorted(r["repeat"] for r in es.read_state(state) if r["type"] == "run") == [1, 2]


def test_live_refuses_a_model_that_is_not_on_this_machine(env, tmp_path, capsys):
    remote = dataclasses.replace(env["settings"], llm=llm_settings(base_url="https://api.deepseek.com", api_key="k"))
    code = es.main(["run", "--live", "--limit", "1", "--report-dir", str(tmp_path)], engine=env["engine"], provider=env["provider"], settings=remote)
    assert code == 2 and "not on this machine" in capsys.readouterr().err
    assert list(tmp_path.glob("*.jsonl")) == []                            # nothing was sent, nothing was written


def test_the_timeout_must_exceed_the_model_timeout(env, tmp_path, capsys):
    assert es.main(["run", "--timeout", "5", "--report-dir", str(tmp_path)], **env) == 2


def test_a_bad_question_file_exits_with_a_message(env, tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    assert es.main(["run", "--questions", str(path), "--report-dir", str(tmp_path)], **env) == 2


def test_the_throwaway_user_and_sessions_are_removed(env, tmp_path, engine):
    from sqlalchemy import text

    es.main(["run", "--ids", "q01-nida-principles", "--modes", "rag", "--report-dir", str(tmp_path)], **env)
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM users WHERE email = 'evalsystem@example.invalid'")) == 0


# ---------------------------------------------------------------- the report

def test_the_report_keeps_automated_live_and_manual_parts_apart(env, tmp_path):
    es.main(["run", *IDS, "--report-dir", str(tmp_path)], **env)
    (auto,) = list(tmp_path.glob("system-automated-*.jsonl"))
    live = tmp_path / "live.jsonl"
    live.write_text("", encoding="utf-8")
    out = tmp_path / "report.md"
    assert eval_report.write_report(auto, live, out, es.DEFAULT_QUESTIONS) == 0
    text_ = out.read_text(encoding="utf-8")
    assert "## A. Automated results (scripted mock model" in text_ and "## B. Live results" in text_ and "No live run has been performed" in text_
    assert "## C. Manual observations" in text_ and "Faithfulness (1-3)" in text_ and "not a hallucination rate" not in text_.replace("Nothing in this report is a hallucination rate", "")
    assert "Nothing in this report is a hallucination rate" in text_ and "one small local model on one machine" in text_
    assert text_.index("## A.") < text_.index("## B.") < text_.index("## C.")


def test_the_report_lists_failed_live_runs_and_prepares_an_empty_manual_table(env, tmp_path):
    es.main(["run", *IDS, "--report-dir", str(tmp_path)], **env)
    (auto,) = list(tmp_path.glob("system-automated-*.jsonl"))
    meta = {"type": "meta", "run_type": "live", "started_at": "2026-01-01T00:00:00+00:00", "model": "qwen3.5-16k", "disclaimer": "x",
            "model_facts": {"exposed": True, "parameter_size": "9.7B", "quantization": "Q4_K_M", "context_length": 16384},
            "config": {"config_fingerprint": "abc", "prompt_version": "answer-v1", "embedding_model": "m", "embedding_fingerprint": "f", "chunking_version": "c"},
            "settings": {"top_k": 5, "retrieval_min_similarity": 0.45, "llm_max_output_tokens": 1500, "llm_context_token_budget": 6000,
                         "llm_timeout_seconds": 300, "llm_max_concurrency": 1}}
    runs = [run("q01-nida-principles", "research", "rag"),
            run("q11-comparison", "comparison", "both", error_code="llm_bad_output", http_status=502, outcome="error:llm_bad_output", wall_s=147.0, llm_called=False)]
    live = tmp_path / "live.jsonl"
    live.write_text("\n".join(json.dumps(r) for r in [meta, *runs]), encoding="utf-8")
    out = tmp_path / "report.md"
    eval_report.write_report(auto, live, out, es.DEFAULT_QUESTIONS)
    body = out.read_text(encoding="utf-8")
    assert "`q11-comparison` / both: `llm_bad_output` (HTTP 502) after 147.0 s" in body
    assert "9.7B parameters, Q4_K_M, context 16384 tokens" in body and "`qwen3.5-16k`" in body
    manual = body.split("## C. Manual observations")[1].split("## Known limitations")[0]
    assert "| 1 | `q01-nida-principles` | rag |  |  |  |" in manual                # rating cells are empty for the owner


def test_the_report_has_no_answer_text(env, tmp_path):
    es.main(["run", *IDS, "--report-dir", str(tmp_path)], **env)
    (auto,) = list(tmp_path.glob("system-automated-*.jsonl"))
    live = tmp_path / "live.jsonl"
    live.write_text("", encoding="utf-8")
    out = tmp_path / "report.md"
    eval_report.write_report(auto, live, out, es.DEFAULT_QUESTIONS)
    assert "hypothetical patient" not in out.read_text(encoding="utf-8")        # scripted answer text stays in the raw file


def test_check_patterns_runs_on_the_test_database(env, capsys):
    code = es.main(["check-patterns"], engine=env["engine"])
    assert code in (0, 1) and "chunks containing a pattern" in capsys.readouterr().out
