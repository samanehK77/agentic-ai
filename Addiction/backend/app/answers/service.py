"""The answer pipeline. The model writes; this code decides what is retrieved, what is sent, what is accepted and what is
stored. All of it happens in ONE database transaction: on any failure nothing is persisted."""
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth_service import AuthUser
from app.errors import ApiError, not_found
from app.llm import prompt as prompts
from app.llm import safety
from app.llm.base import (
    BaseLLMClient, LLMBadOutput, LLMError, LLMMessage, LLMNotConfigured, LLMTimeout, LLMUnavailable)
from app.llm.config import LLMSettings
from app.llm.schema import ModelAnswer, describe_errors
from app.llm.validate import EvidenceItem, validate_answer
from app.repositories import answers as repo
from app.repositories import patients as patients_repo
from app.repositories import sessions as sessions_repo
from app.retrieval import service as retrieval_service
from app.retrieval.embedder import EmbedderProvider
from app.retrieval.ratelimit import SlidingWindowLimiter

logger = logging.getLogger("mindevidence.answers")

NO_EVIDENCE_TEXT = (
    "No supporting evidence was found in the research documents for this question, so no research-based answer is "
    "given. Try rephrasing the question, or switch to General Knowledge mode for an answer that is clearly labelled as "
    "not coming from the documents.")
RESPONSE_VERSION = 1


@dataclass
class Pipeline:
    """Everything the pipeline needs from the application (settings, clients, limiter)."""

    settings: "object"  # app.config.Settings
    llm: BaseLLMClient
    embedder_provider: EmbedderProvider
    limiter: SlidingWindowLimiter | None = None

    @property
    def llm_settings(self) -> LLMSettings:
        return self.settings.llm


@dataclass
class Replay:
    """The stored reply of an earlier request with the same Idempotency-Key and body."""

    reply: dict


# ---------------------------------------------------------------- LLM call with one bounded repair

def _parse(text: str) -> ModelAnswer:
    return ModelAnswer.model_validate(json.loads(text))


def _llm_error(error: LLMError) -> ApiError:
    if isinstance(error, LLMNotConfigured):
        return ApiError(503, "llm_not_configured", "The language model is not configured on this server.")
    if isinstance(error, LLMTimeout):
        return ApiError(504, "llm_timeout", "The language model did not answer in time. Please try again.")
    if isinstance(error, LLMUnavailable):
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return ApiError(503, "llm_unavailable", "The language model service is not available right now. Please try again later.",
                        headers=headers)
    return ApiError(502, "llm_bad_output", "The language model returned an answer that could not be used.")


def _why(error: Exception) -> str:
    """A safe reason for the log: field paths and error types, or the position of a JSON syntax error. Never the text."""
    if isinstance(error, json.JSONDecodeError):
        return f"not valid json (syntax error at character {error.pos})"
    return describe_errors(error)


def _generate(pipeline: Pipeline, messages: list[LLMMessage]) -> tuple[ModelAnswer, dict]:
    """One call, plus at most ONE repair call when the output is unusable. Returns the parsed answer and usage numbers."""
    client = pipeline.llm
    if not client.configured:
        raise ApiError(503, "llm_not_configured", "The language model is not configured on this server.")
    usage = {"model": None, "prompt_tokens": 0, "completion_tokens": 0, "retries": 0, "repair_attempted": False}

    def call(msgs: list[LLMMessage]):
        try:
            result = client.complete(msgs, json_mode=True)
        except LLMBadOutput:
            raise
        except LLMError as error:
            raise _llm_error(error) from None
        usage["model"] = result.model
        usage["prompt_tokens"] += result.prompt_tokens
        usage["completion_tokens"] += result.completion_tokens
        usage["retries"] += result.retries
        return result

    problems = "the reply was empty or cut off"
    first_text = None
    try:
        first = call(messages)
        first_text = first.text
        return _parse(first.text), usage
    except LLMBadOutput as error:
        logger.warning("model output unusable (attempt 1): %s", error)  # a generic reason, never the output itself
    except (ValueError, ValidationError) as error:
        problems = describe_errors(error)
        logger.warning("model output rejected (attempt 1): %s", _why(error))

    usage["repair_attempted"] = True
    repair = list(messages)
    if first_text is not None:
        repair += [LLMMessage("assistant", first_text[:4000]),
                   LLMMessage("user", prompts.load_prompt("repair_v1.txt").format(problems=problems))]
    try:
        second = call(repair)
        return _parse(second.text), usage
    except LLMBadOutput as error:
        logger.warning("model output unusable (attempt 2, after the repair request): %s", error)
        raise ApiError(502, "llm_bad_output", "The language model returned an answer that could not be used.") from None
    except (ValueError, ValidationError) as error:
        logger.warning("model output rejected (attempt 2, after the repair request): %s", _why(error))
        raise ApiError(502, "llm_bad_output", "The language model returned an answer that could not be used.") from None


# ---------------------------------------------------------------- building and reading replies

