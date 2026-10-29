"""Deterministic evidence assessment and follow-up handling. No model, no I/O."""
import re

WEAK_TOP_SIMILARITY = 0.55  # a single usable chunk below this similarity counts as weak evidence
FOLLOW_UP_MAX_WORDS = 6
MAX_RETRIEVALS = 2  # the first search plus at most ONE retry for a follow-up
ENRICHED_QUERY_LIMIT = 1000

_FOLLOW_UP_START = re.compile(
    r"^(and|also|what about|how about|then|so|but|why|how so|it|that|this|these|those|they|he|she|his|her|their)\b", re.IGNORECASE)


def assess(evidence: list) -> dict:
    """Levels: none = no usable chunk; weak = exactly one usable chunk with top similarity below 0.55; adequate otherwise.
    Usable = retrieved above the similarity threshold (the search already applied it) and not flagged possible_injection.
    Weak evidence is still answered (as in Batch 07) but the level is recorded."""
    usable = [e for e in evidence if not e.possible_injection]
    top = max((e.similarity for e in usable), default=0.0)
    if not usable:
        level, code = "none", "no_usable_chunks"
    elif len(usable) == 1 and top < WEAK_TOP_SIMILARITY:
        level, code = "weak", "single_low_similarity_chunk"
    else:
        level, code = "adequate", "enough_usable_chunks"
    return {"sufficient": level != "none", "level": level, "reason_code": code, "retrieved": len(evidence),
            "usable": len(usable), "excluded_possible_injection": len(evidence) - len(usable),
            "top_similarity": round(top, 4)}


_REFERS_BACK = re.compile(r"\b(it|that|this|these|those|they|them|he|she|his|her|their)\b", re.IGNORECASE)


def is_follow_up(question: str) -> bool:
    """A follow-up depends on the previous turn: it starts with a connective or pronoun, or it is short and refers back
    with a pronoun. Length alone is not enough (a short unrelated question must not borrow the previous topic)."""
    text = " ".join(question.split())
    return bool(_FOLLOW_UP_START.match(text)) or (len(text.split()) <= FOLLOW_UP_MAX_WORDS and bool(_REFERS_BACK.search(text)))


def enrich_query(previous_user_turn: str, question: str) -> str:
    return (" ".join(previous_user_turn.split()) + " " + " ".join(question.split()))[:ENRICHED_QUERY_LIMIT].strip()


def previous_user_turn(history: list[tuple[str, str]]) -> str | None:
    for role, text in reversed(history):
        if role == "user" and text.strip():
            return text
    return None
