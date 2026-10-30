"""Writes docs/EVALUATION_REPORT.md from the JSONL state files of app.eval_system. No model is called here.

Keeps three things visibly apart: AUTOMATED results (scripted mock model: tests the pipeline), LIVE results (the real local
model: describes that one small model), and MANUAL observations (an empty table for the project owner to fill in).
The report contains statistics, codes and short labels only; answers stay in the git-ignored raw files."""
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import eval_system as es

FOOTER_LIMITS = """\
* **Tiny sample.** 14 questions, three modes, normally **one run per question and mode**. Differences of a few runs are noise.
* **Keyword labels.** Retrieval relevance and the relevance of cited chunks are judged by keyword patterns in expected papers,
  written before the runs. A relevant chunk can be missed and an irrelevant one can match.
* **Verified quote is not a supported claim.** The validator checks that quoted words exist in the cited chunk. It does not check
  that the claim built on the quote is true or well supported. Nothing in this report is a hallucination rate.
* **Non-deterministic small model.** A 9.7B-parameter, 4-bit local model can answer differently on the same question; one run per
  question cannot show that variance (the optional repeat shows a little of it).
* **One model, one machine.** Live numbers (quality, reliability, waiting times) are valid only for the model and settings in the
  table above, on this hardware. They say nothing about other models and nothing about clinical validity.
* **Automated results test the pipeline, not a model.** The scripted mock model always answers in the right format.
* **No clinical validity.** This is an educational prototype with synthetic patients. It does not diagnose, prescribe or choose
  treatments, and no result here supports any clinical use.
* **Failures are results.** Failed runs (502, timeouts, busy model) are counted in every share that says so and are listed in part B.
  No run was dropped and nothing was retried beyond the pipeline's documented single repair attempt.
"""


def pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.0f} %"


