"""Builds the messages sent to the model.

Layout: ONE system message (trusted, static rules from versioned files) and ONE user message made of clearly delimited
blocks: <patient_facts>, <evidence>, <conversation>, <question>. Everything that comes from patients, documents, earlier
turns or the user is neutralized first (sanitize.py) and appears only in those blocks, never in the system message.
"""
import math
from dataclasses import dataclass, field
from pathlib import Path

from app.llm.base import LLMMessage
from app.llm.sanitize import attribute, neutralize
from app.llm.validate import EvidenceItem

PROMPT_VERSION = "answer-v1"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
HISTORY_TURNS = 4  # exchanges (user + assistant) kept in the prompt
MAX_HISTORY_CHARS = {"user": 1000, "assistant": 700}
MAX_PATIENT_FACTS_CHARS = 3500


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def estimate_tokens(text: str) -> int:
    """A rough, conservative estimate (about 4 characters per token); good enough for a context budget."""
    return math.ceil(len(text) / 4)


def system_prompt(mode: str, patient_facts_only: bool = False) -> str:
    text = load_prompt("answer_v1.system.txt") + "\n\n" + load_prompt(f"mode_{mode}.txt")
    if patient_facts_only:  # routed as a question about the patient record: no documents, answer from the facts only
        text += "\n\n" + load_prompt("mode_patient_facts.txt")
    return text


def _words(value) -> str:
    return str(value).replace("_", " ")


def _date(value) -> str:
    return str(value)[:10] if value else "ongoing"


def patient_facts_text(profile: dict) -> str:
    """A compact rendering of the synthetic patient record (patient facts only)."""
    lines = [
        f"Patient {profile['patient_id']} (fictional): age {profile['age_at_intake']} at intake, {_words(profile['gender'])}, "
        f"primary category {_words(profile['primary_category'])}"
        + (f" ({profile['primary_use_subject']})" if profile.get("primary_use_subject") else "") + ".",
        f"Living situation: {profile['living_situation']}",
        f"Employment: {profile['employment_status']}",
        f"Social context: {profile['social_context']}",
        f"Co-occurring symptoms: {profile['co_occurring_symptoms']}",
        f"Motivation at intake: {_words(profile['motivation_at_intake'])}",
        f"Background: {profile['background']}",
        f"History: {profile['history_summary']}",
        f"Treatment so far: {profile['treatment_summary']}",
    ]
    for factor in profile.get("factors", []):
        lines.append(f"{_words(factor['kind']).capitalize()} ({_words(factor['context'])}): {factor['description']}")
    for item in profile.get("interventions", []):
        lines.append(f"Previous intervention: {_words(item['type'])}, {item['setting']}, {_date(item['start_date'])} to "
                     f"{_date(item.get('end_date'))}, {_words(item['completion_status'])}. Outcome: {item['reported_outcome']}")
    progress = profile.get("progress", [])
    if progress:
        last = progress[-1]
        lines.append(f"Latest progress ({_date(last['observed_on'])}): {_words(last['use_status'])}, motivation "
                     f"{_words(last['motivation'])}. {last['note']}")
    return neutralize("\n".join(lines), MAX_PATIENT_FACTS_CHARS)


def assign_aliases(items: list[EvidenceItem]) -> None:
    """S1..Sn for the chunks that go into the prompt (best similarity first). Chunks flagged as possible prompt
    injection stay out of the prompt; they remain listed in the evidence with the reason."""
    number = 0
    for item in items:
        if item.possible_injection:
            item.alias, item.excluded_reason = None, "possible_injection"
        else:
            number += 1
            item.alias, item.excluded_reason = f"S{number}", None


def _evidence_block(items: list[EvidenceItem]) -> str:
    chunks = []
    for item in items:
        if not item.alias:
            continue
        pages = str(item.page_start) if item.page_start == item.page_end else f"{item.page_start}-{item.page_end}"
        chunks.append(f'<chunk alias="{item.alias}" title="{attribute(item.title)}" '
                      f'section="{attribute(item.section_title or "unknown")}" pages="{pages}">\n'
                      f"{neutralize(item.text)}\n</chunk>")
    return "<evidence>\n" + "\n".join(chunks) + "\n</evidence>"


def _history_block(history: list[tuple[str, str]]) -> str:
    lines = [f"{role}: {neutralize(' '.join(text.split()), MAX_HISTORY_CHARS[role])}" for role, text in history]
    return "<conversation>\n" + "\n".join(lines) + "\n</conversation>"


@dataclass
class PromptBuild:
    messages: list[LLMMessage]
    estimated_tokens: int
    history_turns_used: int = 0
    dropped_for_budget: list[str] = field(default_factory=list)


def build_messages(*, mode: str, profile: dict, evidence: list[EvidenceItem], history: list[tuple[str, str]],
                   question: str, budget_tokens: int, patient_facts_only: bool = False) -> PromptBuild:
    """Deterministic order. Over budget: the oldest conversation turns are trimmed first, then the lowest-similarity
    chunks; the system rules and the question are never trimmed."""
    system = system_prompt(mode, patient_facts_only)
    facts = (f'<patient_facts source="synthetic patient record (fictional)">\n{patient_facts_text(profile)}\n</patient_facts>')
    question_block = f"<question>\n{neutralize(question, 1000)}\n</question>"
    history = history[-(HISTORY_TURNS * 2):]
    dropped: list[str] = []

    def assemble() -> str:
        blocks = [facts]
        if mode != "general_knowledge" and any(item.alias for item in evidence):
            blocks.append(_evidence_block(evidence))
        if history:
            blocks.append(_history_block(history))
        blocks.append(question_block)
        return "\n\n".join(blocks)

    user = assemble()
    while estimate_tokens(system) + estimate_tokens(user) > budget_tokens and history:
        history = history[2:] if len(history) >= 2 else []  # oldest exchange first
        user = assemble()
    while estimate_tokens(system) + estimate_tokens(user) > budget_tokens:
        last = next((item for item in reversed(evidence) if item.alias), None)
        if last is None:
            break
        last.alias, last.excluded_reason = None, "context_budget"
        dropped.append(last.chunk_id)
        user = assemble()
    messages = [LLMMessage("system", system), LLMMessage("user", user)]
    return PromptBuild(messages, estimate_tokens(system) + estimate_tokens(user), len(history) // 2, dropped)