def build_reply(db: Session, message: dict, request_id: str | None = None, rows: dict[str, dict] | None = None) -> dict:
    """The AnswerOut dict for a stored assistant message. Used for the POST reply, idempotent replays and GET messages,
    so all three always agree. Chunk text and metadata are joined at read time; a chunk that is gone or whose text
    changed is marked stale."""
    stored, generation = message["response"], message["generation"] or {}
    refs = stored.get("evidence", [])
    rows = rows if rows is not None else repo.chunk_rows(db, [r["chunk_id"] for r in refs])
    cited = {c["chunk_id"] for c in stored.get("citations", [])}

    def stale(ref: dict) -> bool:
        row = rows.get(ref["chunk_id"])
        return row is None or row["text_sha256"] != ref["text_sha256"]

    evidence, by_chunk = [], {}
    for ref in refs:
        row = rows.get(ref["chunk_id"])
        item = {
            "alias": ref.get("alias"), "chunk_id": ref["chunk_id"], "paper_id": row and row["paper_id"],
            "source_title": row and row["source_title"], "section_title": row and row["section_title"],
            "section_type": row and row["section_type"], "page_start": row and row["page_start"],
            "page_end": row and row["page_end"], "text": row and row["text"], "similarity": ref["similarity"],
            "cited": ref["chunk_id"] in cited, "possible_injection": bool(row and row["possible_injection"]),
            "excluded_reason": ref.get("excluded_reason"), "stale": stale(ref)}
        evidence.append(item)
        by_chunk[ref["chunk_id"]] = item
    citations = []
    for c in stored.get("citations", []):
        meta = by_chunk.get(c["chunk_id"], {})
        citations.append({
            "citation_id": c["chunk_id"], "alias": c["alias"], "chunk_id": c["chunk_id"], "paper_id": meta.get("paper_id"),
            "source_title": meta.get("source_title"), "section_title": meta.get("section_title"),
            "page_start": meta.get("page_start"), "page_end": meta.get("page_end"), "quote": c["quote"],
            "verified": c["verified"], "stale": meta.get("stale", True)})
    return {
        "request_id": request_id, "session_id": message["session_id"], "message_id": message["message_id"],
        "user_message_id": message.get("user_message_id"), "created_at": message["created_at"], "mode": message["mode"],
        "no_evidence": stored["no_evidence"], "content": message["content"], "sections": stored["sections"],
        "citations": citations, "evidence": evidence, "unsupported_claims": stored["unsupported_claims"],
        "conflicting_evidence": stored["conflicting_evidence"], "limitations": stored["limitations"],
        "safety": stored["safety"], "generation": generation, "trace": stored["trace"]}


def attach_answers(db: Session, messages: list[dict]) -> list[dict]:
    """For GET messages: adds `answer` to assistant rows that carry a stored response (one chunk query for the page)."""
    ids = sorted({r["chunk_id"] for m in messages if m.get("response") for r in m["response"].get("evidence", [])})
    rows = repo.chunk_rows(db, ids)
    out = []
    for message in messages:
        message = dict(message)
        stored = message.pop("response", None)
        generation = message.pop("generation", None)
        message["answer"] = build_reply(db, {**message, "response": stored, "generation": generation}, rows=rows) if stored else None
        out.append(message)
    return out


# ---------------------------------------------------------------- the pipeline

def _evidence_from_search(results: list[dict]) -> list[EvidenceItem]:
    return [EvidenceItem(
        chunk_id=r["chunk_id"], paper_id=r["paper_id"], title=r["title"], section_title=r["section_title"],
        section_type=r["section_type"], page_start=r["page_start"], page_end=r["page_end"], text=r["text"],
        similarity=r["similarity"], possible_injection=r["possible_injection"],
        text_sha256=r.get("text_sha256", "")) for r in results]


