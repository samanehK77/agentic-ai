"""Comparative evaluation of the three answer modes on the same questions.

    python -m app.eval_system run [--live] [--limit N] [--resume FILE] [--timeout S] [--questions FILE] [--modes ...] [--ids ...] [--repeat K]
    python -m app.eval_system report --automated FILE --live FILE --out docs/EVALUATION_REPORT.md
    python -m app.eval_system check-patterns

Two run types that are never mixed:
  (a) AUTOMATED (default): the scripted mock model of app.eval_answers. It tests the pipeline around a model (retrieval,
      routing, citation mapping, quote verification, no-evidence handling, safety), NOT how good any model is.
  (b) LIVE (--live): the real model configured in the environment. Refuses to run unless the model address is this machine
      (a local server such as Ollama). Use it only after the project owner approved real model calls. Runs are SEQUENTIAL
      (LLM_MAX_CONCURRENCY stays 1), appended to a JSONL file as they finish, resumable (--resume FILE skips finished runs) and
      limitable (--limit N counts question-mode runs of this invocation).

Every run is kept, failures included: a 502 or a timeout is a result, not a reason to retry. The only repeat the system makes
is the documented single repair attempt inside the pipeline. NOTHING here is a hallucination rate: a verified quote shows that
the quoted words exist in the cited chunk, not that the claim built on them is supported. Retrieval relevance uses keyword
labels, the sample is tiny, and live numbers describe ONE small local model on ONE machine.

Reuses app.eval_retrieval (relevance labels, Recall@k, MRR, distributions) and app.eval_answers (scripted model, throw-away
user and sessions, rates, classifier scoring), and the diagnostics and audit code for model facts and configuration
fingerprints. Raw results go to the git-ignored data/eval_reports/ folder.
"""
import argparse
import dataclasses
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import eval_answers, eval_retrieval
from app.answers.service import Pipeline, post_message
from app.audit.service import AuditService
from app.auth_service import AuthUser
from app.config import load_settings
from app.diagnostics.checks import Context, _model_facts
from app.errors import ApiError
from app.ingestion.config import PROJECT_ROOT
from app.llm.concurrency import ConcurrencyLimitedClient
from app.llm.deepseek import DeepSeekClient
from app.retrieval import service as retrieval_service
from app.retrieval.embedder import EmbedderProvider, load_embedder
from db.config import get_engine

DEFAULT_QUESTIONS = Path(__file__).resolve().parents[1] / "eval" / "system_questions.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "eval_reports"
MODES = ("general_knowledge", "rag", "both")
KINDS = ("research", "patient_history", "comparison", "out_of_domain", "dose_request")
OUTCOME_OF = {"answered": "answered", "no_evidence": "no_evidence", "unsupported_request": "unsupported", "crisis_notice": "crisis"}
DISCLAIMER = ("Small smoke-level evaluation: 14 questions, one run each, keyword relevance labels, a non-deterministic small local "
              "model, no clinical validity. Verified quotes show that quoted words exist in the cited chunk, not that claims are "
              "supported. Live numbers describe this one small model on this one machine only.")


class QuestionFileError(ValueError):
    pass


# ---------------------------------------------------------------- questions

def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[dict]:
    try:
        questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
    except (OSError, ValueError, KeyError, TypeError):
        raise QuestionFileError("Cannot read the questions file.") from None
    seen = set()
    for q in questions:
        for key in ("id", "kind", "question", "patient_id"):
            if not isinstance(q.get(key), str) or not q[key].strip():
                raise QuestionFileError(f"Every question needs a non-empty {key!r}: {str(q)[:80]}")
        if q["id"] in seen:
            raise QuestionFileError(f"Duplicate question id {q['id']!r}.")
        seen.add(q["id"])
        if q["kind"] not in KINDS:
            raise QuestionFileError(f"Question {q['id']!r}: kind must be one of {KINDS}.")
        if q["kind"] in ("research", "comparison") and not (q.get("expected_papers") and q.get("patterns")):
            raise QuestionFileError(f"Question {q['id']!r} needs expected_papers and patterns.")
    return questions


def retrieval_query(q: dict) -> dict | None:
    """The question in the shape app.eval_retrieval expects (None for questions that are not about the documents)."""
    if q["kind"] in ("research", "comparison"):
        return {"id": q["id"], "kind": "in_domain", "query": q["question"], "expected_papers": q["expected_papers"], "patterns": q["patterns"]}
    if q["kind"] == "out_of_domain":
        return {"id": q["id"], "kind": "out_of_domain", "query": q["question"]}
    return None


# ---------------------------------------------------------------- statistics (small helpers; the heavy ones are reused)

def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; with a handful of values p95 is simply close to the maximum (the report shows n)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(p * len(ordered) + 0.5) - 1))]


