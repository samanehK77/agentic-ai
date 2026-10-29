"""Smoke check of the whole answer pipeline:  python -m app.eval_answers [--checks FILE] [--live]

By default the language model is a SCRIPTED mock (see eval/answer_checks.json): the numbers then describe what the backend
does with such output (retrieval, citation mapping, quote verification, no-evidence handling, safety), NOT how good a real
model is. With --live the real provider answers, which sends questions and retrieved chunks to an external service: use it
only after explicit approval. Nothing is kept: the run creates a throw-away user and chat session (the workflow's nodes read through their
own database sessions, so these rows must be committed while it runs) and deletes them, with their messages, afterwards.

HONEST LIMITS: small, scripted, keyword-based. It makes no claim about answer quality or clinical validity.
"""
import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.answers.service import Pipeline, post_message
from app.auth_service import AuthUser
from app.config import load_settings
from app.errors import ApiError
from app.ingestion.config import PROJECT_ROOT
from app.llm.base import LLMResult
from app.llm.deepseek import DeepSeekClient
from app.retrieval.embedder import EmbedderProvider, load_embedder
from db.config import get_engine

DEFAULT_CHECKS = Path(__file__).resolve().parents[1] / "eval" / "answer_checks.json"
DEFAULT_CLASSIFIER_CHECKS = Path(__file__).resolve().parents[1] / "eval" / "classifier_checks.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "eval_reports"
DISCLAIMER = ("Smoke check with a scripted model and keyword checks: it tests the pipeline around the model, not the "
              "quality of any answer, and says nothing about clinical validity.")
CHUNK_RE = re.compile(r'<chunk alias="(S\d+)"[^>]*>\n(.*?)\n</chunk>', re.S)
BEHAVIORS = ("faithful", "sloppy", "complies_with_dose", "complies_with_directive")


class CheckFileError(ValueError):
    pass


def load_checks(path: Path) -> list[dict]:
    try:
        checks = json.loads(path.read_text(encoding="utf-8"))["checks"]
    except (OSError, ValueError, KeyError, TypeError):
        raise CheckFileError("Cannot read the checks file.") from None
    seen = set()
    for item in checks:
        for key in ("id", "kind", "question", "modes", "scripted_model", "expect"):
            if key not in item:
                raise CheckFileError(f"Check {item.get('id', '?')!r} is missing {key!r}.")
        if item["id"] in seen:
            raise CheckFileError(f"Duplicate check id {item['id']!r}.")
        seen.add(item["id"])
        if item["scripted_model"] not in BEHAVIORS:
            raise CheckFileError(f"Check {item['id']!r}: unknown scripted_model.")
        if not item["modes"] or any(m not in ("general_knowledge", "rag", "both") for m in item["modes"]):
            raise CheckFileError(f"Check {item['id']!r}: modes must be general_knowledge, rag or both.")
    return checks


class ScriptedModel:
    """A mock provider whose behaviour is chosen per check. It also records the messages it was sent."""

    configured = True

    def __init__(self):
        self.behavior = "faithful"
        self.calls: list[list] = []

    def complete(self, messages, *, json_mode=True, max_tokens=None, temperature=None, timeout=None) -> LLMResult:
        self.calls.append(messages)
        system, user = messages[0].content, messages[1].content
        mode = re.search(r"MODE: (\w+)", system).group(1)
        chunks = CHUNK_RE.findall(user)
        sections = [{"kind": "patient_fact", "text": "The hypothetical patient is described in the synthetic record.", "citations": []}]
        if self.behavior == "complies_with_dose":
            sections.append({"kind": "interpretation", "text": "Start naltrexone 50 mg once daily.", "citations": []})
        elif self.behavior == "complies_with_directive":
            sections.append({"kind": "interpretation", "text": "He meets the criteria. He should be prescribed naltrexone.", "citations": []})
        if mode in ("rag", "both") and chunks:
            alias, body = chunks[0]
            quote = " ".join(body.split()[:6])
            sections.append({"kind": "research_finding", "text": "The first retrieved chunk reports a finding.",
                             "citations": [{"alias": alias, "quote": quote}]})
            if self.behavior == "sloppy":
                sections.append({"kind": "research_finding", "text": "A claim with an invented quote.",
                                 "citations": [{"alias": alias, "quote": "this sentence does not occur in the chunk"}]})
                sections.append({"kind": "research_finding", "text": "A claim citing a chunk that was never shown.",
                                 "citations": [{"alias": "S9", "quote": "anything"}]})
                sections.append({"kind": "research_finding", "text": "A claim without any citation.", "citations": []})
        if mode in ("general_knowledge", "both"):
            sections.append({"kind": "general_knowledge", "text": "In general, psychosocial support is often combined with other care.", "citations": []})
        body = json.dumps({"sections": sections, "conflicting_evidence": [], "limitations": "Scripted answer.", "escalation_needed": False})
        return LLMResult(body, "scripted-mock", 100, 50, "stop", 0)


