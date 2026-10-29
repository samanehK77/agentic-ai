"""Deterministic safety layer. All checks are keyword heuristics: they miss things and they flag harmless text.
They are a safety net around the model, not a guarantee (see docs/LLM.md)."""
import re
from dataclasses import dataclass, field

# Written in the backend, never generated, and deliberately without country-specific phone numbers.
ESCALATION_NOTICE = (
    "Safety notice: if you or someone else may be in immediate danger or at risk of harm, contact local emergency "
    "services or a crisis service in your area right now. This is an educational tool: it cannot assess risk, it "
    "cannot help in an emergency, and it is not a substitute for a qualified professional. Please talk to a qualified "
    "professional about any safety concern."
)

WITHHELD_NOTE = ("This part of the answer was withheld: it contained a dosing instruction or an individual treatment "
                 "directive, which this educational tool does not give.")

_FLAGS = re.IGNORECASE
_GENERAL_RISK = [re.compile(p, _FLAGS) for p in (
    r"\bsuicid\w*", r"\bself[- ]?harm\w*", r"\bkill(?:ing)?\s+(?:myself|himself|herself|themselves|yourself)\b",
    r"\bhurt(?:ing)?\s+(?:myself|himself|herself|themselves)\b", r"\bend(?:ing)?\s+(?:my|his|her|their)\s+(?:own\s+)?life\b",
    r"\boverdos\w*", r"\bwant(?:s|ed)? to die\b", r"\bbetter off dead\b", r"\btook too many\b",
    r"\bacute(?:ly)?\s+(?:danger|risk|crisis)\b", r"\bmedical emergency\b",
)]
# First-person statements: the person asking may be the one in danger. No answer is generated for these.
_PERSONAL_RISK = [re.compile(p, _FLAGS) for p in (
    r"\bI(?:'m| am)?\s+(?:going to|gonna|want to|wanna|plan to|will|am thinking of|thinking about)\s+(?:kill myself|end my life|die|hurt myself|harm myself|overdose)",
    r"\bI\s+(?:want|wish)\s+(?:to\s+)?(?:die|be dead)\b", r"\bI(?:'m| am)\s+(?:suicidal|overdosing)\b",
    r"\bI\s+(?:took|have taken|swallowed|just took)\s+too (?:many|much)\b", r"\bkill myself\b", r"\bend my (?:own )?life\b",
    r"\bI\s+(?:can't|cannot|can not)\s+go on\b", r"\bI(?:'m| am)\s+going to hurt (?:myself|someone)\b",
)]

_DOSING = [re.compile(p, _FLAGS) for p in (
    r"\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|µg|ug|ml|mL|iu|units?)\b(?:\s?/\s?(?:kg|day|d|dose|h|hr))?",
    r"\b\d+(?:[.,]\d+)?\s?g\b(?:\s?/\s?(?:kg|day|d|dose))?", r"\b(?:milligrams?|micrograms?|millilit(?:er|re)s?)\b",
    r"\b(?:once|twice|three times|four times|\d+ times)\s+(?:a|per|every)\s+(?:day|week|night|morning|hour)\b",
    r"\bdaily dose\b", r"\b(?:tablets?|pills?|capsules?)\s+(?:a|per|each)\s+(?:day|night)\b",
)]
_DIRECTIVES = [re.compile(p, _FLAGS) for p in (
    r"\bshould be (?:prescribed|given|started|put on|treated with|switched)\b",
    r"\b(?:stop|start|begin|continue|increase|decrease|reduce|discontinue)\s+taking\b",
    r"\b(?:he|she|they|the patient|this patient|P-\d{3})\s+(?:should|must|needs? to|ought to)\s+(?:take|start|stop|begin|receive|get|use|switch|increase|decrease|reduce|discontinue)\b",
    r"\byou\s+(?:should|must|need to)\s+(?:take|start|stop|begin|increase|decrease|reduce|discontinue)\b",
    r"\bI\s+(?:recommend|advise|suggest|would prescribe)\b",
    r"\bprescribe\s+(?:him|her|them|the patient|this patient)\b",
    r"\bthe\s+(?:best|right|appropriate|ideal)\s+(?:treatment|medication|drug|option|therapy)\s+for\s+(?:him|her|them|this patient|P-\d{3})\b",
)]


@dataclass(frozen=True)
class RiskScreen:
    triggered: bool = False
    personal: bool = False
    matched: list[str] = field(default_factory=list)


def screen_question(question: str) -> RiskScreen:
    """Risk cues in the user's question. `personal` means a first-person statement: no answer is generated then."""
    personal = any(p.search(question) for p in _PERSONAL_RISK)
    general = [p.pattern for p in _GENERAL_RISK if p.search(question)]
    return RiskScreen(triggered=personal or bool(general), personal=personal, matched=general[:3])


def check_output(text: str) -> list[str]:
    """Flag codes for a piece of generated text: dosing_instruction and/or treatment_directive."""
    flags = []
    if any(p.search(text) for p in _DOSING):
        flags.append("dosing_instruction")
    if any(p.search(text) for p in _DIRECTIVES):
        flags.append("treatment_directive")
    return flags
