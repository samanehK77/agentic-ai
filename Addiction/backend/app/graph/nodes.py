"""The ten nodes. Each takes (state, deps) and returns a PARTIAL state update that includes one execution-trace event.
They reuse the Batch 07 components (safety screen, retrieval service, prompt builder, generation with one repair,
answer validator). Nodes never write to the database: the service stores the final result."""
import logging
import time

from sqlalchemy.orm import Session

from app.answers.generate import generate
from app.errors import ApiError
from app.graph import assessment
from app.graph.classifier import UNSUPPORTED, Classifier
from app.graph.deps import GraphDeps
from app.graph.routing import HISTORY_REASON, NO_EVIDENCE_TEXT, UNSUPPORTED_TEXT, decide
from app.graph.state import GraphState
from app.graph.trace import NODE_ORDER, Stopwatch, ordered
from app.graph.version import GRAPH_VERSION
from app.llm import prompt as prompts
from app.llm import safety
from app.llm.validate import EvidenceItem, validate_answer
from app.retrieval import service as retrieval_service

logger = logging.getLogger("mindevidence.graph")

RESPONSE_VERSION = 1
MODES = ("general_knowledge", "rag", "both")
QUESTION_LIMIT = 1000


def _evidence_from_search(results: list[dict]) -> list[EvidenceItem]:
    return [EvidenceItem(
        chunk_id=r["chunk_id"], paper_id=r["paper_id"], title=r["title"], section_title=r["section_title"],
        section_type=r["section_type"], page_start=r["page_start"], page_end=r["page_end"], text=r["text"],
        similarity=r["similarity"], possible_injection=r["possible_injection"],
        text_sha256=r.get("text_sha256", "")) for r in results]


# ---------------------------------------------------------------- 1. validate_inputs

def validate_inputs(state: GraphState, deps: GraphDeps) -> dict:
    """The service has already checked ownership and read the patient record (short database phase before the run);
    this node checks that the run starts from a complete, valid input."""
    sw = Stopwatch()
    question = state.question
    if not question.strip() or len(question) > QUESTION_LIMIT:
        raise ApiError(422, "invalid_input", "The question must be 1 to 1000 characters.")
    if state.mode not in MODES:
        raise ApiError(422, "invalid_input", "Unknown mode.")
    if not state.patient_profile:
        raise ApiError(404, "not_found", "Patient was not found.")
    return {"execution_trace": [sw.event(
        "validate_inputs", request_id=state.request_id, reason_code="inputs_valid",
        reason="Question, mode and patient record are present.", counts={"question_chars": len(question)})]}


# ---------------------------------------------------------------- 2. safety_screen

def safety_screen(state: GraphState, deps: GraphDeps) -> dict:
    sw = Stopwatch()
    screen = safety.screen_question(state.question)
    info = {"triggered": screen.triggered, "personal": screen.personal, "escalation": False, "flags": []}
    if screen.personal:
        # A first-person crisis statement: no retrieval and no generated answer, only the fixed notice.
        return {
            "safety": info, "flags": ["personal_crisis_no_answer"],
            "termination": {"reason_code": "crisis_notice", "message": safety.ESCALATION_NOTICE},
            "user_trace": [{"type": "safety", "label": "Risk screen triggered", "detail": "fixed notice shown; no answer generated"}],
            "execution_trace": [sw.event(
                "safety_screen", "ended", request_id=state.request_id, reason_code="crisis_notice",
                reason="First-person risk statement: only the fixed safety notice is shown.", counts={"risk_cues": 1})]}
    return {"safety": info, "execution_trace": [sw.event(
        "safety_screen", request_id=state.request_id, reason_code="risk_cues" if screen.triggered else "no_risk_cues",
        reason="Risk cues found: a safety notice will be added." if screen.triggered else "No risk cues in the question.",
        counts={"risk_cues": len(screen.matched)})]}


# ---------------------------------------------------------------- 3. classify_intent