def _request_hash(session_id: UUID, mode: str, content: str) -> str:
    body = json.dumps({"session": str(session_id), "mode": mode, "content": content}, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def post_message(db: Session, pipeline: Pipeline, *, user: AuthUser, session_id: UUID, content: str, mode: str,
                 idempotency_key: str | None, request_id: str, commit: bool = True) -> tuple[dict, bool]:
    """Answers one question and stores the turn. Returns (reply, replayed). With commit=False the caller owns the
    transaction (the evaluation script rolls everything back)."""
    started = time.perf_counter()
    outcome = "error"
    llm_called, tokens = False, (0, 0)
    try:
        session = sessions_repo.get_session(db, user.id, session_id)
        if session is None:
            raise not_found("Chat session was not found.")  # also for another user's session
        request_hash = _request_hash(session_id, mode, content)

        if idempotency_key:
            repo.lock_key(db, session_id, idempotency_key)
            existing = repo.find_by_key(db, session_id, idempotency_key)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ApiError(409, "idempotency_conflict",
                                   "This Idempotency-Key was already used with a different request.")
                outcome = "replayed"
                return build_reply(db, existing, request_id), True

        profile = patients_repo.get_profile(db, session["patient_id"])
        screen = safety.screen_question(content)

        if pipeline.limiter is not None:
            wait = pipeline.limiter.check(str(user.id))
            if wait is not None:
                outcome = "rate_limited"
                raise ApiError(429, "rate_limited", "Too many questions. Please wait a moment and try again.",
                               headers={"Retry-After": str(wait)})

        trace: list[dict] = []
        evidence: list[EvidenceItem] = []
        sections: list[dict] = []
        validated = None
        no_evidence = False
        flags: list[str] = []
        generation: dict = {"llm_called": False}
        conflicts: list[str] = []
        limitations = ""
        model_escalation = False

        if screen.personal:
            # A first-person crisis statement: no retrieval and no generated answer, only the fixed notice.
            flags.append("personal_crisis_no_answer")
            trace.append({"type": "safety", "label": "Risk screen triggered", "detail": "fixed notice shown; no answer generated"})
            content_out = safety.ESCALATION_NOTICE
            outcome = "crisis_notice"
        else:
            if mode in ("rag", "both"):
                t0 = time.perf_counter()
                found = retrieval_service.search(
                    db, pipeline.embedder_provider, query=content, top_k=pipeline.settings.answer_top_k, paper_id=None,
                    min_similarity=pipeline.settings.retrieval_min_similarity)
                evidence = _evidence_from_search(found["results"])
                trace.append({"type": "retrieval", "label": "Chunks retrieved" if evidence else "No chunks above the threshold",
                              "detail": f"{len(evidence)} chunk(s)", "latency_ms": round((time.perf_counter() - t0) * 1000)})
                no_evidence = not evidence

            if no_evidence:
                flags.append("no_evidence")
                content_out = NO_EVIDENCE_TEXT
                outcome = "no_evidence"
            else:
                prompts.assign_aliases(evidence)
                history = repo.recent_turns(db, session_id, prompts.HISTORY_TURNS * 2)
                build = prompts.build_messages(
                    mode=mode, profile=profile, evidence=evidence, history=history, question=content,
                    budget_tokens=pipeline.llm_settings.context_token_budget)
                t1 = time.perf_counter()
                answer, usage = _generate(pipeline, build.messages)
                llm_ms = round((time.perf_counter() - t1) * 1000)
                llm_called, tokens = True, (usage["prompt_tokens"], usage["completion_tokens"])
                validated = validate_answer(answer, mode, evidence)
                flags.extend(validated.flags)
                sections, conflicts, limitations = validated.sections, validated.conflicting_evidence, validated.limitations
                model_escalation = answer.escalation_needed
                content_out = validated.content
                generation = {
                    "llm_called": True, "model": usage["model"], "prompt_version": prompts.PROMPT_VERSION,
                    "latency_ms": llm_ms, "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                    "retries": usage["retries"], "repair_attempted": usage["repair_attempted"],
                    "temperature": pipeline.llm_settings.temperature, "max_tokens": pipeline.llm_settings.max_output_tokens,
                    "estimated_context_tokens": build.estimated_tokens, "history_turns_used": build.history_turns_used}
                trace.append({"type": "generation", "label": "Answer generated", "detail":
                              f"{usage['prompt_tokens']} prompt / {usage['completion_tokens']} completion tokens", "latency_ms": llm_ms})
                verified = sum(c["verified"] for c in validated.citations)
                trace.append({"type": "validation", "label": "Citations validated",
                              "detail": f"{verified} of {len(validated.citations)} quote(s) verified; "
                                        f"{len(validated.unsupported_claims)} unsupported claim(s)"})
                outcome = "answered"

        escalation = screen.triggered or model_escalation
        if escalation and not screen.personal:
            trace.append({"type": "safety", "label": "Safety notice added", "detail": "risk cues in the question or the answer"})
        cited_ids = {c["chunk_id"] for c in (validated.citations if validated else [])}
        stored = {
            "v": RESPONSE_VERSION, "mode": mode, "no_evidence": no_evidence, "sections": sections,
            "citations": validated.citations if validated else [],
            "unsupported_claims": validated.unsupported_claims if validated else [],
            "conflicting_evidence": conflicts, "limitations": limitations,
            "safety": {"escalation": escalation, "notice": safety.ESCALATION_NOTICE if escalation else None, "flags": flags},
            "evidence": [{"alias": e.alias, "chunk_id": e.chunk_id, "text_sha256": e.text_sha256, "similarity": e.similarity,
                          "excluded_reason": e.excluded_reason} for e in evidence],
            "trace": trace,
        }
        for ref, item in zip(stored["evidence"], evidence):
            ref["cited"] = item.chunk_id in cited_ids
        message = repo.insert_turn(db, session_id=session_id, mode=mode, question=content, answer_content=content_out,
                                   response=stored, generation=generation, key=idempotency_key, request_hash=request_hash)
        reply = build_reply(db, message, request_id)
        if commit:
            db.commit()
        return reply, False
    except ApiError as error:
        outcome = error.code
        raise
    finally:
        logger.info("answer request=%s user=%s mode=%s outcome=%s llm_called=%s prompt_tokens=%d completion_tokens=%d latency_ms=%d",
                    request_id, user.id, mode, outcome, llm_called, tokens[0], tokens[1], round((time.perf_counter() - started) * 1000))
