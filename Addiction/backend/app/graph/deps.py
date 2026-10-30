"""Dependencies of a run. They travel in the LangGraph config (config["configurable"]["deps"]), never in the state, so
the state never holds a key, a token or a database session."""
import time
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from app.errors import ApiError
from app.llm.base import BaseLLMClient
from app.retrieval.embedder import EmbedderProvider

FAST_NODE_SECONDS = 5.0  # the deterministic nodes do no I/O: a budget this small only catches a hang


@dataclass
class GraphDeps:
    settings: object  # app.config.Settings
    llm: BaseLLMClient
    embedder_provider: EmbedderProvider
    engine: Engine
    deadline: float  # time.monotonic() value at which the whole workflow must be finished
    request_id: str | None = None
    node_timeouts: dict[str, float] = field(default_factory=dict)
    # Trace events of the nodes as they finish (plus an error event for a node that failed), so a failed run still has
    # its partial trace for the audit log. The same objects the stored execution_trace is made from.
    collected: list = field(default_factory=list)

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def timeout_for(self, node: str) -> float:
        """The node's own budget, never more than what is left of the whole workflow's time."""
        return max(0.0, min(self.node_timeouts.get(node, FAST_NODE_SECONDS), self.remaining()))


def workflow_timeout() -> ApiError:
    return ApiError(504, "workflow_timeout", "The answer took too long to prepare. Please try again.")