def make_classify_intent(classifier: Classifier):
    def classify_intent(state: GraphState, deps: GraphDeps) -> dict:
        sw = Stopwatch()
        result = classifier.classify(state.question, state.patient_id)
        update = {"classification": {"label": result.label, "reason_code": result.reason_code}}
        if result.label == UNSUPPORTED:
            update["termination"] = {"reason_code": "unsupported_request", "message": UNSUPPORTED_TEXT}
            update["flags"] = ["unsupported_request"]
            update["execution_trace"] = [sw.event(
                "classify_intent", "ended", request_id=state.request_id, reason_code=result.reason_code,
                reason="The request is outside what this tool does (see the reason code): no retrieval and no model call.")]
        else:
            update["execution_trace"] = [sw.event(
                "classify_intent", request_id=state.request_id, reason_code=result.reason_code,
                reason=f"Classified as {result.label}.")]
        return update

    return classify_intent


# ---------------------------------------------------------------- 4. decide_retrieval

def decide_retrieval(state: GraphState, deps: GraphDeps) -> dict:
    sw = Stopwatch()
    c = state.classification
    decision = decide(state.mode, c["label"], c["reason_code"])
    return {"retrieval_decision": decision, "execution_trace": [sw.event(
        "decide_retrieval", request_id=state.request_id, reason_code=decision["reason_code"], reason=decision["reason"],
        counts={"retrieval_needed": decision["needed"]})]}


# ---------------------------------------------------------------- 5. execute_retrieval

def execute_retrieval(state: GraphState, deps: GraphDeps) -> dict:
    sw = Stopwatch()
    query = state.retrieval_query or state.question
    settings = deps.settings
    with Session(deps.engine) as db:  # its own short read-only session: no connection is held between nodes
        found = retrieval_service.search(
            db, deps.embedder_provider, query=query, top_k=settings.answer_top_k, paper_id=None,
            min_similarity=settings.retrieval_min_similarity)
    evidence = _evidence_from_search(found["results"])
    attempt = state.attempts + 1
    event = sw.event(
        "execute_retrieval", request_id=state.request_id, reason_code="retrieval_done" if attempt == 1 else "retrieval_retry_done",
        reason="Documents searched." if attempt == 1 else "Documents searched again with the previous question added.",
        counts={"chunks": len(evidence), "attempt": attempt}, chunk_ids=[e.chunk_id for e in evidence])
    return {"evidence": evidence, "attempts": attempt, "execution_trace": [event], "user_trace": [{
        "type": "retrieval", "label": "Chunks retrieved" if evidence else "No chunks above the threshold",
        "detail": f"{len(evidence)} chunk(s)", "latency_ms": event["duration_ms"]}]}


# ---------------------------------------------------------------- 6. assess_evidence

def assess_evidence(state: GraphState, deps: GraphDeps) -> dict:
    sw = Stopwatch()
    result = assessment.assess(state.evidence)
    result["retry_follow_up"] = False
    if not result["sufficient"] and state.attempts < assessment.MAX_RETRIEVALS and assessment.is_follow_up(state.question):
        previous = assessment.previous_user_turn(state.history)
        if previous:
            result["retry_follow_up"] = True
            return {"evidence_assessment": result, "retrieval_query": assessment.enrich_query(previous, state.question),
                    "execution_trace": [sw.event(
                        "assess_evidence", request_id=state.request_id, reason_code="insufficient_retry_follow_up",
                        reason="No usable evidence for a short follow-up question: one more search with the previous question added.",
                        counts={"retrieved": result["retrieved"], "usable": result["usable"]})]}
    counts = {"retrieved": result["retrieved"], "usable": result["usable"], "top_similarity": result["top_similarity"]}
    if not result["sufficient"]:
        return {"evidence_assessment": result, "flags": ["no_evidence"],
                "termination": {"reason_code": "no_evidence", "message": NO_EVIDENCE_TEXT},
                "execution_trace": [sw.event(
                    "assess_evidence", "ended", request_id=state.request_id, reason_code="no_evidence",
                    reason="No usable evidence: no research-based answer is generated and the model is not called.", counts=counts)]}
    return {"evidence_assessment": result, "execution_trace": [sw.event(
        "assess_evidence", request_id=state.request_id, reason_code=result["reason_code"],
        reason=f"Evidence level: {result['level']}.", counts=counts)]}