def stats(values: list[float]) -> dict:
    return {"n": len(values), "median": median(values) if values else None, "p95": percentile(values, 0.95)}


# ---------------------------------------------------------------- one run

def run_one(db: Session, pipeline: Pipeline, user: AuthUser, q: dict, mode: str, timeline_start: float) -> dict:
    session_id = eval_answers._new_session(db, user)
    started = time.perf_counter()
    entry = {"type": "run", "question_id": q["id"], "kind": q["kind"], "mode": mode, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "error_code": None, "http_status": None}
    try:
        reply, _ = post_message(db, pipeline, user=user, session_id=session_id, content=q["question"], mode=mode, idempotency_key=None,
                                request_id="eval-system")
    except ApiError as error:
        entry.update({"wall_s": round(time.perf_counter() - started, 2), "error_code": error.code, "http_status": error.status_code,
                      "outcome": f"error:{error.code}"})
        return entry
    entry["wall_s"] = round(time.perf_counter() - started, 2)
    generation = reply["generation"]
    cited = [c["chunk_id"] for c in reply["citations"]]
    evidence = {e["chunk_id"]: e for e in reply["evidence"]}
    relevant_cited = None
    rq = retrieval_query(q)
    if rq and rq["kind"] == "in_domain" and cited:
        relevant_cited = sum(eval_retrieval.is_relevant({"paper_id": evidence[c]["paper_id"], "text": evidence[c]["text"] or ""}, rq) for c in cited if c in evidence)
    outcome = "no_evidence" if reply["no_evidence"] else ("unsupported" if "unsupported_request" in reply["safety"]["flags"] else
                                                          "crisis" if reply["safety"]["escalation"] and not generation.get("llm_called") else "answered")
    tokens = generation.get("completion_tokens") or 0
    latency_ms = generation.get("latency_ms") or 0
    entry.update({
        "outcome": outcome, "classification": (reply.get("classification") or {}).get("label"),
        "retrieval_needed": (reply.get("retrieval_decision") or {}).get("needed"), "llm_called": bool(generation.get("llm_called")),
        "evidence_chunks": len(reply["evidence"]), "citations": len(cited), "verified": sum(c["verified"] for c in reply["citations"]),
        "cited_relevant": relevant_cited, "unsupported_claims": len(reply["unsupported_claims"]), "flags": reply["safety"]["flags"],
        "model": generation.get("model"), "prompt_tokens": generation.get("prompt_tokens"), "completion_tokens": tokens,
        "generation_ms": latency_ms, "tokens_per_s": round(tokens / (latency_ms / 1000), 1) if tokens and latency_ms else None,
        "repair_attempted": bool(generation.get("repair_attempted")), "retries": generation.get("retries"),
        "answer_text": (reply["content"] or "")[:3000]})
    return entry


# ---------------------------------------------------------------- aggregation

def question_checks(q: dict, r: dict) -> dict:
    """Per-run correctness flags (None = not applicable)."""
    mode, ok = r["mode"], r.get("error_code") is None
    flags = {"classification_ok": None, "no_evidence_ok": None, "safety_ok": None, "wrongly_no_evidence": None}
    if ok and q.get("expected_classification") and r.get("classification") is not None:
        flags["classification_ok"] = r["classification"] == q["expected_classification"]
    if ok and q["kind"] == "out_of_domain" and mode != "general_knowledge":
        flags["no_evidence_ok"] = r["outcome"] in ("no_evidence", "unsupported") and not r["llm_called"]
    if ok and q["kind"] in ("research", "comparison") and mode != "general_knowledge":
        flags["wrongly_no_evidence"] = r["outcome"] == "no_evidence"
    if q["kind"] == "dose_request":
        flags["safety_ok"] = ok and r["outcome"] == "unsupported" and not r["llm_called"]
    return flags


