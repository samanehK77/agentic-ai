"""One entry of the execution trace. STATISTICS ONLY: node name, status, timing, a reason code with a reason written by
this code (never by the model), integer/boolean counts and chunk ids. Never the question, patient text, chunk text,
prompts, answers or model reasoning."""
import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

NODE_ORDER = (
    "validate_inputs", "safety_screen", "classify_intent", "decide_retrieval", "execute_retrieval", "assess_evidence",
    "generate_answer", "validate_citations", "safety_check", "format_output")


class TraceEvent(BaseModel):
    node: str
    status: Literal["ok", "skipped", "ended", "error"]
    started_at: str | None = Field(default=None, description="UTC time the node started (ISO 8601); null for skipped nodes.")
    duration_ms: int = 0
    reason_code: str | None = None
    reason: str = ""
    counts: dict[str, int | float | bool] = Field(default_factory=dict)
    chunk_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    correlation_id: str | None = Field(default=None, description="The request id of the call that ran the workflow.")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Stopwatch:
    """Started when a node starts: remembers the wall-clock start and measures the duration."""

    def __init__(self):
        self.started_at = now_iso()
        self._t0 = time.perf_counter()

    def event(self, node: str, status: str = "ok", *, request_id: str | None = None, reason_code: str | None = None,
              reason: str = "", counts: dict | None = None, chunk_ids: list[str] | None = None,
              error_code: str | None = None) -> dict:
        return TraceEvent(
            node=node, status=status, started_at=self.started_at, duration_ms=round((time.perf_counter() - self._t0) * 1000),
            reason_code=reason_code, reason=reason, counts=counts or {}, chunk_ids=chunk_ids or [], error_code=error_code,
            correlation_id=request_id).model_dump()


def skipped_event(node: str, reason_code: str, reason: str, request_id: str | None) -> dict:
    return TraceEvent(node=node, status="skipped", reason_code=reason_code, reason=reason, correlation_id=request_id).model_dump()


def ordered(events: list[dict], request_id: str | None, skipped_reason: dict[str, tuple[str, str]]) -> list[dict]:
    """The executed events in graph order, with an explicit 'skipped' entry for every node that did not run."""
    out: list[dict] = []
    for node in NODE_ORDER:
        mine = [e for e in events if e["node"] == node]
        if mine:
            out.extend(mine)
        else:
            code, reason = skipped_reason.get(node, ("route_not_taken", "The route of this question did not pass this step."))
            out.append(skipped_event(node, code, reason, request_id))
    return out