def num(value, digits=1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def st(s: dict, unit="s") -> str:
    """median / p95 with the sample size."""
    return "n/a" if not s["n"] else f"{num(s['median'])} / {num(s['p95'])} {unit} (n={s['n']})"


def mode_table(summary: dict) -> list[str]:
    rows = ["| Measure | General Knowledge | RAG | Both |", "|---|---|---|---|"]
    get = lambda key, fmt: [fmt(summary[m][key]) for m in es.MODES]
    for label, key, fmt in (
        ("Runs", "runs", str), ("Runs that ended in an error (502, timeout, busy ...)", "errors", str),
        ("Runs that needed the model", "model_runs", str),
        ("Valid JSON on the first try (of model runs)", "first_try_valid_json", pct),
        ("Needed the one repair attempt, whether it worked or not (of model runs)", "repair_needed", pct),
        ("Failed after repair, or timed out (of model runs)", "failed_after_repair_or_timeout", pct),
        ("Citations returned", "citations", str), ("Citations with a verified quote", "quote_verified_share", pct),
        ("Cited chunks judged relevant (keyword labels)", "cited_chunk_relevance", pct),
        ("Unsupported claims reported (count)", "unsupported_claims", str),
        ("Answers with at least one unsupported claim", "answers_with_unsupported_claims", str),
        ("Classification matched the expected label", "classification_accuracy", pct),
        ("Out-of-domain questions ended as no-evidence or unsupported, without a model call", "no_evidence_correct", pct),
        ("Research questions wrongly ended as no-evidence", "research_wrongly_no_evidence", pct),
        ("Dose request stopped before the model", "safety_correct", pct),
    ):
        rows.append(f"| {label} | " + " | ".join(get(key, fmt)) + " |")
    rows.append("| Wall time per answered run, median / p95 | " + " | ".join(st(summary[m]["wall_s"]) for m in es.MODES) + " |")
    rows.append("| Wall time, all runs incl. no-model runs and errors | " + " | ".join(st(summary[m]["wall_s_all_runs"]) for m in es.MODES) + " |")
    rows.append("| Tokens per second (completion tokens / generation time) | " + " | ".join(st(summary[m]["tokens_per_s"], "tok/s") for m in es.MODES) + " |")
    return rows


def retrieval_section(retrieval: dict | None) -> list[str]:
    if not retrieval:
        return ["_No retrieval metrics in the state file._"]
    m, sim = retrieval["metrics"], retrieval["top1_similarity"]
    inn, out = sim["in_domain"], sim["out_of_domain"]
    return [f"Same retrieval code as the API (`top_k` {retrieval['top_k']}, no similarity threshold), run once per question (independent of mode). "
            f"In-domain questions: **{m['queries']}**.", "",
            "| Recall@1 | Recall@3 | Recall@5 | MRR |", "|---|---|---|---|",
            f"| {num(m['recall@1'], 2)} | {num(m['recall@3'], 2)} | {num(m['recall@5'], 2)} | {num(m['mrr'], 2)} |", "",
            f"Top-1 cosine similarity, in-domain (n={inn['n']}): min {num(inn['min'], 2)}, median {num(inn['median'], 2)}, max {num(inn['max'], 2)}. "
            f"Out-of-domain (n={out['n']}): min {num(out['min'], 2)}, median {num(out['median'], 2)}, max {num(out['max'], 2)}.", "",
            "Questions with no relevant chunk in the top 5: " + (", ".join(f"`{i}`" for i in retrieval["weakest"]) or "none") + "."]


def per_question_table(runs: list[dict], questions: list[dict]) -> list[str]:
    rows = ["| Question | Kind | Mode | Outcome | Wall s | Evidence | Citations (verified) | Unsupported claims | Repair |", "|---|---|---|---|---|---|---|---|---|"]
    order = {q["id"]: i for i, q in enumerate(questions)}
    for r in sorted(runs, key=lambda r: (order.get(r["question_id"], 99), es.MODES.index(r["mode"]), r.get("repeat", 1))):
        cites = "" if r.get("error_code") else f"{r.get('citations', 0)} ({r.get('verified', 0)})"
        rows.append(f"| `{r['question_id']}`{' #' + str(r['repeat']) if r.get('repeat', 1) > 1 else ''} | {r['kind']} | {r['mode']} | {r['outcome']} | {r['wall_s']} | "
                    f"{r.get('evidence_chunks', '')} | {cites} | {r.get('unsupported_claims', '')} | {'yes' if r.get('repair_attempted') else ''} |")
    return rows


def setup_table(meta: dict, runs: list[dict]) -> list[str]:
    cfg, facts, s = meta["config"], meta.get("model_facts") or {}, meta["settings"]
    rows = [f"| Run type | {meta['run_type']} |", f"| Started | {meta['started_at']} |", f"| Model | `{meta['model']}` |"]
    if facts.get("exposed"):
        rows += [f"| Model facts (read from the local server) | {facts.get('parameter_size')} parameters, {facts.get('quantization')}, context {facts.get('context_length')} tokens |"]
    rows += [f"| Configuration fingerprint | `{cfg.get('config_fingerprint')}` (prompt `{cfg.get('prompt_version')}`, top_k {s['top_k']}, threshold {s['retrieval_min_similarity']}) |",
             f"| Embedding model / fingerprint | `{cfg.get('embedding_model')}` / `{cfg.get('embedding_fingerprint')}` |", f"| Chunking version (hash) | `{cfg.get('chunking_version')}` |",
             f"| Model limits | max output {s['llm_max_output_tokens']} tokens, context budget {s['llm_context_token_budget']}, timeout {s['llm_timeout_seconds']} s, concurrency {s['llm_max_concurrency']} |",
             f"| Runs | {len(runs)} ({len({r['question_id'] for r in runs})} questions) |"]
    return ["| Item | Value |", "|---|---|", *rows]


def failed_list(runs: list[dict]) -> list[str]:
    bad = [r for r in runs if r.get("error_code")]
    if not bad:
        return ["No run ended in an error."]
    return [f"* `{r['question_id']}` / {r['mode']}: `{r['error_code']}` (HTTP {r['http_status']}) after {r['wall_s']} s" for r in bad]


def manual_table(live_runs: list[dict]) -> list[str]:
    """About ten answered live runs to rate by hand: research in rag and both, a general-knowledge answer, history, comparison."""
    picks, seen = [], set()
    for _ in range(2):  # up to two answers per kind and mode, ten in all
        for want in ("research", "comparison", "patient_history"):
            for mode in ("rag", "both", "general_knowledge"):
                for r in live_runs:
                    key = (r["question_id"], r["mode"])
                    if r["kind"] == want and r["mode"] == mode and r.get("outcome") == "answered" and key not in seen and len(picks) < 10:
                        picks.append(r)
                        seen.add(key)
                        break
    rows = ["| # | Question id | Mode | Faithfulness (1-3) | Helpfulness (1-3) | Notes |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(picks, 1):
        rows.append(f"| {i} | `{r['question_id']}` | {r['mode']} |  |  |  |")
    if not picks:
        rows.append("| 1 |  |  |  |  |  |")
    return rows


def observations(summary: dict, runs: list[dict]) -> list[str]:
    """Plain statements computed from the live runs (no interpretation beyond counting)."""
    lines = []
    model_runs = sum(summary[m]["model_runs"] for m in es.MODES)
    failed = [r for r in runs if r.get("error_code")]
    lines.append(f"* **Reliability.** {len(failed)} of {model_runs} runs that reached the model ended in an error "
                 f"({', '.join(sorted({r['error_code'] for r in failed})) or 'none'}); the pipeline's one repair attempt did not rescue them. "
                 f"Every such run is listed above and kept in the figures.")
    history = [r for r in runs if r["kind"] == "patient_history" and r["mode"] != "general_knowledge" and r.get("outcome") == "no_evidence"]
    if history:
        lines.append("* **Routing.** A patient-history question ended as no-evidence in RAG or Both mode because it was searched in the documents: "
                     + ", ".join(sorted({f"`{r['question_id']}`" for r in history})) + ". That is a classifier limit, not a model result.")
    rag, gk = summary["rag"]["wall_s"], summary["general_knowledge"]["wall_s"]
    if rag["n"] and gk["n"]:
        lines.append(f"* **Waiting time.** Median wall time of answered runs: General Knowledge {num(gk['median'])} s, RAG {num(rag['median'])} s, "
                     f"Both {num(summary['both']['wall_s']['median'])} s.")
    cites = summary["rag"]["quote_verified_share"]
    if cites is not None:
        lines.append(f"* **Citations.** In RAG mode {pct(cites)} of the citations carried a quote that exists in the cited chunk. A verified quote is "
                     "not a supported claim, and an unverified one is shown to the student as unverified, not hidden.")
    return lines


def write_report(automated: Path, live: Path, out: Path, questions_path: Path) -> int:
    questions = es.load_questions(questions_path)
    by_id = {q["id"]: q for q in questions}
    a_state, l_state = es.read_state(automated), es.read_state(live)
    a_meta = next((r for r in a_state if r["type"] == "meta"), None)
    l_meta = next((r for r in l_state if r["type"] == "meta"), None)
    a_runs = [r for r in a_state if r["type"] == "run"]
    l_runs = [r for r in l_state if r["type"] == "run"]
    retrieval = next((r for r in (l_state + a_state) if r["type"] == "retrieval"), None)
    lines = [
        "# Evaluation report: general knowledge, RAG and both on the same questions", "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `python -m app.eval_system report`. "
        "**Read the limits at the end before quoting any number.**", "",
        "> Educational prototype, synthetic patients, no clinical validity. The live numbers describe **one small local model on one "
        "machine** and nothing else. Gmail/e-mail reporting from the original spec was deliberately not implemented and is not evaluated.", "",
        "The same 14 questions (`backend/eval/system_questions.json`: at least one per document, two patient-history, one comparison, "
        "two out-of-domain, one dose request) run in all three modes. Three parts are kept apart: **A** automated (scripted mock model), "
        "**B** live (your local model), **C** manual observations.", ""]
    lines += ["## Retrieval (keyword labels)", "", *retrieval_section(retrieval), ""]
    lines += ["## A. Automated results (scripted mock model: tests the pipeline, not a model)", ""]
    if a_meta:
        lines += [*setup_table(a_meta, a_runs), "", *mode_table(es.summarize_runs(a_runs, by_id)), "",
                  "The mock model always answers in valid JSON and quotes the first chunk it is shown, so reliability and quality figures here "
                  "only show that the pipeline around a model works. Latencies and tokens per second are those of the mock and mean nothing.", ""]
    else:
        lines += ["_The automated run was not included._", ""]
    lines += ["## B. Live results (real local model)", ""]
    if l_meta and l_runs:
        summary = es.summarize_runs(l_runs, by_id)
        lines += [*setup_table(l_meta, l_runs), "", "### Mode comparison", "", *mode_table(summary), "",
                  "Latency shares and reliability are over the runs listed; with this few runs a single failure moves a share by several points.", "",
                  "### Observations (counted from the runs above)", "", *observations(summary, l_runs), "",
                  f"Raw runs, including the answer texts, are in the git-ignored `data/eval_reports/{live.name}`.", "",
                  "### Per question and mode (every run)", "", *per_question_table(l_runs, questions), "",
                  "### Failed runs", "", *failed_list(l_runs), ""]
    else:
        lines += ["_No live run has been performed for this report._", ""]
    lines += ["## C. Manual observations (to be filled in by hand; not automated results)", "",
              "Read the answers in the application (or the raw file in `data/eval_reports/`) and rate each: faithfulness (are the claims backed by the cited "
              "passages? 1 = mostly not, 2 = partly, 3 = yes) and helpfulness (would a psychology student learn from it? 1-3). Add notes. "
              "This table is intentionally empty and is **not** part of any figure above.", "", *manual_table(l_runs), ""]
    lines += ["## Known limitations and honest boundaries", "", FOOTER_LIMITS]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    print("Use: python -m app.eval_system report --automated FILE --live FILE --out FILE", file=sys.stderr)
    raise SystemExit(2)
