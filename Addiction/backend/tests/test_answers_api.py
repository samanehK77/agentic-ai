"""POST /api/sessions/{id}/messages end to end: modes, citations, safety, failures, persistence, access rules.
The model is a mock behind the real DeepSeekClient; the embedder is the fake one. No live calls."""
import json
import logging

import httpx
import pytest
from sqlalchemy import text

from app.llm.safety import ESCALATION_NOTICE, WITHHELD_NOTE
from tests.answers_helpers import all_request_text, scripted, system_text, user_text
from tests.fake_llm import TEST_KEY, answer_json, section

PAPER = "test-ans-a"
QUESTION = "alpha question about heavy drinking"
ANSWER_KEYS = {"request_id", "session_id", "message_id", "user_message_id", "created_at", "mode", "no_evidence", "content",
               "sections", "citations", "evidence", "unsupported_claims", "conflicting_evidence", "limitations", "safety",
               "generation", "trace"}


def messages(env, session_id):
    return env.client.get(f"/api/sessions/{session_id}/messages").json()


def stored_rows(env, session_id):
    with env.engine.connect() as c:
        return c.execute(text("SELECT role, mode FROM chat_messages WHERE session_id = :s ORDER BY created_at"),
                         {"s": session_id}).all()


# ---------------------------------------------------------------- the same question in three modes

