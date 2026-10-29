"""Builds and compiles the answer graph. Compiled ONCE at startup; the compiled graph is stateless, so concurrent runs
share it. No checkpointer: nothing about a run is kept by LangGraph."""
from collections.abc import Callable

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.graph import nodes, routing
from app.graph.classifier import Classifier, RuleClassifier
from app.graph.deps import GraphDeps
from app.graph.guard import run_guarded
from app.graph.state import GraphState

RECURSION_LIMIT = 25  # the longest legitimate path has 12 steps (10 nodes plus one retrieval retry)


def _guarded(name: str, fn: Callable[[GraphState, GraphDeps], dict]):
    def run(state: GraphState, config: RunnableConfig) -> dict:
        deps: GraphDeps = config["configurable"]["deps"]
        return run_guarded(name, deps, lambda: fn(state, deps))

    run.__name__ = name
    return run


def build_graph(classifier: Classifier | None = None):
    graph = StateGraph(GraphState)
    steps = {
        "validate_inputs": nodes.validate_inputs,
        "safety_screen": nodes.safety_screen,
        "classify_intent": nodes.make_classify_intent(classifier or RuleClassifier()),
        "decide_retrieval": nodes.decide_retrieval,
        "execute_retrieval": nodes.execute_retrieval,
        "assess_evidence": nodes.assess_evidence,
        "generate_answer": nodes.generate_answer,
        "validate_citations": nodes.validate_citations,
        "safety_check": nodes.safety_check,
        "format_output": nodes.format_output,
    }
    for name, fn in steps.items():
        graph.add_node(name, _guarded(name, fn))

    graph.add_edge(START, "validate_inputs")
    graph.add_edge("validate_inputs", "safety_screen")
    graph.add_conditional_edges("safety_screen", routing.route_after_safety,
                                {"classify_intent": "classify_intent", "format_output": "format_output"})
    graph.add_conditional_edges("classify_intent", routing.route_after_classify,
                                {"decide_retrieval": "decide_retrieval", "format_output": "format_output"})
    graph.add_conditional_edges("decide_retrieval", routing.route_after_decision,
                                {"execute_retrieval": "execute_retrieval", "generate_answer": "generate_answer"})
    graph.add_edge("execute_retrieval", "assess_evidence")
    graph.add_conditional_edges("assess_evidence", routing.route_after_assessment,
                                {"execute_retrieval": "execute_retrieval", "generate_answer": "generate_answer",
                                 "format_output": "format_output"})
    graph.add_edge("generate_answer", "validate_citations")
    graph.add_edge("validate_citations", "safety_check")
    graph.add_edge("safety_check", "format_output")
    graph.add_edge("format_output", END)
    return graph.compile()  # no checkpointer, no store


def run_config(deps: GraphDeps) -> dict:
    return {"recursion_limit": RECURSION_LIMIT, "configurable": {"deps": deps}}