# ---------------------------------------------------------------- 7. generate_answer

def generate_answer(state: GraphState, deps: GraphDeps) -> dict:
    sw = Stopwatch()
    settings = deps.settings
    llm_settings = settings.llm
    evidence = state.evidence
    prompts.assign_aliases(evidence)
    facts_only = bool(state.retrieval_decision) and state.retrieval_decision["reason_code"] == HISTORY_REASON
    build = prompts.build_messages(
        mode=state.mode, profile=state.patient_profile, evidence=evidence, history=state.history, question=state.question,
        budget_tokens=llm_settings.context_token_budget, patient_facts_only=facts_only)
    t_call = time.perf_counter()
    answer, usage = generate(deps.llm, build.messages, timeout=deps.remaining())
    latency = round((time.perf_counter() - t_call) * 1000)
    generation = {
        "llm_called": True, "model": usage["model"], "prompt_version": prompts.PROMPT_VERSION, "latency_ms": latency,
        "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"], "retries": usage["retries"],
        "repair_attempted": usage["repair_attempted"], "temperature": llm_settings.temperature,
        "max_tokens": llm_settings.max_output_tokens, "estimated_context_tokens": build.estimated_tokens,
        "history_turns_used": build.history_turns_used}
    event = sw.event(
        "generate_answer", request_id=state.request_id, reason_code="answer_generated",
        reason="The model wrote a structured answer.",
        counts={"prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                "retries": usage["retries"], "repair_attempted": usage["repair_attempted"],
                "chunks_in_prompt": sum(1 for e in evidence if e.alias)},
        chunk_ids=[e.chunk_id for e in evidence if e.alias])
    return {"evidence": evidence, "raw_answer": answer, "generation": generation, "model_escalation": answer.escalation_needed,
            "execution_trace": [event], "user_trace": [{
                "type": "generation", "label": "Answer generated",
                "detail": f"{usage['prompt_tokens']} prompt / {usage['completion_tokens']} completion tokens", "latency_ms": latency}]}


# ---------------------------------------------------------------- 8. validate_citations

def validate_citations(state: GraphState, deps: GraphDeps) -> dict:
    sw = Stopwatch()
    validated = validate_answer(state.raw_answer, state.mode, state.evidence)
    verified = sum(c["verified"] for c in validated.citations)
    total = len(validated.citations)
    info = {"valid": verified == total and "unknown_alias_dropped" not in validated.flags
            and "unsupported_research_claim" not in validated.flags,
            "citations": total, "verified": verified, "unverified": total - verified,
            "unknown_aliases_dropped": "unknown_alias_dropped" in validated.flags,
            "unsupported_claims": len(validated.unsupported_claims)}
    return {"validated": validated, "citation_validation": info, "flags": list(validated.flags),
            "execution_trace": [sw.event(
                "validate_citations", request_id=state.request_id, reason_code="citations_checked",
                reason="Citations were mapped to the shown chunks and every quote was checked against its chunk.",
                counts={"citations": total, "verified": verified, "unsupported_claims": len(validated.unsupported_claims),
                        "sections": len(validated.sections)})],
            "user_trace": [{"type": "validation", "label": "Citations validated",
                            "detail": f"{verified} of {total} quote(s) verified; {len(validated.unsupported_claims)} unsupported claim(s)"}]}


# ---------------------------------------------------------------- 9. safety_check

