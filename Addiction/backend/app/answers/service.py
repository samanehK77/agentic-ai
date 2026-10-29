"""The answer service: three SHORT database phases around the LangGraph workflow (app/graph).

  A. one short transaction: ownership (404), idempotency lookup (replay), patient record, recent turns, rate limit.
     The connection is then released.
  B. the workflow runs with NO database connection held (the retrieval node opens its own short read-only session).
     The model call can take minutes, so no transaction and no advisory lock may stay open meanwhile.
  C. one short transaction: re-check the key, insert the user and the assistant message, commit.

Nothing is stored unless the whole run succeeded. A double submit with the same Idempotency-Key is serialized by an
in-process keyed lock (app/answers/locks.py) with the unique index as the backstop. The model writes; this code decides
what is retrieved, what is sent, what is accepted and what is stored."""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.answers.locks import KeyedLocks
from app.auth_service import AuthUser
from app.errors import ApiError, not_found
from app.graph import build_graph
from app.graph.build import run_config
from app.graph.deps import GraphDeps
from app.graph.nodes import RESPONSE_VERSION  # noqa: F401  (re-exported: the stored response format version)
from app.graph.routing import NO_EVIDENCE_TEXT  # noqa: F401  (re-exported for callers and tests)
from app.llm import prompt as prompts
from app.llm.base import BaseLLMClient
from app.llm.config import LLMSettings
from app.repositories import answers as repo
from app.repositories import patients as patients_repo
from app.repositories import sessions as sessions_repo
from app.retrieval.embedder import EmbedderProvider
from app.retrieval.ratelimit import SlidingWindowLimiter

logger = logging.getLogger("mindevidence.answers")


@lru_cache(maxsize=1)
def default_graph():
    return build_graph()


@dataclass
class Pipeline:
    """Everything the pipeline needs from the application (settings, clients, limiter, the compiled graph)."""

    settings: "object"  # app.config.Settings
    llm: BaseLLMClient
    embedder_provider: EmbedderProvider
    limiter: SlidingWindowLimiter | None = None
    graph: object = None
    locks: KeyedLocks = field(default_factory=KeyedLocks)

    def __post_init__(self):
        if self.graph is None:
            self.graph = default_graph()

    @property
    def llm_settings(self) -> LLMSettings:
        return self.settings.llm


@dataclass
class Replay:
    """The stored reply of an earlier request with the same Idempotency-Key and body."""

    reply: dict


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
        "safety": stored["safety"], "generation": generation, "trace": stored["trace"],
        # Batch 08 (additive; null for answers stored before the graph existed)
        "classification": stored.get("classification"), "retrieval_decision": stored.get("retrieval_decision"),
        "evidence_assessment": stored.get("evidence_assessment"), "execution_trace": message.get("trace"),
        "graph_version": message.get("graph_version")}


def attach_answers(db: Session, messages: list[dict]) -> list[dict]:
    """For GET messages: adds `answer` to assistant rows that carry a stored response (one chunk query for the page)."""
    ids = sorted({r["chunk_id"] for m in messages if m.get("response") for r in m["response"].get("evidence", [])})
    rows = repo.chunk_rows(db, ids)
    out = []
    for message in messages:
        message = dict(message)
        stored = message.pop("response", None)
        generation = message.pop("generation", None)
        trace = message.pop("trace", None)
        graph_version = message.pop("graph_version", None)
        message["answer"] = build_reply(
            db, {**message, "response": stored, "generation": generation, "trace": trace, "graph_version": graph_version},
            rows=rows) if stored else None
        out.append(message)
    return out


def get_execution_trace(db: Session, user: AuthUser, session_id: UUID, message_id: UUID) -> dict:
    """The stored execution trace of an assistant message. Another user's session, an unknown message and a user message
    all look the same: 404."""
    if sessions_repo.get_session(db, user.id, session_id) is None:
        raise not_found("Chat session was not found.")
    row = repo.get_trace(db, session_id, message_id)
    if row is None:
        raise not_found("Message was not found.")
    return {"message_id": row["message_id"], "graph_version": row["graph_version"], "execution_trace": row["trace"] or []}


# ---------------------------------------------------------------- the pipeline