def summarize_runs(runs: list[dict], questions: dict[str, dict]) -> dict:
    """Metrics per mode. Failed runs count: they are in `runs`, in the error share and in the denominators that say so."""
    out = {}
    for mode in MODES:
        mine = [r for r in runs if r["mode"] == mode]
        called = [r for r in mine if r.get("llm_called") or r.get("error_code") in ("llm_bad_output", "llm_timeout", "llm_unavailable", "workflow_timeout")]
        succeeded_called = [r for r in mine if r.get("llm_called")]
        cites = sum(r.get("citations", 0) for r in succeeded_called)
        flags = [question_checks(questions[r["question_id"]], r) for r in mine if r["question_id"] in questions]
        research_runs = [r for r in succeeded_called if r["kind"] in ("research", "comparison")]
        rel_known = [r for r in research_runs if r.get("cited_relevant") is not None and r.get("citations")]
        out[mode] = {
            "runs": len(mine), "errors": sum(r.get("error_code") is not None for r in mine),
            "error_codes": {code: sum(r.get("error_code") == code for r in mine) for code in sorted({r["error_code"] for r in mine if r.get("error_code")})},
            "model_runs": len(called), "first_try_valid_json": eval_answers._rate(sum(not r.get("repair_attempted") for r in succeeded_called), len(called)),
            "repair_needed": eval_answers._rate(sum(bool(r.get("repair_attempted")) for r in succeeded_called)
                                                + sum(r.get("error_code") == "llm_bad_output" for r in mine), len(called)),
            "failed_after_repair_or_timeout": eval_answers._rate(sum(r.get("error_code") is not None for r in called), len(called)),
            "wall_s": stats([r["wall_s"] for r in mine if r.get("error_code") is None and r.get("llm_called")]),
            "wall_s_all_runs": stats([r["wall_s"] for r in mine]),
            "tokens_per_s": stats([r["tokens_per_s"] for r in succeeded_called if r.get("tokens_per_s")]),
            "citations": cites, "quote_verified_share": eval_answers._rate(sum(r.get("verified", 0) for r in succeeded_called), cites),
            "cited_chunk_relevance": eval_answers._rate(sum(r["cited_relevant"] for r in rel_known), sum(r["citations"] for r in rel_known)),
            "unsupported_claims": sum(r.get("unsupported_claims", 0) for r in succeeded_called),
            "answers_with_unsupported_claims": sum(r.get("unsupported_claims", 0) > 0 for r in succeeded_called),
            "classification_accuracy": eval_answers._rate(sum(f["classification_ok"] is True for f in flags), sum(f["classification_ok"] is not None for f in flags)),
            "no_evidence_correct": eval_answers._rate(sum(f["no_evidence_ok"] is True for f in flags), sum(f["no_evidence_ok"] is not None for f in flags)),
            "research_wrongly_no_evidence": eval_answers._rate(sum(f["wrongly_no_evidence"] is True for f in flags), sum(f["wrongly_no_evidence"] is not None for f in flags)),
            "safety_correct": eval_answers._rate(sum(f["safety_ok"] is True for f in flags), sum(f["safety_ok"] is not None for f in flags)),
        }
    return out


def retrieval_metrics(db: Session, provider: EmbedderProvider, questions: list[dict], top_k: int = 10) -> dict:
    queries = [rq for rq in (retrieval_query(q) for q in questions) if rq]
    report = eval_retrieval.evaluate(db, provider, queries, top_k)
    return {"top_k": top_k, "metrics": report["metrics"], "top1_similarity": report["top1_similarity"], "weakest": report["weakest"],
            "per_query": [{"id": e["id"], "kind": e["kind"], "rank": e.get("rank"), "top1_similarity": e["top1_similarity"]} for e in report["per_query"]]}


# ---------------------------------------------------------------- JSONL state (resumable)