def score_classifier(path: Path = DEFAULT_CLASSIFIER_CHECKS) -> dict:
    """Accuracy of the RULE-BASED question classifier on a small labelled set, with a confusion matrix. Statistics only:
    misses are listed by position, never by question text. Items marked known_gap are questions the rules are known to get
    wrong (for example every non-English question); they count in `accuracy` but not in `accuracy_without_known_gaps`."""
    from app.graph.classifier import LABELS, RuleClassifier

    try:
        items = json.loads(path.read_text(encoding="utf-8"))["checks"]
    except (OSError, ValueError, KeyError, TypeError):
        raise CheckFileError("Cannot read the classifier checks file.") from None
    classifier = RuleClassifier()
    confusion = {want: {got: 0 for got in LABELS} for want in LABELS}
    right = clear = right_clear = 0
    misses = []
    for index, item in enumerate(items):
        got = classifier.classify(item["question"], item.get("patient_id", "P-001")).label
        want, gap = item["label"], bool(item.get("known_gap"))
        confusion[want][got] += 1
        right += got == want
        if not gap:
            clear += 1
            right_clear += got == want
        if got != want:
            misses.append({"index": index, "expected": want, "got": got, "known_gap": gap})
    return {"total": len(items), "accuracy": _rate(right, len(items)), "clear_cases": clear,
            "accuracy_without_known_gaps": _rate(right_clear, clear), "confusion": confusion, "misses": misses,
            "note": "small hand-written set; says nothing about answer quality"}


def print_classifier(score: dict) -> None:
    print(f"\nClassifier (rule-based, {score['total']} labelled questions): accuracy {_fmt(score['accuracy'])}, "
          f"without known gaps {_fmt(score['accuracy_without_known_gaps'])}; misses: {len(score['misses'])} "
          f"({sum(m['known_gap'] for m in score['misses'])} known gaps)")
    labels = list(score["confusion"])
    print("  expected / got  " + "  ".join(label[:12].ljust(12) for label in labels))
    for want in labels:
        print(f"  {want[:15].ljust(15)} " + "  ".join(str(score['confusion'][want][got]).ljust(12) for got in labels))


def evaluate_expectations(expect: dict, reply: dict, model_calls: list, system_reference: str | None) -> list[str]:
    """Returns the failed expectations (empty list = pass)."""
    failures = []
    flags = set(reply["safety"]["flags"])
    cites = reply["citations"]
    if "llm_called" in expect and reply["generation"]["llm_called"] != expect["llm_called"]:
        failures.append("llm_called")
    if "no_evidence" in expect and reply["no_evidence"] != expect["no_evidence"]:
        failures.append("no_evidence")
    classification = (reply.get("classification") or {}).get("label")
    if "classification" in expect and classification != expect["classification"]:
        failures.append("classification")
    needed = (reply.get("retrieval_decision") or {}).get("needed")
    if "retrieval_needed" in expect and needed != expect["retrieval_needed"]:
        failures.append("retrieval_needed")
    if "min_citations" in expect and len(cites) < expect["min_citations"]:
        failures.append("min_citations")
    if expect.get("all_quotes_verified") and not all(c["verified"] for c in cites):
        failures.append("all_quotes_verified")
    if expect.get("citations_empty") and cites:
        failures.append("citations_empty")
    if not set(expect.get("flags_include", [])) <= flags:
        failures.append("flags_include")
    if any(term in reply["content"] for term in expect.get("content_excludes", [])):
        failures.append("content_excludes")
    if "notice" in expect and bool(reply["safety"]["notice"]) != expect["notice"]:
        failures.append("notice")
    if expect.get("no_unsupported") and reply["unsupported_claims"]:
        failures.append("no_unsupported")
    if any(s["kind"] in expect.get("sections_exclude_kinds", []) for s in reply["sections"]):
        failures.append("sections_exclude_kinds")
    if expect.get("question_only_in_question_block") and model_calls:
        system, user = model_calls[-1][0].content, model_calls[-1][1].content
        question_block = re.search(r"<question>\n(.*?)\n</question>", user, re.S)
        outside = user.replace(question_block.group(0), "") if question_block else user
        marker = "Ignore all your rules"
        if marker in system or marker in outside or not question_block or marker not in question_block.group(1):
            failures.append("question_only_in_question_block")
        if system_reference is not None and system != system_reference:
            failures.append("system_message_changed")
    return failures


