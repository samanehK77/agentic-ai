"""Turns the audit rows of one session into question groups for the activity timeline. Pure functions: no SQL, no HTTP."""
from datetime import datetime, timedelta, timezone

QUESTION_START = "question_submitted"
CONFIG_KEYS = ("config_fingerprint", "model", "prompt_version", "retrieval_threshold", "top_k", "embedding_model",
               "embedding_fingerprint", "chunking_version")
INTERRUPTED_AFTER = timedelta(minutes=10)  # longer than the workflow time limit: the server must have stopped meanwhile


def event_out(row: dict) -> dict:
    return {"event_id": row["event_id"], "event_type": row["event_type"], "outcome": row["outcome"],
            "occurred_at": row["occurred_at"], "latency_ms": row["latency_ms"], "error_code": row["error_code"],
            "seq": row["seq"], "metadata": row["metadata"]}


def group_out(events: list[dict], now: datetime | None = None) -> dict:
    """One correlation group. `outcome` is the result of a question (answered, no_evidence, unsupported, crisis,
    replayed), `error`, `running` / `interrupted` (no final event yet), or `ok` / `denied` for a single action."""
    now = now or datetime.now(timezone.utc)
    by_type = {}
    for row in events:
        by_type.setdefault(row["event_type"], row)
    first = events[0]
    submitted = by_type.get(QUESTION_START)
    error, answer = by_type.get("pipeline_error"), by_type.get("answer_returned")
    error_code, total = None, None
    if submitted is None:
        kind, outcome = "action", first["outcome"]
        error_code = first["error_code"]
    else:
        kind = "question"
        if error is not None:
            outcome, error_code, total = "error", error["error_code"], error["latency_ms"]
        elif answer is not None:
            meta = answer["metadata"]
            outcome = "replayed" if meta.get("replayed") else meta.get("result", "answered")
            total = answer["latency_ms"]
        elif now - submitted["occurred_at"] > INTERRUPTED_AFTER:
            outcome = "interrupted"
        else:
            outcome = "running"
    config = {k: v for k, v in (submitted["metadata"].items() if submitted else []) if k in CONFIG_KEYS}
    return {"correlation_id": first["correlation_id"], "kind": kind, "outcome": outcome, "error_code": error_code,
            "total_latency_ms": total, "started_at": first["occurred_at"], "config": config or None,
            "events": [event_out(row) for row in events]}


def build_groups(correlation_ids: list, rows: list[dict], now: datetime | None = None) -> list[dict]:
    """Groups in the order of `correlation_ids` (newest first); events inside a group in the order they happened."""
    by_group: dict = {}
    for row in rows:
        by_group.setdefault(row["correlation_id"], []).append(row)
    return [group_out(by_group[cid], now) for cid in correlation_ids if cid in by_group]