def read_state(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def meta_record(settings, engine, live: bool) -> dict:
    audit = AuditService(engine)
    snapshot = audit.config_snapshot(settings, EmbedderProvider(load_embedder))
    facts = {}
    if live:
        ctx = Context(engine, settings, EmbedderProvider(load_embedder))
        (check,) = _model_facts(ctx)
        facts = check.facts
    return {"type": "meta", "run_type": "live" if live else "automated", "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": "scripted-mock" if not live else settings.llm.model, "model_facts": facts, "config": snapshot,
            "settings": {"top_k": settings.answer_top_k, "retrieval_min_similarity": settings.retrieval_min_similarity,
                         "llm_max_output_tokens": settings.llm.max_output_tokens, "llm_context_token_budget": settings.llm.context_token_budget,
                         "llm_timeout_seconds": settings.llm.timeout_seconds, "llm_max_concurrency": settings.llm.max_concurrency},
            "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------- the run command

def do_run(args, *, engine=None, provider=None, settings=None) -> int:
    try:
        questions = load_questions(args.questions)
    except QuestionFileError as error:
        print(f"Questions file problem: {error}", file=sys.stderr)
        return 2
    by_id = {q["id"]: q for q in questions}
    chosen = [q for q in questions if not args.ids or q["id"] in args.ids]
    modes = [m for m in args.modes if m in MODES]
    settings = settings or load_settings()
    engine = engine or get_engine()
    provider = provider or EmbedderProvider(load_embedder)
    if args.timeout:
        if args.timeout <= settings.llm.timeout_seconds:
            print("--timeout must be larger than LLM_TIMEOUT_SECONDS.", file=sys.stderr)
            return 2
        settings = dataclasses.replace(settings, graph_total_timeout_seconds=float(args.timeout))
    if args.live:
        if not settings.llm.local:
            print("Refusing to run live: the model address is not on this machine (this evaluation only uses a local model).", file=sys.stderr)
            return 2
        model = None
        client = ConcurrencyLimitedClient(DeepSeekClient(settings.llm), 1, settings.llm.queue_wait_seconds)
    else:
        model = client = eval_answers.ScriptedModel()
    pipeline = Pipeline(settings, client, provider, None)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    state_path = args.resume or args.report_dir / f"system-{'live' if args.live else 'automated'}-{stamp}.jsonl"
    state = read_state(state_path)
    done = {(r["question_id"], r["mode"], r.get("repeat", 1)) for r in state if r["type"] == "run"}
    if not state:
        append(state_path, meta_record(settings, engine, args.live))
    with Session(engine) as db:
        if not any(r["type"] == "retrieval" for r in state):
            try:
                append(state_path, {"type": "retrieval", **retrieval_metrics(db, provider, questions)})
            except ApiError as error:
                print(f"Cannot evaluate retrieval: {error.message}", file=sys.stderr)
                return 2
        user_id = db.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES (:s, 'evalsystem@example.invalid', true) RETURNING id"),
                             {"s": f"evalsys-{uuid.uuid4()}"}).scalar_one()
        db.commit()
        user = AuthUser(user_id, "evalsystem@example.invalid", None, "student", "", uuid.uuid4())
        started, finished = time.perf_counter(), 0
        try:
            for repeat in range(1, args.repeat + 1):
                for q in chosen:
                    for mode in modes:
                        if (q["id"], mode, repeat) in done:
                            continue
                        if args.limit and finished >= args.limit:
                            raise StopIteration
                        if model is not None:
                            model.behavior, model.calls = "faithful", []
                        record = run_one(db, pipeline, user, q, mode, started)
                        record["repeat"] = repeat
                        append(state_path, record)
                        finished += 1
                        print(f"[{finished}] {q['id']} / {mode}: {record['outcome']} in {record['wall_s']} s", flush=True)
        except StopIteration:
            pass
        finally:
            db.rollback()
            db.execute(text("DELETE FROM chat_sessions WHERE owner_id = :u"), {"u": user_id})
            db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
            db.commit()
    all_runs = [r for r in read_state(state_path) if r["type"] == "run"]
    total = len(chosen) * len(modes) * args.repeat
    print(f"\nThis invocation: {finished} run(s) in {time.perf_counter() - started:.0f} s. State file: {state_path.name} "
          f"({len(all_runs)} of {total} planned run(s) finished). Resume with: --resume {state_path}")
    summary = summarize_runs(all_runs, by_id)
    for mode in MODES:
        s = summary[mode]
        print(f"  {mode:<18} runs {s['runs']:>3}  errors {s['errors']:>2}  median wall {s['wall_s']['median']}")
    print("\n" + DISCLAIMER)
    return 0


def do_check_patterns(args, *, engine=None) -> int:
    questions = load_questions(args.questions)
    queries = [rq for rq in (retrieval_query(q) for q in questions) if rq and rq["kind"] == "in_domain"]
    bad = 0
    with Session(engine or get_engine()) as db:
        for query_id, count in eval_retrieval.check_patterns(db, queries):
            print(f"{query_id:<32} chunks containing a pattern in the expected papers: {count}" + ("   <-- none!" if count == 0 else ""))
            bad += count == 0
    return 1 if bad else 0


def main(argv: list[str] | None = None, *, engine=None, provider=None, settings=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval_system", description="Compare general_knowledge, rag and both on the same questions.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the questions (scripted mock by default; --live for the local model)")
    run.add_argument("--live", action="store_true", help="the real LOCAL model (only after the owner approved real model calls)")
    run.add_argument("--limit", type=int, default=0, help="at most this many question-mode runs in this invocation (0 = all)")
    run.add_argument("--resume", type=Path, help="continue a state file (finished runs are skipped)")
    run.add_argument("--timeout", type=int, default=0, help="whole-run limit in seconds per question (default: GRAPH_TOTAL_TIMEOUT_SECONDS)")
    run.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    run.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    run.add_argument("--ids", nargs="+", help="only these question ids")
    run.add_argument("--repeat", type=int, default=1, help="repeat the selection K times (for a run-to-run variance look; n stays tiny)")
    run.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    check = sub.add_parser("check-patterns", help="label sanity: do the patterns occur in the expected papers at all")
    check.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    rep = sub.add_parser("report", help="write the markdown report from state files")
    rep.add_argument("--automated", type=Path, required=True)
    rep.add_argument("--live", type=Path, required=True)
    rep.add_argument("--out", type=Path, required=True)
    rep.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    args = parser.parse_args(argv)
    if args.command == "run":
        return do_run(args, engine=engine, provider=provider, settings=settings)
    if args.command == "check-patterns":
        return do_check_patterns(args, engine=engine)
    from app.eval_report import write_report
    return write_report(args.automated, args.live, args.out, args.questions)


if __name__ == "__main__":
    raise SystemExit(main())
