"""Runs one node under its time budget. The total deadline is checked when every node starts. A node that overruns ends
the run with 504 `workflow_timeout` (its worker thread is abandoned: I/O inside it is bounded by its own timeouts)."""
import logging
import threading
from collections.abc import Callable

from app.errors import ApiError
from app.graph.deps import GraphDeps, workflow_timeout

logger = logging.getLogger("mindevidence.graph")


def run_guarded(name: str, deps: GraphDeps, fn: Callable[[], dict]) -> dict:
    if deps.remaining() <= 0:
        logger.warning("workflow deadline passed before node=%s request=%s", name, deps.request_id)
        raise workflow_timeout()
    budget = deps.timeout_for(name)
    outcome: dict = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as error:  # handed to the calling thread unchanged
            outcome["error"] = error

    worker = threading.Thread(target=target, name=f"graph-{name}", daemon=True)
    worker.start()
    worker.join(budget)
    if worker.is_alive():
        logger.warning("node timed out node=%s budget_s=%.1f request=%s", name, budget, deps.request_id)
        raise workflow_timeout()
    if "error" in outcome:
        error = outcome["error"]
        code = error.code if isinstance(error, ApiError) else type(error).__name__
        logger.info("node failed node=%s code=%s request=%s", name, code, deps.request_id)
        raise error
    return outcome["value"]
