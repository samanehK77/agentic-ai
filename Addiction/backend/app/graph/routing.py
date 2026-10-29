"""Routing decisions and fixed texts. The model never chooses a route: everything here is deterministic."""
from app.graph.classifier import HISTORY

NO_EVIDENCE_TEXT = (
    "No supporting evidence was found in the research documents for this question, so no research-based answer is "
    "given. Try rephrasing the question, or switch to General Knowledge mode for an answer that is clearly labelled as "
    "not coming from the documents.")
UNSUPPORTED_TEXT = (
    "This educational tool cannot help with this request: it does not diagnose, prescribe, name doses or choose an "
    "individual treatment, and it only discusses the one synthetic patient of this conversation and the research documents. "
    "Try asking what the research says about an approach, or what the patient record contains.")

HISTORY_REASON = "history_question_answered_from_patient_facts"

_REASONS = {
    "mode_forbids_retrieval": "General Knowledge mode never searches the documents.",
    HISTORY_REASON: "The question is about the patient record, so it is answered from the patient facts without searching the documents.",
    "research_needs_evidence": "The question needs research evidence, so the documents are searched.",
    "uncertain_default_retrieve": "The question type is uncertain, so the documents are searched (safe default).",
}


def decide(mode: str, label: str, reason_code: str) -> dict:
    """The retrieval decision for a classified question (see the routing table in docs/ORCHESTRATION.md)."""
    if mode == "general_knowledge":
        code, needed = "mode_forbids_retrieval", False
    elif label == HISTORY:
        code, needed = HISTORY_REASON, False
    elif reason_code.startswith("uncertain"):
        code, needed = "uncertain_default_retrieve", True
    else:
        code, needed = "research_needs_evidence", True
    return {"needed": needed, "reason_code": code, "reason": _REASONS[code]}


def route_after_safety(state) -> str:
    return "format_output" if state.termination else "classify_intent"


def route_after_classify(state) -> str:
    return "format_output" if state.termination else "decide_retrieval"


def route_after_decision(state) -> str:
    return "execute_retrieval" if state.retrieval_decision["needed"] else "generate_answer"


def route_after_assessment(state) -> str:
    if state.termination:
        return "format_output"
    return "execute_retrieval" if state.evidence_assessment.get("retry_follow_up") else "generate_answer"