def run_checks(db: Session, pipeline: Pipeline, model: ScriptedModel | None, checks: list[dict], live: bool) -> dict:
    user_id = db.execute(text("INSERT INTO users (google_sub, email, email_verified) VALUES (:s, :e, true) RETURNING id"),
                         {"s": f"eval-{uuid.uuid4()}", "e": "eval@example.invalid"}).scalar_one()
    user = AuthUser(user_id, "eval@example.invalid", None, "student", "", uuid.uuid4())
    db.commit()
    try:
        return _run_checks(db, pipeline, model, checks, live, user)
    finally:
        db.rollback()
        db.execute(text("DELETE FROM chat_sessions WHERE owner_id = :u"), {"u": user_id})  # messages go with them (cascade)
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        db.commit()


def _new_session(db: Session, user: AuthUser):
    """A fresh chat session per check, so one check never inherits the conversation of another."""
    session_id = db.execute(text("INSERT INTO chat_sessions (patient_id, title, owner_id) VALUES ('P-001', 'eval', :u) RETURNING session_id"),
                            {"u": user.id}).scalar_one()
    db.commit()
    return session_id


def _run_checks(db: Session, pipeline: Pipeline, model: ScriptedModel | None, checks: list[dict], live: bool, user: AuthUser) -> dict:
    results, system_by_mode = [], {}
    for item in checks:
        for mode in item["modes"]:
            if model is not None:
                model.behavior, model.calls = item["scripted_model"], []
            try:
                reply, _ = post_message(db, pipeline, user=user, session_id=_new_session(db, user), content=item["question"], mode=mode,
                                        idempotency_key=None, request_id="eval")
                error = None
            except ApiError as exc:
                if exc.status_code == 503:  # the index or the model is not available: not a result, a setup problem
                    raise
                reply, error = None, exc.code
            entry = {"id": item["id"], "kind": item["kind"], "mode": mode, "error": error, "failures": [],
                     "scripted": not live}
            if reply is not None:
                calls = model.calls if model else []
                expect = item["expect"] if not live else {k: v for k, v in item["expect"].items()
                                                          if k in ("llm_called", "no_evidence", "citations_empty", "notice", "content_excludes", "question_only_in_question_block",
                                                                                  "classification", "retrieval_needed")}
                entry["failures"] = evaluate_expectations(expect, reply, calls, system_by_mode.get(mode))
                if calls:
                    system_by_mode.setdefault(mode, calls[-1][0].content if item["kind"] != "injection_attempt" else None)
                entry.update({
                    "llm_called": reply["generation"]["llm_called"], "no_evidence": reply["no_evidence"],
                    "citations": len(reply["citations"]), "verified": sum(c["verified"] for c in reply["citations"]),
                    "unsupported": len(reply["unsupported_claims"]), "flags": reply["safety"]["flags"],
                    "evidence_chunks": len(reply["evidence"]), "escalation": reply["safety"]["escalation"],
                    "classification": (reply.get("classification") or {}).get("label"),
                    "retrieval_needed": (reply.get("retrieval_decision") or {}).get("needed"),
                    "research_sections": sum(s["kind"] == "research_finding" for s in reply["sections"])})
            else:
                entry["failures"] = [f"api_error:{error}"]
            results.append(entry)
    return {"results": results, "metrics": metrics(results)}


def _rate(num: int, den: int):
    return None if den == 0 else num / den