def _request_hash(session_id: UUID, mode: str, content: str) -> str:
    body = json.dumps({"session": str(session_id), "mode": mode, "content": content}, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay(db: Session, existing: dict, request_hash: str, request_id: str) -> dict:
    if existing["request_hash"] != request_hash:
        raise ApiError(409, "idempotency_conflict", "This Idempotency-Key was already used with a different request.")
    return build_reply(db, existing, request_id)


def post_message(db: Session, pipeline: Pipeline, *, user: AuthUser, session_id: UUID, content: str, mode: str,
                 idempotency_key: str | None, request_id: str) -> tuple[dict, bool]:
    """Answers one question and stores the turn. Returns (reply, replayed)."""
    started = time.perf_counter()
    outcome = "error"
    llm_called, tokens = False, (0, 0)
    request_hash = _request_hash(session_id, mode, content)
    try:
        if idempotency_key:
            with pipeline.locks.hold(f"{session_id}:{idempotency_key}"):
                reply, replayed, outcome, llm_called, tokens = _run(
                    db, pipeline, user, session_id, content, mode, idempotency_key, request_id, request_hash)
        else:
            reply, replayed, outcome, llm_called, tokens = _run(
                db, pipeline, user, session_id, content, mode, None, request_id, request_hash)
        return reply, replayed
    except ApiError as error:
        outcome = error.code
        raise
    finally:
        logger.info("answer request=%s user=%s mode=%s outcome=%s llm_called=%s prompt_tokens=%d completion_tokens=%d latency_ms=%d",
                    request_id, user.id, mode, outcome, llm_called, tokens[0], tokens[1], round((time.perf_counter() - started) * 1000))


def _run(db: Session, pipeline: Pipeline, user: AuthUser, session_id: UUID, content: str, mode: str,
         key: str | None, request_id: str, request_hash: str):
    settings = pipeline.settings
    # ---- phase A: a short read-only transaction
    session = sessions_repo.get_session(db, user.id, session_id)
    if session is None:
        raise not_found("Chat session was not found.")  # also for another user's session
    if key:
        existing = repo.find_by_key(db, session_id, key)
        if existing:
            reply = _replay(db, existing, request_hash, request_id)
            return reply, True, "replayed", False, (0, 0)
    profile = patients_repo.get_profile(db, session["patient_id"])
    history = repo.recent_turns(db, session_id, prompts.HISTORY_TURNS * 2)
    if pipeline.limiter is not None:
        wait = pipeline.limiter.check(str(user.id))
        if wait is not None:
            raise ApiError(429, "rate_limited", "Too many questions. Please wait a moment and try again.",
                           headers={"Retry-After": str(wait)})
    engine = db.get_bind()
    db.rollback()  # releases the pooled connection: nothing is held open during the run

    # ---- phase B: the workflow (no connection held)
    total = settings.graph_total_timeout_seconds
    deps = GraphDeps(
        settings=settings, llm=pipeline.llm, embedder_provider=pipeline.embedder_provider, engine=engine,
        deadline=time.monotonic() + total, request_id=request_id,
        node_timeouts={"execute_retrieval": settings.graph_retrieval_timeout_seconds, "generate_answer": total})
    state = {"user_id": str(user.id), "session_id": str(session_id), "patient_id": session["patient_id"], "mode": mode,
             "question": content, "request_id": request_id, "patient_profile": profile, "history": history}
    final = pipeline.graph.invoke(state, config=run_config(deps))
    result = final["result"] if isinstance(final, dict) else final.result

    # ---- phase C: one short transaction
    try:
        if key:
            existing = repo.find_by_key(db, session_id, key)  # another process may have finished meanwhile
            if existing:
                return _replay(db, existing, request_hash, request_id), True, "replayed", result["llm_called"], result["tokens"]
        message = repo.insert_turn(
            db, session_id=session_id, mode=mode, question=content, answer_content=result["content"], response=result["stored"],
            generation=result["generation"], key=key, request_hash=request_hash, trace=result["execution_trace"],
            graph_version=result["graph_version"])
        reply = build_reply(db, message, request_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = repo.find_by_key(db, session_id, key) if key else None
        if existing is None:
            raise
        return _replay(db, existing, request_hash, request_id), True, "replayed", result["llm_called"], result["tokens"]
    return reply, False, result["outcome"], result["llm_called"], result["tokens"]