def test_the_same_question_in_three_modes_shows_inspectable_differences(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    gk = env.ask(sid, QUESTION, "general_knowledge")
    rag = env.ask(sid, QUESTION, "rag")
    both = env.ask(sid, QUESTION, "both")
    assert (gk.status_code, rag.status_code, both.status_code) == (201, 201, 201)
    gk, rag, both = gk.json(), rag.json(), both.json()

    # general_knowledge: nothing retrieved, nothing cited, honest labels
    assert gk["evidence"] == [] and gk["citations"] == [] and gk["no_evidence"] is False
    assert {s["kind"] for s in gk["sections"]} == {"patient_fact", "general_knowledge"}
    assert all(s["citations"] == [] for s in gk["sections"])
    assert gk["generation"]["llm_called"] is True and not any(t["type"] == "retrieval" for t in gk["trace"])

    # rag: real chunks, a verified citation that points to a real chunk id, no general knowledge
    assert [c["chunk_id"] for c in rag["citations"]] == [f"{PAPER}-c0001"]
    citation = rag["citations"][0]
    assert citation["citation_id"] == citation["chunk_id"] and citation["verified"] is True and citation["alias"] == "S1"
    assert citation["source_title"] == "Answers test paper" and citation["stale"] is False
    assert "general_knowledge" not in {s["kind"] for s in rag["sections"]}
    by_id = {e["chunk_id"]: e for e in rag["evidence"]}
    assert set(by_id) == {f"{PAPER}-c0001", f"{PAPER}-c0002", f"{PAPER}-c0003"}
    assert by_id[f"{PAPER}-c0001"]["cited"] is True and by_id[f"{PAPER}-c0002"]["cited"] is False   # retrieved but not cited
    assert by_id[f"{PAPER}-c0003"]["excluded_reason"] == "possible_injection" and by_id[f"{PAPER}-c0003"]["alias"] is None
    assert by_id[f"{PAPER}-c0001"]["similarity"] == pytest.approx(1.0, abs=1e-3)

    # both: research findings AND clearly separated general knowledge
    kinds = [s["kind"] for s in both["sections"]]
    assert "research_finding" in kinds and "general_knowledge" in kinds and both["citations"]
    assert env.provider.count == 3


def test_response_shape_request_id_and_assembled_content(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    response = env.ask(sid, QUESTION, "rag")
    body = response.json()
    assert set(body) == ANSWER_KEYS
    assert body["request_id"] == response.headers["X-Request-ID"] and body["session_id"] == sid and body["mode"] == "rag"
    assert "[Research finding S1]" in body["content"] and "[Patient fact (synthetic)]" in body["content"]
    assert set(body["safety"]) == {"escalation", "notice", "flags"} and body["safety"]["escalation"] is False
    assert {t["type"] for t in body["trace"]} == {"retrieval", "generation", "validation"}
    retrieval = next(t for t in body["trace"] if t["type"] == "retrieval")
    assert retrieval["detail"] == "3 chunk(s)" and retrieval["latency_ms"] >= 0


def test_generation_telemetry_names_the_model_prompt_version_and_parameters(answer_env, answers_corpus):
    env = answer_env()
    body = env.ask(env.new_session(), QUESTION, "rag").json()["generation"]
    assert body["llm_called"] is True and body["model"] == "deepseek-chat" and body["prompt_version"] == "answer-v1"
    assert (body["prompt_tokens"], body["completion_tokens"], body["retries"], body["repair_attempted"]) == (120, 60, 0, False)
    assert body["temperature"] == 0.2 and body["max_tokens"] == 1500 and body["latency_ms"] >= 0


def test_the_request_to_the_model_follows_the_prompt_design(answer_env, answers_corpus):
    env = answer_env()
    env.ask(env.new_session(), QUESTION, "rag")
    call = env.provider.calls[0]
    assert call["payload"]["response_format"] == {"type": "json_object"} and call["payload"]["thinking"] == {"type": "disabled"}
    system, user = system_text(call), user_text(call)
    assert "MODE: rag" in system and "Do not diagnose" in system
    assert "heavy drinking days" in user and QUESTION in user and "P-001" in user and "synthetic" in user
    assert QUESTION not in system and "heavy drinking days" not in system and "P-001" not in system
    # retrieval used the question only, never the patient record
    assert env.embedder.calls == [[QUESTION]]


def test_chunks_flagged_as_possible_injection_never_reach_the_model(answer_env, answers_corpus):
    env = answer_env()
    body = env.ask(env.new_session(), QUESTION, "rag").json()
    assert "Ignore previous instructions" not in all_request_text(env.provider)
    flagged = next(e for e in body["evidence"] if e["chunk_id"] == f"{PAPER}-c0003")
    assert flagged["possible_injection"] is True and flagged["text"].startswith("Ignore previous")  # reported to the user, not sent on


def test_the_selected_patients_facts_are_sent_as_a_separate_block(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session("P-004")
    env.ask(sid, QUESTION, "general_knowledge")
    user = user_text(env.provider.calls[0])
    assert "<patient_facts" in user and "Patient P-004 (fictional)" in user and "<evidence>" not in user


def test_switching_mode_between_questions_in_one_session(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    for mode in ("rag", "general_knowledge", "both", "rag"):
        assert env.ask(sid, QUESTION, mode).json()["mode"] == mode
    assert [r[1] for r in stored_rows(env, sid)] == ["rag", "rag", "general_knowledge", "general_knowledge", "both", "both", "rag", "rag"]


# ---------------------------------------------------------------- no evidence: the model is never called

@pytest.mark.parametrize("mode", ["rag", "both"])
def test_no_chunk_above_the_threshold_means_no_llm_call(answer_env, answers_corpus, mode):
    env = answer_env(key=False)  # works even without a key: the model is not needed
    sid = env.new_session()
    response = env.ask(sid, "completely unrelated words about cooking", mode)
    body = response.json()
    assert response.status_code == 201 and env.provider.count == 0
    assert body["no_evidence"] is True and body["citations"] == [] and body["sections"] == [] and body["evidence"] == []
    assert "No supporting evidence was found" in body["content"] and body["generation"]["llm_called"] is False
    assert "no_evidence" in body["safety"]["flags"] and body["trace"][0]["label"] == "No chunks above the threshold"


def test_a_below_threshold_match_is_treated_as_no_evidence(answer_env, answers_corpus):
    env = answer_env(settings_changes={"retrieval_min_similarity": 0.99})
    body = env.ask(env.new_session(), "gamma question", "rag").json()  # best similarity is about 0.45, the threshold 0.99
    assert body["no_evidence"] is True and env.provider.count == 0


def test_the_fixed_no_evidence_answer_is_persisted_like_any_other(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, "completely unrelated words", "rag")
    items = messages(env, sid)["items"]
    assert [m["role"] for m in items] == ["user", "assistant"] and items[1]["answer"]["no_evidence"] is True


def test_general_knowledge_mode_does_not_need_the_embedding_model(answer_env, answers_corpus):
    env = answer_env()
    env.ask(env.new_session(), "anything", "general_knowledge")
    assert env.embedder.calls == []


# ---------------------------------------------------------------- validation of the model's answer

def test_unknown_aliases_unverified_quotes_and_unsupported_claims_are_shown_not_hidden(answer_env, answers_corpus):
    reply = answer_json([
        section("research_finding", "A supported finding.", ("S1", "heavy drinking days")),
        section("research_finding", "Invented quote finding.", ("S2", "this sentence is not in the chunk")),
        section("research_finding", "Cites a chunk that does not exist.", ("S9", "whatever")),
        section("research_finding", "No citation at all."),
    ], conflicts=["Source A and source B disagree about duration."])
    env = answer_env(scripted(reply))
    body = env.ask(env.new_session(), QUESTION, "rag").json()
    assert [(c["alias"], c["verified"]) for c in body["citations"]] == [("S1", True), ("S2", False)]
    assert [s["text"] for s in body["sections"]] == ["A supported finding.", "Invented quote finding."]
    assert [u["text"] for u in body["unsupported_claims"]] == ["Cites a chunk that does not exist.", "No citation at all."]
    assert body["conflicting_evidence"] == ["Source A and source B disagree about duration."]
    assert {"unverified_quote", "unknown_alias_dropped", "unsupported_research_claim"} <= set(body["safety"]["flags"])


def test_general_knowledge_sections_are_rejected_in_rag_mode(answer_env, answers_corpus):
    reply = answer_json([section("general_knowledge", "From memory."), section("research_finding", "Fine.", ("S1", "placebo in trials"))])
    env = answer_env(scripted(reply))
    body = env.ask(env.new_session(), QUESTION, "rag").json()
    assert [s["kind"] for s in body["sections"]] == ["research_finding"] and "general_knowledge_rejected" in body["safety"]["flags"]


def test_a_model_that_cites_in_general_knowledge_mode_loses_the_citations(answer_env, answers_corpus):
    reply = answer_json([section("research_finding", "Trials show benefit.", ("S1", "placebo"))])
    env = answer_env(scripted(reply))
    body = env.ask(env.new_session(), QUESTION, "general_knowledge").json()
    assert body["citations"] == [] and body["sections"][0]["kind"] == "general_knowledge" and body["unsupported_claims"] == []


def test_dosing_and_treatment_directives_are_withheld(answer_env, answers_corpus):
    reply = answer_json([section("interpretation", "Start naltrexone 50 mg daily."),
                         section("interpretation", "He should be prescribed acamprosate."),
                         section("research_finding", "A fine finding.", ("S1", "placebo in trials"))])
    env = answer_env(scripted(reply))
    body = env.ask(env.new_session(), "What dose of naltrexone should he take? alpha", "rag").json()
    assert [s["kind"] for s in body["sections"]] == ["withheld", "withheld", "research_finding"]
    assert body["sections"][0]["text"] == WITHHELD_NOTE
    assert "50 mg" not in body["content"] and "prescribed" not in body["content"]
    assert {"dosing_instruction", "treatment_directive", "section_withheld"} <= set(body["safety"]["flags"])


def test_the_assembled_answer_respects_the_8000_character_limit(answer_env, answers_corpus):
    reply = answer_json([section("interpretation", ("Word " * 480).strip()) for _ in range(8)])
    env = answer_env(scripted(reply))
    body = env.ask(env.new_session(), QUESTION, "both").json()
    assert len(body["content"]) <= 8000 and "truncated_to_fit" in body["safety"]["flags"]


# ---------------------------------------------------------------- safety notices

def test_risk_cues_add_the_fixed_notice_and_still_answer(answer_env, answers_corpus):
    env = answer_env()
    body = env.ask(env.new_session(), "What are warning signs of suicide risk in this patient?", "general_knowledge").json()
    assert body["safety"]["escalation"] is True and body["safety"]["notice"] == ESCALATION_NOTICE and env.provider.count == 1


def test_first_person_crisis_gets_only_the_notice_and_no_model_call(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    body = env.ask(sid, "I want to die", "rag").json()
    assert env.provider.count == 0 and env.embedder.calls == []
    assert body["content"] == ESCALATION_NOTICE and body["sections"] == [] and body["safety"]["flags"] == ["personal_crisis_no_answer"]
    assert body["safety"]["escalation"] is True and body["generation"]["llm_called"] is False
    assert [m["role"] for m in messages(env, sid)["items"]] == ["user", "assistant"]


def test_the_models_own_escalation_flag_adds_the_notice(answer_env, answers_corpus):
    env = answer_env(scripted(answer_json([section("interpretation", "Please involve a clinician.")], escalation=True)))
    body = env.ask(env.new_session(), "How is he doing?", "general_knowledge").json()
    assert body["safety"]["escalation"] is True and body["safety"]["notice"] == ESCALATION_NOTICE


# ---------------------------------------------------------------- failures: nothing is persisted, the key never leaks

def failing(status=None, exception=None):
    return lambda payload, n: exception if exception else httpx.Response(status, json={"error": f"{TEST_KEY} secret"})


@pytest.mark.parametrize("responder,status,code,calls", [
    (failing(exception=httpx.ReadTimeout("t")), 504, "llm_timeout", 3),
    (failing(429), 503, "llm_unavailable", 3),
    (failing(500), 503, "llm_unavailable", 3),
    (failing(503), 503, "llm_unavailable", 3),
    (failing(401), 503, "llm_unavailable", 1),
    (failing(402), 503, "llm_unavailable", 1),
    (failing(exception=httpx.ConnectError("x")), 503, "llm_unavailable", 3),
])
def test_provider_failures_map_to_clean_errors_and_persist_nothing(answer_env, answers_corpus, caplog, responder, status, code, calls):
    caplog.set_level(logging.DEBUG)
    env = answer_env(responder)
    sid = env.new_session()
    response = env.ask(sid, QUESTION, "rag")
    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (status, code) and env.provider.count == calls
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert messages(env, sid)["total"] == 0                                 # nothing was stored
    for leak in (TEST_KEY, "secret", "Bearer", "deepseek", "api.deepseek.com"):
        assert leak not in response.text, leak
    assert TEST_KEY not in caplog.text and "Bearer" not in caplog.text


def test_a_provider_rate_limit_carries_a_retry_hint(answer_env, answers_corpus):
    env = answer_env(failing(429))
    response = env.ask(env.new_session(), QUESTION, "rag")
    assert response.status_code == 503 and response.headers["Retry-After"] == "30"


def test_provider_errors_are_not_retried_for_authentication_problems(answer_env, answers_corpus):
    env = answer_env(failing(401))
    env.ask(env.new_session(), QUESTION, "rag")
    assert env.provider.count == 1 and env.provider.sleeps == []


def test_malformed_json_gets_one_repair_attempt(answer_env, answers_corpus):
    good = answer_json([section("research_finding", "Fixed.", ("S1", "placebo in trials"))])
    env = answer_env(scripted("this is not json", good))
    body = env.ask(env.new_session(), QUESTION, "rag").json()
    assert env.provider.count == 2 and body["generation"]["repair_attempted"] is True and body["sections"][0]["text"] == "Fixed."
    assert body["generation"]["prompt_tokens"] == 240  # both calls are counted
    repair = env.provider.calls[1]["payload"]["messages"]
    assert [m["role"] for m in repair] == ["system", "user", "assistant", "user"] and "could not be used" in repair[-1]["content"]


def test_a_schema_violation_is_repaired_with_field_names_only(answer_env, answers_corpus):
    bad = json.dumps({"sections": [{"kind": "poem", "text": "roses are red"}]})
    good = answer_json([section("interpretation", "Fine.")])
    env = answer_env(scripted(bad, good))
    env.ask(env.new_session(), QUESTION, "general_knowledge")
    repair_request = env.provider.calls[1]["payload"]["messages"][-1]["content"]
    assert "sections.0.kind" in repair_request and "poem" not in repair_request.split("could not be used:")[1]


def test_still_bad_after_the_repair_is_a_502(answer_env, answers_corpus):
    env = answer_env(scripted("not json", "{broken"))
    sid = env.new_session()
    response = env.ask(sid, QUESTION, "rag")
    assert response.status_code == 502 and response.json()["error"]["code"] == "llm_bad_output" and env.provider.count == 2
    assert messages(env, sid)["total"] == 0


def test_empty_or_truncated_provider_output_is_repaired_once_then_502(answer_env, answers_corpus):
    from tests.fake_llm import completion

    env = answer_env(lambda p, n: httpx.Response(200, json=completion(None)))
    response = env.ask(env.new_session(), QUESTION, "rag")
    assert response.status_code == 502 and env.provider.count == 2
    env2 = answer_env(lambda p, n: httpx.Response(200, json=completion('{"sections": [', finish="length")))
    assert env2.ask(env2.new_session(), QUESTION, "rag").status_code == 502


def test_a_missing_key_is_a_503_and_nothing_is_stored(answer_env, answers_corpus):
    env = answer_env(key=False)
    sid = env.new_session()
    response = env.ask(sid, QUESTION, "general_knowledge")
    assert response.status_code == 503 and response.json()["error"]["code"] == "llm_not_configured" and env.provider.count == 0
    assert messages(env, sid)["total"] == 0


def test_retrieval_problems_keep_their_batch_6_codes(answer_env, engine):
    env = answer_env()  # no corpus at all
    response = env.ask(env.new_session(), QUESTION, "rag")
    assert response.status_code == 503 and response.json()["error"]["code"] == "retrieval_not_ready" and env.provider.count == 0


def test_the_key_and_prompts_never_appear_in_logs(answer_env, answers_corpus, caplog):
    caplog.set_level(logging.DEBUG)
    env = answer_env()
    sid = env.new_session()
    secret_question = "alpha CONFIDENTIAL-QUESTION-WORDS"
    assert env.ask(sid, secret_question, "both").status_code == 201
    ours = [r for r in caplog.records if r.name.startswith("mindevidence")]
    assert any("answer request=" in r.getMessage() for r in ours)
    line = next(r.getMessage() for r in ours if "answer request=" in r.getMessage())
    for part in ("user=", "mode=both", "outcome=answered", "prompt_tokens=120", "completion_tokens=60", "latency_ms="):
        assert part in line
    haystack = " ".join(r.getMessage() for r in ours)
    for secret in ("CONFIDENTIAL", TEST_KEY, "heavy drinking", "naltrexone", "synthetic", "psychosocial support"):
        assert secret not in haystack, secret
    assert TEST_KEY not in caplog.text


# ---------------------------------------------------------------- persistence and the history

def test_the_turn_is_stored_and_read_back_with_citations(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    posted = env.ask(sid, QUESTION, "rag").json()
    page = messages(env, sid)
    assert page["total"] == 2 and [m["role"] for m in page["items"]] == ["user", "assistant"]
    user, assistant = page["items"]
    assert user["content"] == QUESTION and user["answer"] is None and user["mode"] == "rag"
    answer = assistant["answer"]
    assert answer["message_id"] == posted["message_id"] == assistant["message_id"] and answer["content"] == assistant["content"]
    assert answer["citations"] == posted["citations"] and answer["sections"] == posted["sections"]
    assert [e["chunk_id"] for e in answer["evidence"]] == [e["chunk_id"] for e in posted["evidence"]]
    assert answer["request_id"] is None  # only the POST carries a request id
    with env.engine.connect() as c:
        row = c.execute(text("SELECT response, generation FROM chat_messages WHERE message_id = :m"), {"m": posted["message_id"]}).one()
    stored = json.dumps([row[0], row[1]])
    assert "heavy drinking days" not in stored and QUESTION not in stored           # citations by chunk id, no chunk or question text
    assert row[0]["citations"][0]["chunk_id"] == f"{PAPER}-c0001" and row[1]["model"] == "deepseek-chat"
    assert set(row[1]) == {"llm_called", "model", "prompt_version", "latency_ms", "prompt_tokens", "completion_tokens", "retries",
                           "repair_attempted", "temperature", "max_tokens", "estimated_context_tokens", "history_turns_used"}  # telemetry only


def test_a_changed_or_deleted_chunk_is_marked_stale_when_read_back(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    env.ask(sid, QUESTION, "rag")
    first = messages(env, sid)["items"][1]["answer"]
    assert not any(e["stale"] for e in first["evidence"]) and not any(c["stale"] for c in first["citations"])
    with engine.begin() as c:
        c.execute(text("UPDATE paper_chunks SET text_sha256 = :h WHERE chunk_id = :i"), {"h": "e" * 64, "i": f"{PAPER}-c0001"})
        c.execute(text("DELETE FROM paper_chunks WHERE chunk_id = :i"), {"i": f"{PAPER}-c0002"})
    again = messages(env, sid)["items"][1]["answer"]
    by_id = {e["chunk_id"]: e for e in again["evidence"]}
    assert by_id[f"{PAPER}-c0001"]["stale"] is True and by_id[f"{PAPER}-c0001"]["text"]          # changed: flagged, still readable
    assert by_id[f"{PAPER}-c0002"]["stale"] is True and by_id[f"{PAPER}-c0002"]["text"] is None  # gone: flagged, no text
    assert again["citations"][0]["stale"] is True


def test_recent_turns_go_into_the_next_prompt_untrusted_and_within_the_window(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    for n in range(6):
        env.ask(sid, f"alpha question number {n}", "general_knowledge")
    last = user_text(env.provider.calls[-1])
    assert "<conversation>" in last and "alpha question number 4" in last and "alpha question number 0" not in last
    assert last.count("user: alpha question") == 4  # at most the last four exchanges


def test_history_is_trimmed_to_the_context_budget(answer_env, answers_corpus):
    env = answer_env(llm_changes={"context_token_budget": 1000})
    sid = env.new_session()
    for n in range(3):
        env.ask(sid, "alpha " + "long question " * 60, "general_knowledge")
    assert "<conversation>" not in user_text(env.provider.calls[-1]) or user_text(env.provider.calls[-1]).count("user:") < 3
    assert "Do not diagnose" in system_text(env.provider.calls[-1])


def test_an_assistant_message_from_the_past_does_not_break_reading_old_sessions(answer_env, answers_corpus, engine):
    env = answer_env()
    sid = env.new_session()
    with engine.begin() as c:  # a message written before Batch 07 has no stored answer
        c.execute(text("INSERT INTO chat_messages (session_id, role, mode, content) VALUES (:s, 'assistant', 'rag', 'old reply')"), {"s": sid})
    items = messages(env, sid)["items"]
    assert items[0]["answer"] is None and items[0]["content"] == "old reply"


# ---------------------------------------------------------------- access rules and input validation

def test_anonymous_gets_401(answer_env, answers_corpus):
    from fastapi.testclient import TestClient

    env = answer_env()
    sid = env.new_session()
    with TestClient(env.app, base_url="http://testserver.local") as anon:
        response = anon.post(f"/api/sessions/{sid}/messages", json={"content": "x", "mode": "rag"})
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


def test_missing_or_wrong_csrf_header_is_403_and_calls_nothing(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    del env.client.headers["X-CSRF-Token"]
    for headers in ({}, {"X-CSRF-Token": "wrong"}):
        response = env.ask(sid, QUESTION, "rag", headers=headers)
        assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"
    assert env.provider.count == 0


def test_another_users_session_and_unknown_sessions_are_404(answer_env, answers_corpus):
    alice, bob = answer_env(), answer_env()
    sid = alice.new_session()
    foreign = bob.ask(sid, QUESTION, "rag")
    unknown = bob.ask("123e4567-e89b-42d3-a456-426614174000", QUESTION, "rag")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert bob.provider.count == 0 and messages(alice, sid)["total"] == 0


@pytest.mark.parametrize("body", [
    {"content": "", "mode": "rag"}, {"content": "   ", "mode": "rag"}, {"content": "x" * 1001, "mode": "rag"},
    {"content": "ok", "mode": "auto"}, {"content": "ok"}, {"mode": "rag"}, {"content": "ok", "mode": "rag", "extra": 1},
    {"content": 5, "mode": "rag"},
])
def test_invalid_bodies_are_422(answer_env, answers_corpus, body):
    env = answer_env()
    sid = env.new_session()
    response = env.client.post(f"/api/sessions/{sid}/messages", json=body)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error" and env.provider.count == 0


def test_a_question_of_exactly_1000_characters_is_accepted_and_trimmed(answer_env, answers_corpus):
    env = answer_env()
    sid = env.new_session()
    assert env.ask(sid, "a" * 1000, "general_knowledge").status_code == 201
    assert env.ask(sid, "   padded question   ", "general_knowledge").status_code == 201
    assert messages(env, sid)["items"][2]["content"] == "padded question"


@pytest.mark.parametrize("key", ["short", "x" * 65, "has space in it", "semi;colon;key"])
def test_invalid_idempotency_keys_are_422(answer_env, answers_corpus, key):
    env = answer_env()
    response = env.ask(env.new_session(), QUESTION, "rag", key=key)
    assert response.status_code == 422 and env.provider.count == 0


def test_rate_limit_is_429_with_retry_after_and_does_not_call_the_model(answer_env, answers_corpus):
    env = answer_env(settings_changes={"answer_rate_limit_per_minute": 2})
    sid = env.new_session()
    assert [env.ask(sid, QUESTION, "general_knowledge").status_code for _ in range(2)] == [201, 201]
    response = env.ask(sid, QUESTION, "general_knowledge")
    error = response.json()["error"]
    assert response.status_code == 429 and error["code"] == "rate_limited" and error["request_id"] == response.headers["X-Request-ID"]
    assert 1 <= int(response.headers["Retry-After"]) <= 60 and env.provider.count == 2
    assert messages(env, sid)["total"] == 4


def test_rejected_requests_do_not_use_up_the_rate_limit(answer_env, answers_corpus):
    env = answer_env(settings_changes={"answer_rate_limit_per_minute": 1})
    sid = env.new_session()
    for _ in range(3):
        assert env.client.post(f"/api/sessions/{sid}/messages", json={"content": "", "mode": "rag"}).status_code == 422
    assert env.ask(sid, QUESTION, "general_knowledge").status_code == 201


def test_errors_use_the_standard_format(answer_env, answers_corpus):
    env = answer_env(failing(503))
    response = env.ask(env.new_session(), QUESTION, "rag")
    error = response.json()["error"]
    assert set(response.json()) == {"error"} and set(error) >= {"code", "message", "request_id"}


def test_openapi_documents_the_endpoint_and_its_errors(answer_env):
    env = answer_env()
    operation = env.client.get("/openapi.json").json()["paths"]["/api/sessions/{session_id}/messages"]["post"]
    assert {"201", "403", "404", "409", "422", "429", "502", "503", "504"} <= set(operation["responses"])
    assert any(p["name"] == "Idempotency-Key" and p["in"] == "header" for p in operation["parameters"])


def test_a_rejected_model_output_is_logged_with_a_reason_but_never_its_text(answer_env, answers_corpus, caplog):
    caplog.set_level(logging.DEBUG)
    env = answer_env(scripted('{"sections": [{"kind": "poem", "text": "SECRET-MODEL-WORDS"}]}', "SECRET-MODEL-WORDS not json"))
    assert env.ask(env.new_session(), QUESTION, "rag").status_code == 502
    messages_ = [r.getMessage() for r in caplog.records if r.name == "mindevidence.answers"]
    assert any("attempt 1" in m and "sections.0.kind" in m for m in messages_)
    assert any("attempt 2" in m and "not valid json" in m for m in messages_)
    assert "SECRET-MODEL-WORDS" not in caplog.text


def test_a_cut_off_provider_answer_is_logged_as_such(answer_env, answers_corpus, caplog):
    from tests.fake_llm import completion

    caplog.set_level(logging.DEBUG)
    env = answer_env(lambda p, n: httpx.Response(200, json=completion('{"sections": [', finish="length")))
    env.ask(env.new_session(), QUESTION, "rag")
    assert any("cut off" in r.getMessage() for r in caplog.records if r.name == "mindevidence.answers")
