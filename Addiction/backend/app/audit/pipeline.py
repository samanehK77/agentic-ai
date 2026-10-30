"""Audit events of one question. The node events are made from the SAME trace objects the workflow produced (the stored
`execution_trace` on success, the nodes' collected events on failure): there is one source of truth, and the audit log
adds the cross-run record that `chat_messages.trace` (a per-message snapshot) cannot give, including failed runs.

Written as: `question_submitted` at once (so a long local run shows as running), everything else in ONE batch when the
run ends, whether it succeeded or failed."""
import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from app.audit.service import AuditService, Event, new_correlation_id, safe_code
from app.errors import ApiError

logger = logging.getLogger("mindevidence.audit")

RESULT_OF_OUTCOME = {"answered": "answered", "no_evidence": "no_evidence", "unsupported_request": "unsupported",
                     "crisis_notice": "crisis"}


def _when(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def events_from_trace(trace: list[dict], *, top_k: int | None, threshold: float | None, config_fingerprint: str | None,
                      model: str | None, evidence_level: str | None, started_at: datetime) -> list[Event]:
    """node_executed for every trace entry, each followed by its derived event (retrieval_executed, llm_request,
    citation_validated). A skipped node takes the time of the entry before it, so the order stays that of the run."""
    out: list[Event] = []
    last_time = started_at
    for entry in trace:
        status, node = entry["status"], entry["node"]
        happened = _when(entry.get("started_at")) or last_time
        last_time = happened
        outcome = "skipped" if status == "skipped" else "error" if status == "error" else "ok"
        counts = {k: v for k, v in (entry.get("counts") or {}).items() if isinstance(v, (int, float, bool))}
        chunk_ids = list(entry.get("chunk_ids") or [])[:20]
        out.append(Event("node_executed", outcome, {
            "node": node, "status": status, "reason_code": safe_code(entry.get("reason_code")),
            "counts": counts, "chunk_ids": chunk_ids},
            latency_ms=None if status == "skipped" else entry.get("duration_ms"), error_code=safe_code(entry.get("error_code")),
            occurred_at=happened))
        if node == "execute_retrieval" and status in ("ok", "error"):
            out.append(Event("retrieval_executed", outcome, {
                "attempt": int(counts.get("attempt", 1)), "top_k": top_k, "threshold": threshold,
                "chunks": int(counts.get("chunks", 0)), "chunk_ids": chunk_ids, "evidence_level": evidence_level},
                latency_ms=entry.get("duration_ms"), error_code=safe_code(entry.get("error_code")), occurred_at=happened))
        elif node == "generate_answer" and status in ("ok", "error"):
            out.append(Event("llm_request", outcome, {
                "model": model, "config_fingerprint": config_fingerprint,
                "prompt_tokens": int(counts.get("prompt_tokens", 0)), "completion_tokens": int(counts.get("completion_tokens", 0)),
                "retries": int(counts.get("retries", 0)), "repair_attempted": bool(counts.get("repair_attempted", False)),
                "status": "ok" if status == "ok" else "error"},
                latency_ms=entry.get("duration_ms"), error_code=safe_code(entry.get("error_code")), occurred_at=happened))
        elif node == "validate_citations" and status == "ok":
            out.append(Event("citation_validated", "ok", {
                "citations": int(counts.get("citations", 0)), "verified": int(counts.get("verified", 0)),
                "unsupported_claims": int(counts.get("unsupported_claims", 0)), "sections": int(counts.get("sections", 0))},
                latency_ms=entry.get("duration_ms"), occurred_at=happened))
    return out


class QuestionAudit:
    """The audit trail of one POST .../messages call. Does nothing when auditing is off; never raises."""

    def __init__(self, audit: AuditService | None, settings, embedder_provider, *, user_id: UUID, session_id: UUID,
                 request_id: str | None):
        self.audit = audit
        self.settings = settings
        self.embedder_provider = embedder_provider
        self.user_id, self.session_id, self.request_id = user_id, session_id, request_id
        self.correlation_id = new_correlation_id()
        self.config: dict = {}
        self.started = time.perf_counter()
        self.started_at = datetime.now(timezone.utc)
        self.active = False  # set once question_submitted was written: earlier refusals are not questions
        self.result: dict | None = None  # the finished workflow's result, when only the storing step failed
        self.collected: list[dict] = []  # filled by the graph wrapper while nodes run (GraphDeps.collected)

    def _write(self, events: list[Event], first_seq: int = 1) -> None:
        self.audit.record_many(events, correlation_id=self.correlation_id, user_id=self.user_id, session_id=self.session_id,
                               request_id=self.request_id, first_seq=first_seq)

    def submitted(self, question_chars: int, mode: str, idempotent: bool) -> None:
        if self.audit is None:
            return
        self.active = True
        try:
            self.config = self.audit.config_snapshot(self.settings, self.embedder_provider)
        except Exception as error:
            logger.warning("audit_config_unavailable error=%s", type(error).__name__)
            self.config = {"config_fingerprint": "unknown"}
        self.audit.record_many(
            [Event("question_submitted", "ok", {"question_chars": question_chars, "mode": mode, "idempotent": idempotent,
                                                **self.config}, occurred_at=self.started_at)],
            correlation_id=self.correlation_id, user_id=self.user_id, session_id=self.session_id, request_id=self.request_id)

    def _total_ms(self) -> int:
        return round((time.perf_counter() - self.started) * 1000)

    def answered(self, result: dict, message_id: str) -> None:
        """A finished run: every node of the stored trace, the derived events and answer_returned."""
        if self.audit is None or not self.active:
            return
        try:
            stored = result["stored"]
            level = (stored.get("evidence_assessment") or {}).get("level")
            events = events_from_trace(
                result["execution_trace"], top_k=self.settings.answer_top_k, threshold=self.settings.retrieval_min_similarity,
                config_fingerprint=self.config.get("config_fingerprint"), model=self.config.get("model"),
                evidence_level=level, started_at=self.started_at)
            events.append(Event("answer_returned", "ok", {
                "result": RESULT_OF_OUTCOME.get(result["outcome"], "answered"), "message_id": str(message_id),
                "classification": safe_code((stored.get("classification") or {}).get("label")),
                "llm_called": bool(result["llm_called"]), "replayed": False}, latency_ms=self._total_ms()))
            self._write(events)
        except Exception as error:
            logger.error("audit_write_failed types=run error=%s", type(error).__name__)
            self.audit._count_failure()

    def replayed(self) -> None:
        if self.audit is not None and self.active:
            self._write([Event("answer_returned", "skipped", {"replayed": True}, latency_ms=self._total_ms())])

    def failed(self, error: BaseException) -> None:
        """A failed run: the nodes that did run (and the one that failed), then pipeline_error with the standard code."""
        if self.audit is None or not self.active:
            return
        try:
            code = error.code if isinstance(error, ApiError) else "internal_error"
            trace = self.result["execution_trace"] if self.result else self.collected
            level = ((self.result or {}).get("stored", {}).get("evidence_assessment") or {}).get("level")
            events = events_from_trace(
                trace, top_k=self.settings.answer_top_k, threshold=self.settings.retrieval_min_similarity,
                config_fingerprint=self.config.get("config_fingerprint"), model=self.config.get("model"),
                evidence_level=level, started_at=self.started_at)
            failed_node = next((e["node"] for e in reversed(self.collected) if e["status"] == "error"), None)
            chunks = next((int((e.get("counts") or {}).get("chunks", 0)) for e in reversed(self.collected)
                           if e["node"] == "execute_retrieval" and e["status"] == "ok"), None)
            events.append(Event("pipeline_error", "error", {"failed_node": safe_code(failed_node), "retrieval_chunks": chunks},
                                latency_ms=self._total_ms(), error_code=safe_code(code)))
            self._write(events)
        except Exception as problem:
            logger.error("audit_write_failed types=run error=%s", type(problem).__name__)
            self.audit._count_failure()