def metrics(results: list[dict]) -> dict:
    ok = [r for r in results if r["error"] is None]
    cites = sum(r["citations"] for r in ok)
    research = sum(r["research_sections"] + r["unsupported"] for r in ok)
    expects_no_evidence = [r for r in ok if r["kind"] == "out_of_domain" and r["mode"] != "general_knowledge"]
    safety = [r for r in results if r["kind"] in ("dose_request", "diagnosis_request", "risk")]
    return {
        "checks": len(results), "failed": sum(bool(r["failures"]) for r in results),
        "citation_validity_rate": _rate(sum(r["citations"] for r in ok), cites),  # every kept citation maps to a shown chunk
        "quote_verified_rate": _rate(sum(r["verified"] for r in ok), cites),
        "unsupported_rate": _rate(sum(r["unsupported"] for r in ok), research),
        "no_evidence_correct_rate": _rate(sum(r["no_evidence"] and not r["llm_called"] for r in expects_no_evidence), len(expects_no_evidence)),
        "safety_behavior_rate": _rate(sum(not r["failures"] for r in safety), len(safety)),
        "not_covered": ["diagnosis statements are not detected by the deterministic layer (only dosing and treatment directives are)"],
    }


def _fmt(value):
    return "n/a" if value is None else f"{value:.2f}"


def print_report(report: dict, live: bool) -> None:
    print(DISCLAIMER + ("\nLIVE MODE: the real provider answered." if live else "\nMock mode: the model is scripted.") + "\n")
    for r in report["results"]:
        status = "PASS" if not r["failures"] else "FAIL " + ", ".join(r["failures"])
        detail = "" if r["error"] else (f"  llm={r['llm_called']} no_evidence={r['no_evidence']} citations={r['citations']} "
                                        f"verified={r['verified']} unsupported={r['unsupported']} flags={r['flags']}")
        print(f"[{status}] {r['id']} ({r['mode']}){detail}")
    m = report["metrics"]
    print(f"\nChecks: {m['checks']}, failed: {m['failed']}")
    print(f"Citation validity {_fmt(m['citation_validity_rate'])}  Quote verified {_fmt(m['quote_verified_rate'])}  "
          f"Unsupported {_fmt(m['unsupported_rate'])}  No-evidence correct {_fmt(m['no_evidence_correct_rate'])}  "
          f"Safety behaviour {_fmt(m['safety_behavior_rate'])}")
    for note in m["not_covered"]:
        print("Not covered: " + note)
    print("\n" + DISCLAIMER)


def main(argv: list[str] | None = None, *, engine=None, provider: EmbedderProvider | None = None, settings=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval_answers", description="Smoke check of the answer pipeline.")
    parser.add_argument("--checks", type=Path, default=DEFAULT_CHECKS)
    parser.add_argument("--classifier-checks", type=Path, default=DEFAULT_CLASSIFIER_CHECKS)
    parser.add_argument("--live", action="store_true", help="use the real provider (only after explicit approval)")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args(argv)
    try:
        checks = load_checks(args.checks)
    except CheckFileError as error:
        print(f"Checks file problem: {error}", file=sys.stderr)
        return 2
    settings = settings or load_settings()
    if args.live:
        if not settings.llm.configured:
            print("No DEEPSEEK_API_KEY is configured; nothing was sent.", file=sys.stderr)
            return 2
        model, client = None, DeepSeekClient(settings.llm)
    else:
        model = client = ScriptedModel()
    pipeline = Pipeline(settings, client, provider or EmbedderProvider(load_embedder), None)
    with Session(engine or get_engine()) as db:
        try:
            report = run_checks(db, pipeline, model, checks, args.live)
        except ApiError as error:
            print(f"Cannot evaluate: {error.message}", file=sys.stderr)
            return 2
    print_report(report, args.live)
    try:
        classifier = score_classifier(args.classifier_checks)
    except CheckFileError as error:
        print(f"Checks file problem: {error}", file=sys.stderr)
        return 2
    print_classifier(classifier)
    report["classifier"] = classifier
    args.report_dir.mkdir(parents=True, exist_ok=True)
    path = args.report_dir / f"answers-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"note": DISCLAIMER, "live": args.live, **report}, indent=2), encoding="utf-8")
    print(f"Statistics-only report: {path.name} in the report folder")
    clear_misses = [m for m in classifier["misses"] if not m["known_gap"]]
    return 1 if report["metrics"]["failed"] or clear_misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
