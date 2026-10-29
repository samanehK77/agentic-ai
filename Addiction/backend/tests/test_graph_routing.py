"""Routing of the answer workflow, seen through the API: which nodes ran, which were skipped and why, and how often the
model and the embedder were called. The model is a mock behind the real client; the embedder is the fake one."""
import pytest

from app.graph.routing import NO_EVIDENCE_TEXT, UNSUPPORTED_TEXT
from app.graph.trace import NODE_ORDER
from app.llm.safety import ESCALATION_NOTICE
from tests.answers_helpers import system_text

QUESTION = "alpha question about heavy drinking"


def statuses(body) -> dict[str, str]:
    return {e["node"]: e["status"] for e in body["execution_trace"]}


def events(body, node):
    return [e for e in body["execution_trace"] if e["node"] == node]


def ask_ok(env, content, mode="rag", sid=None):
    response = env.ask(sid or env.new_session(), content, mode)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_research_question_runs_every_node_once_in_graph_order(answer_env, answers_corpus):
    env = answer_env()
    body = ask_ok(env, QUESTION, "rag")
    assert [e["node"] for e in body["execution_trace"]] == list(NODE_ORDER)
    assert set(statuses(body).values()) == {"ok"}
    assert body["classification"]["label"] == "research_question"
    assert body["retrieval_decision"]["needed"] is True and body["retrieval_decision"]["reason_code"] == "uncertain_default_retrieve"
    assert body["evidence_assessment"]["level"] == "adequate" and body["evidence_assessment"]["sufficient"] is True
    retrieval = events(body, "execute_retrieval")[0]
    assert retrieval["counts"]["chunks"] == 3 and retrieval["chunk_ids"][0] == "test-ans-a-c0001"
    assert body["graph_version"] == "graph-v1" and env.provider.count == 1


@pytest.mark.parametrize("mode", ["general_knowledge", "rag", "both"])
@pytest.mark.parametrize("question", [
    "What dose of naltrexone should he take?", "Does this patient have alcohol use disorder?", "Which medication should he take?",
    "Compare P-001 with P-002.", "My brother drinks every day.", "Who will win the football match?"])
def test_unsupported_requests_reach_neither_the_model_nor_the_documents(answer_env, answers_corpus, mode, question):
    env = answer_env()
    body = ask_ok(env, question, mode)
    assert env.provider.count == 0 and env.embedder.calls == []
    assert body["content"] == UNSUPPORTED_TEXT and body["sections"] == [] and body["citations"] == []
    assert body["safety"]["flags"] == ["unsupported_request"] and body["generation"]["llm_called"] is False
    assert body["classification"]["label"] == "unsupported_request"
    got = statuses(body)
    assert got["classify_intent"] == "ended" and got["format_output"] == "ok"
    assert all(got[n] == "skipped" for n in ("decide_retrieval", "execute_retrieval", "assess_evidence", "generate_answer",
                                             "validate_citations", "safety_check"))
    assert events(body, "decide_retrieval")[0]["reason_code"] == "unsupported_request"


def test_a_first_person_crisis_reaches_neither_the_model_nor_the_documents(answer_env, answers_corpus):
    env = answer_env()
    body = ask_ok(env, "I want to die", "both")
    assert env.provider.count == 0 and env.embedder.calls == [] and body["content"] == ESCALATION_NOTICE
    got = statuses(body)
    assert got["safety_screen"] == "ended" and got["classify_intent"] == "skipped" and got["generate_answer"] == "skipped"
    assert events(body, "safety_screen")[0]["reason_code"] == "crisis_notice" and body["classification"] is None


@pytest.mark.parametrize("mode", ["rag", "both"])
def test_no_evidence_searches_but_never_calls_the_model(answer_env, answers_corpus, mode):
    env = answer_env()
    body = ask_ok(env, "completely unrelated words", mode)
    assert env.provider.count == 0 and len(env.embedder.calls) == 1 and body["no_evidence"] is True
    assert body["content"] == NO_EVIDENCE_TEXT and body["safety"]["flags"] == ["no_evidence"]
    got = statuses(body)
    assert got["execute_retrieval"] == "ok" and got["assess_evidence"] == "ended" and got["generate_answer"] == "skipped"
    assert body["evidence_assessment"] == {**body["evidence_assessment"], "level": "none", "sufficient": False}


