"""The answer workflow as an explicit LangGraph state graph (Batch 08). See docs/ORCHESTRATION.md.

No checkpointer and no LangSmith/LangChain tracing: nothing from a run leaves the process, and nothing is persisted by
the graph itself (the service stores the final result and the text-free execution trace).
"""
import os

# Forced off BEFORE langgraph/langchain are imported anywhere: a stray environment variable must not turn on remote tracing.
for _name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGSMITH_TRACING_V2"):
    os.environ[_name] = "false"
os.environ.pop("LANGSMITH_API_KEY", None)
os.environ.pop("LANGCHAIN_API_KEY", None)

from app.graph.version import GRAPH_VERSION  # noqa: E402
from app.graph.build import build_graph  # noqa: E402

__all__ = ["GRAPH_VERSION", "build_graph"]
