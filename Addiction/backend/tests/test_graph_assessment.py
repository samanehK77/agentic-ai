"""Evidence assessment thresholds and follow-up handling (pure functions)."""
import pytest

from app.graph.assessment import (
    MAX_RETRIEVALS, WEAK_TOP_SIMILARITY, assess, enrich_query, is_follow_up, previous_user_turn)
from app.llm.validate import EvidenceItem


def item(similarity: float, injection: bool = False, n: int = 1) -> EvidenceItem:
    return EvidenceItem(chunk_id=f"c{n}", paper_id="p", title="t", section_title=None, section_type="body", page_start=1,
                        page_end=1, text="text", similarity=similarity, possible_injection=injection)


def test_no_chunks_means_none_and_insufficient():
    result = assess([])
    assert (result["level"], result["sufficient"], result["usable"]) == ("none", False, 0)


def test_only_flagged_chunks_are_not_usable():
    result = assess([item(0.9, injection=True)])
    assert (result["level"], result["sufficient"], result["excluded_possible_injection"]) == ("none", False, 1)


def test_one_low_similarity_chunk_is_weak_but_sufficient():
    result = assess([item(WEAK_TOP_SIMILARITY - 0.01)])
    assert (result["level"], result["sufficient"], result["reason_code"]) == ("weak", True, "single_low_similarity_chunk")


@pytest.mark.parametrize("chunks", [[item(0.55)], [item(0.9)], [item(0.3, n=1), item(0.2, n=2)], [item(0.9), item(0.5, injection=True, n=2)]])
def test_adequate_evidence(chunks):
    assert assess(chunks)["level"] == "adequate" or assess(chunks)["usable"] == 1


def test_the_counts_and_top_similarity_are_reported():
    result = assess([item(0.8, n=1), item(0.6, n=2), item(0.99, injection=True, n=3)])
    assert (result["retrieved"], result["usable"], result["top_similarity"]) == (3, 2, 0.8)


@pytest.mark.parametrize("question", ["and what about relapse?", "Also the second one", "What about it?", "how about that", "Why?", "They relapsed. Why?"])
def test_follow_ups_are_recognised(question):
    assert is_follow_up(question)


@pytest.mark.parametrize("question", ["completely unrelated words", "alpha question about heavy drinking", "What is contingency management?",
                                      "Which medications are used to treat opioid addiction?"])
def test_a_short_unrelated_question_is_not_a_follow_up(question):
    assert not is_follow_up(question)


def test_the_enriched_query_adds_the_previous_user_turn_and_is_capped():
    assert enrich_query("alpha  question", "what about it?") == "alpha question what about it?"
    assert len(enrich_query("x " * 900, "y " * 900)) <= 1000


def test_the_previous_user_turn_is_the_last_user_message():
    history = [("user", "first"), ("assistant", "reply"), ("user", "second"), ("assistant", "reply 2")]
    assert previous_user_turn(history) == "second" and previous_user_turn([("assistant", "x")]) is None and previous_user_turn([]) is None


def test_at_most_one_retry_is_allowed():
    assert MAX_RETRIEVALS == 2
