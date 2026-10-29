"""Deterministic question classifier. Rule-based, conservative and honest about it: it matches English phrases only
(other languages match nothing and fall through to the default, which retrieves). It never raises, and it never looks at
retrieved text, so injected chunk text cannot change a route.

Labels: unsupported_request, comparison, patient_history_lookup, research_question. The order of the rules matters
(documented in docs/ORCHESTRATION.md). `Classifier` is the seam where a model-based classifier could replace the rules
later; the graph only depends on `classify(question, patient_id) -> Classification`.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

UNSUPPORTED = "unsupported_request"
COMPARISON = "comparison"
HISTORY = "patient_history_lookup"
RESEARCH = "research_question"
LABELS = (UNSUPPORTED, COMPARISON, HISTORY, RESEARCH)


@dataclass(frozen=True)
class Classification:
    label: str
    reason_code: str


class Classifier(Protocol):
    def classify(self, question: str, patient_id: str) -> Classification:
        ...


def _compile(*patterns: str) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_SUBJECT = r"(?:he|she|they|the patient|this patient|that patient|p-\d{3})"

# (reason_code, patterns): checked in this order; the first match decides.
_UNSUPPORTED_RULES = [
    ("diagnosis_request", _compile(
        r"\bdiagnos(?:e|es|ed|ing|is)\b", rf"\b(?:does|do|did|is|has|have)\s+{_SUBJECT}\s+(?:have|meet|got|suffer)\b",
        r"\bmeets?\s+(?:the\s+)?(?:dsm|icd|criteria)\b", r"\bis\s+(?:he|she|they)\s+(?:an?\s+)?(?:alcoholic|addict)\b")),
    ("dosing_or_prescribing_request", _compile(
        r"\b(?:what|which|how\s+much|how\s+many|recommended?)\b[^?.!]{0,40}\b(?:dose|doses|dosage|dosing|mg|milligrams?)\b",
        r"\bhow\s+(?:much|many)\b[^?.!]{0,40}\b(?:per|a|each|every)\s+(?:day|dose|week|night|morning|time)\b",
        r"\bprescri(?:be|bed|bing|ption)\b")),
    ("individual_treatment_choice", _compile(
        rf"\bwhich\s+(?:medications?|drugs?|treatments?|therap(?:y|ies)|medicines?)\s+(?:should|would|do you recommend for)\s+{_SUBJECT}\b",
        rf"\b(?:what|which)\s+should\s+{_SUBJECT}\s+(?:take|be given|be prescribed|start|use)\b",
        rf"\bshould\s+{_SUBJECT}\s+(?:take|start|stop|switch|be\s+(?:put\s+on|given|prescribed|treated))\b",
        r"\b(?:best|right|ideal|appropriate)\s+(?:treatment|medication|drug|therapy)\s+for\s+(?:him|her|them|this patient|p-\d{3})\b",
        rf"\bwhat\s+treatment\s+should\s+{_SUBJECT}\b")),
    ("multi_patient_request", _compile(
        r"\b(?:all|every|each|other|both|two)\s+(?:the\s+)?patients?\b", r"\bpatients\s+p-\d{3}\b")),
    ("real_person_or_first_person", _compile(
        r"\b(?:my|our)\s+(?:own\s+)?(?:brother|sister|friend|husband|wife|son|daughter|mother|father|mom|dad|partner|boyfriend|"
        r"girlfriend|cousin|neighbou?r|coworker|colleague|client|patient|child|kid|uncle|aunt)\b",
        r"\bi\s+(?:am|was|have been)\s+(?:addicted|an addict|drinking too much|using (?:too much|drugs))\b",
        r"\bmy\s+(?:own\s+)?(?:addiction|drinking|drug use|drug problem|substance use)\b", r"\breal\s+(?:patient|person|people)\b")),
    ("off_topic", _compile(
        r"\b(?:recipes?|football|soccer|basketball|cricket|bitcoin|cryptocurrenc\w+|stock\s+market|weather\s+forecast|"
        r"movie\s+(?:recommendation|review)s?|horoscope|lottery)\b",
        r"\bwrite\s+(?:me\s+)?(?:an?\s+|some\s+)?(?:code|python|javascript|poem|essay|song|story)\b", r"\btell\s+me\s+a\s+joke\b")),
]
_OTHER_PATIENT_ID = re.compile(r"\bp-(\d{3})\b", re.IGNORECASE)
_COMPARISON = _compile(
    r"\bcompar(?:e|es|ed|ing|ison|isons)\b", r"\bversus\b", r"\bvs\.?\b",
    r"\bhow\s+(?:does|do|would|might)\b[^?.!]{0,80}\b(?:relate|apply|applies|fit|connect)\b",
    r"\b(?:relevant|relevance|applicable|applicability)\s+(?:to|for)\b")
_PATIENT_CUE = _compile(r"\b(?:he|she|him|his|hers?|the patient|this patient|that patient|p-\d{3}|the case|this case)\b")
_HISTORY_CUE = _compile(
    r"\b(?:when|trigger\w*|interventions?|treatment\s+so\s+far|progress|history|background|lives?|living|employ\w*|age|"
    r"old|first|previous\w*|prior|relapse\w*|motivation\w*|attend\w*|complet\w*|how\s+(?:is|was|has|did)|"
    r"tell\s+me\s+about|describe|summari[sz]e|received|receiving|social|family|symptoms?)\b")
_RESEARCH_CUE = _compile(
    r"\b(?:research|studies|study|trials?|evidence|literature|papers?|meta-?analys\w*|reviews?|effective\w*|efficacy|"
    r"randomi[sz]ed|findings?|according\s+to|guidelines?|mechanisms?|prevalence|risk\s+factors?|what\s+works|"
    r"medications?\s+(?:are|is)\s+used|psychosocial|published)\b")


def _any(patterns: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


class RuleClassifier:
    def classify(self, question: str, patient_id: str) -> Classification:
        try:
            return self._classify(unicodedata.normalize("NFKC", question or ""), patient_id)
        except Exception:  # a classifier bug must never break answering: fall back to the safe default (retrieve)
            return Classification(RESEARCH, "classifier_error_default_research")

    def _classify(self, text: str, patient_id: str) -> Classification:
        text = " ".join(text.split())
        for code, patterns in _UNSUPPORTED_RULES:
            if _any(patterns, text):
                return Classification(UNSUPPORTED, code)
        mentioned = {f"P-{n}" for n in _OTHER_PATIENT_ID.findall(text)}
        if mentioned - {patient_id.upper()}:
            return Classification(UNSUPPORTED, "other_patient_mentioned")
        patient = _any(_PATIENT_CUE, text)
        research = _any(_RESEARCH_CUE, text)
        if _any(_COMPARISON, text) or (patient and research):
            return Classification(COMPARISON, "comparison_or_patient_with_research_cue")
        if patient and _any(_HISTORY_CUE, text):
            return Classification(HISTORY, "patient_reference_with_history_cue")
        return Classification(RESEARCH, "uncertain_default_research" if not research else "research_cue")