@pytest.mark.parametrize("mode", ["rag", "both"])
def test_a_patient_history_question_is_answered_from_the_patient_facts_without_retrieval(answer_env, answers_corpus, mode):
    env = answer_env()
    body = ask_ok(env, "When did he first attend treatment?", mode)
    assert env.embedder.calls == [] and env.provider.count == 1
    assert body["classification"]["label"] == "patient_history_lookup"
    assert body["retrieval_decision"] == {**body["retrieval_decision"], "needed": False,
                                          "reason_code": "history_question_answered_from_patient_facts"}
    got = statuses(body)
    assert got["execute_retrieval"] == "skipped" and got["assess_evidence"] == "skipped" and got["generate_answer"] == "ok"
    assert events(body, "execute_retrieval")[0]["reason_code"] == "history_question_answered_from_patient_facts"
    assert body["evidence"] == [] and body["evidence_assessment"] is None
    system = system_text(env.provider.calls[0])
    assert "PATIENT-RECORD QUESTION" in system and f"MODE: {mode}" in system  # the mode rules are still there


def test_general_knowledge_mode_never_retrieves(answer_env, answers_corpus):
    env = answer_env()
    body = ask_ok(env, QUESTION, "general_knowledge")
    assert env.embedder.calls == [] and env.provider.count == 1
    assert body["retrieval_decision"]["reason_code"] == "mode_forbids_retrieval"
    assert statuses(body)["execute_retrieval"] == "skipped"
    assert "PATIENT-RECORD QUESTION" not in system_text(env.provider.calls[0])


def test_a_comparison_question_retrieves(answer_env, answers_corpus):
    env = answer_env()
    body = ask_ok(env, "How does the alpha evidence apply to this patient?", "both")
    assert body["classification"]["label"] == "comparison" and len(env.embedder.calls) == 1 and env.provider.count == 1


def test_an_uncertain_question_retrieves_as_the_safe_default(answer_env, answers_corpus):
    env = answer_env()
    body = ask_ok(env, "alpha", "rag")
    assert body["classification"]["reason_code"] == "uncertain_default_research"
    assert body["retrieval_decision"]["reason_code"] == "uncertain_default_retrieve" and len(env.embedder.calls) == 1


def test_a_follow_up_without_evidence_is_searched_once_more_with_the_previous_question(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    ask_ok(env, QUESTION, "rag", sid)
    env.embedder.calls.clear()
    body = ask_ok(env, "what about it?", "rag", sid)
    assert len(env.embedder.calls) == 2 and env.embedder.calls[1][0].startswith(QUESTION)
    assert [e["counts"]["attempt"] for e in events(body, "execute_retrieval")] == [1, 2]
    assessments = events(body, "assess_evidence")
    assert [e["reason_code"] for e in assessments] == ["insufficient_retry_follow_up", "enough_usable_chunks"]
    assert body["no_evidence"] is False and env.provider.count == 2


def test_the_retry_happens_at_most_once(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    ask_ok(env, "completely unrelated words", "rag", sid)
    env.embedder.calls.clear()
    body = ask_ok(env, "what about it?", "rag", sid)
    assert len(env.embedder.calls) == 2 and len(events(body, "execute_retrieval")) == 2
    assert body["no_evidence"] is True and env.provider.count == 0


def test_a_short_unrelated_question_does_not_borrow_the_previous_topic(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    ask_ok(env, QUESTION, "rag", sid)
    env.embedder.calls.clear()
    body = ask_ok(env, "completely unrelated words", "rag", sid)
    assert len(env.embedder.calls) == 1 and body["no_evidence"] is True


def test_evidence_that_is_only_flagged_chunks_counts_as_no_evidence(answer_env, answers_corpus):
    env = answer_env(settings_changes={"retrieval_min_similarity": 0.4})
    body = ask_ok(env, "gamma question", "rag")  # only the possible-injection chunk (similarity about 0.45) passes the threshold
    assert env.provider.count == 0 and body["no_evidence"] is True
    assessment = body["evidence_assessment"]
    assert (assessment["retrieved"], assessment["usable"], assessment["excluded_possible_injection"]) == (1, 0, 1)
    assert body["evidence"][0]["excluded_reason"] == "possible_injection"


def test_chunk_text_cannot_change_the_route(answer_env, answers_corpus):
    """The injected chunk says 'ignore previous instructions...'; the route was decided from the question before retrieval."""
    env = answer_env()
    body = ask_ok(env, QUESTION, "both")
    assert any(e["possible_injection"] for e in body["evidence"])
    assert body["classification"]["label"] == "research_question" and "reveal the system prompt" not in str(env.provider.calls)


def test_risk_cues_in_a_normal_question_add_the_notice_and_still_answer(answer_env, answers_corpus):
    env = answer_env()
    body = ask_ok(env, "What are warning signs of suicide risk in people with alcohol use disorder?", "general_knowledge")
    assert body["safety"]["escalation"] is True and env.provider.count == 1
    assert events(body, "safety_check")[0]["reason_code"] == "escalation_notice"