def safety_check(state: GraphState, deps: GraphDeps) -> dict:
    """The answer validator has already withheld sections with dosing instructions or treatment directives; this node
    decides the escalation notice (risk cues in the question, or the model's own flag) and records what was withheld."""
    sw = Stopwatch()
    withheld = sum(1 for s in state.validated.sections if s["kind"] == "withheld")
    escalation = bool(state.safety["triggered"] or state.model_escalation)
    safety_info = {**state.safety, "escalation": escalation}
    return {"safety": safety_info, "execution_trace": [sw.event(
        "safety_check", request_id=state.request_id, reason_code="escalation_notice" if escalation else "output_checked",
        reason="A safety notice is added to the answer." if escalation else "Dosing and directive checks were applied to the answer.",
        counts={"withheld_sections": withheld, "escalation": escalation})]}


# ---------------------------------------------------------------- 10. format_output

def _skip_reasons(state: GraphState) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    if state.termination:
        for node in NODE_ORDER:
            out[node] = (state.termination["reason_code"], "The run ended before this step.")
    decision = state.retrieval_decision
    if decision and not decision["needed"]:
        out["execute_retrieval"] = out["assess_evidence"] = (decision["reason_code"], decision["reason"])
    return out


def format_output(state: GraphState, deps: GraphDeps) -> dict:
    """Assembles the stored response, the message text, the generation record and the complete execution trace
    (executed nodes in order, plus an explicit 'skipped' entry for every node that did not run)."""
    sw = Stopwatch()
    validated, termination = state.validated, state.termination
    evidence: list[EvidenceItem] = state.evidence  # empty unless documents were retrieved
    if validated is None:
        prompts.assign_aliases(evidence)  # retrieved but unused chunks (for example flagged ones) are listed with their reason
    escalation = bool(state.safety["triggered"] or state.model_escalation)
    user_trace = list(state.user_trace)
    if escalation and not state.safety["personal"]:
        user_trace.append({"type": "safety", "label": "Safety notice added", "detail": "risk cues in the question or the answer"})
    if validated is not None:
        content_out, outcome = validated.content, "answered"
    else:
        content_out, outcome = termination["message"], termination["reason_code"]
    no_evidence = bool(termination and termination["reason_code"] == "no_evidence")
    cited = {c["chunk_id"] for c in (validated.citations if validated else [])}
    stored = {
        "v": RESPONSE_VERSION, "mode": state.mode, "no_evidence": no_evidence,
        "sections": validated.sections if validated else [], "citations": validated.citations if validated else [],
        "unsupported_claims": validated.unsupported_claims if validated else [],
        "conflicting_evidence": validated.conflicting_evidence if validated else [],
        "limitations": validated.limitations if validated else "",
        "safety": {"escalation": escalation, "notice": safety.ESCALATION_NOTICE if escalation else None, "flags": list(state.flags)},
        "evidence": [{"alias": e.alias, "chunk_id": e.chunk_id, "text_sha256": e.text_sha256, "similarity": e.similarity,
                      "excluded_reason": e.excluded_reason, "cited": e.chunk_id in cited} for e in evidence],
        "trace": user_trace,
        "classification": state.classification, "retrieval_decision": state.retrieval_decision,
        "evidence_assessment": state.evidence_assessment, "citation_validation": state.citation_validation,
    }
    event = sw.event("format_output", request_id=state.request_id, reason_code=outcome,
                     reason="The response was assembled.", counts={"sections": len(stored["sections"]), "citations": len(stored["citations"])})
    full_trace = ordered(list(state.execution_trace) + [event], state.request_id, _skip_reasons(state))
    generation = state.generation
    return {"result": {
        "stored": stored, "content": content_out, "generation": generation, "execution_trace": full_trace,
        "graph_version": GRAPH_VERSION, "outcome": outcome, "llm_called": bool(generation.get("llm_called")),
        "tokens": (generation.get("prompt_tokens", 0), generation.get("completion_tokens", 0))}}
