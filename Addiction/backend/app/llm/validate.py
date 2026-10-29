"""Server-side validation of the model's structured answer. The model is never trusted:

1. Short aliases (S1..Sn) are mapped back to the real chunk ids; unknown aliases are dropped and flagged.
2. Each quote is checked against the cited chunk text (whitespace, case and quote-style normalized). `verified=true`
   proves only that the quote EXISTS in that chunk, not that it supports the claim.
3. A research_finding section without any valid citation is moved to unsupported_claims.
4. Section kinds are enforced per mode; the assembled text must fit the 8000-character message limit.
5. Sections with dosing instructions or individual treatment directives are withheld (safety.py).
"""
import re
import unicodedata
from dataclasses import dataclass, field

from app.llm.safety import WITHHELD_NOTE, check_output
from app.llm.schema import ModelAnswer

MAX_QUOTE_WORDS = 25
CONTENT_LIMIT = 8000  # chat_messages.content check constraint

KIND_LABELS = {
    "patient_fact": "Patient fact (synthetic)", "research_finding": "Research finding",
    "general_knowledge": "General knowledge (not from the documents)", "interpretation": "Interpretation",
    "withheld": "Withheld",
}


@dataclass
class EvidenceItem:
    """One chunk shown to the model (alias set) or retrieved but kept out of the prompt (alias None)."""

    chunk_id: str
    paper_id: str
    title: str
    section_title: str | None
    section_type: str
    page_start: int
    page_end: int
    text: str
    similarity: float
    possible_injection: bool
    alias: str | None = None
    excluded_reason: str | None = None
    text_sha256: str = ""


@dataclass
class ValidatedAnswer:
    sections: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    unsupported_claims: list[dict] = field(default_factory=list)
    conflicting_evidence: list[str] = field(default_factory=list)
    limitations: str = ""
    flags: list[str] = field(default_factory=list)
    content: str = ""


_QUOTE_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_EDGES = re.compile(r"^[\s\"'.…\[\]()]+|[\s\"'.…\[\]()]+$")


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_MAP).lower()
    text = text.replace("...", " ").replace("…", " ")
    return " ".join(text.split())


def verify_quote(quote: str, chunk_text: str) -> bool:
    """True if the (short) quote appears in the chunk text after normalization."""
    cleaned = _EDGES.sub("", normalize_for_match(quote))
    if not cleaned or len(cleaned.split()) > MAX_QUOTE_WORDS:
        return False
    return cleaned in normalize_for_match(chunk_text)


def assemble_content(sections: list[dict], conflicts: list[str], limitations: str, unsupported: list[dict]) -> str:
    parts = []
    for section in sections:
        label = KIND_LABELS[section["kind"]]
        cites = ", ".join(dict.fromkeys(c["alias"] for c in section["citations"]))
        parts.append(f"[{label}{' ' + cites if cites else ''}] {section['text']}")
    if conflicts:
        parts.append("Conflicting evidence:\n" + "\n".join(f"- {c}" for c in conflicts))
    if limitations.strip():
        parts.append(f"Limitations: {limitations.strip()}")
    if unsupported:
        parts.append("Unsupported claims (no valid citation, not part of the answer):\n"
                     + "\n".join(f"- {u['text']}" for u in unsupported))
    return "\n\n".join(parts)


def validate_answer(answer: ModelAnswer, mode: str, evidence: list[EvidenceItem]) -> ValidatedAnswer:
    by_alias = {item.alias: item for item in evidence if item.alias}
    out = ValidatedAnswer(conflicting_evidence=list(answer.conflicting_evidence), limitations=answer.limitations.strip())
    flags: list[str] = []

    def flag(code: str) -> None:
        if code not in flags:
            flags.append(code)

    seen_citations: set[tuple[str, str]] = set()
    for section in answer.sections:
        kind = section.kind
        # --- kind rules per mode
        if mode == "general_knowledge":
            if kind == "research_finding":
                kind = "general_knowledge"  # research-type statements are labelled general knowledge in this mode
                flag("research_finding_relabelled_general_knowledge")
        elif mode == "rag" and kind == "general_knowledge":
            flag("general_knowledge_rejected")
            continue

        # --- citations
        citations: list[dict] = []
        # Only research findings and interpretations may cite documents, and only when evidence was provided.
        may_cite = mode != "general_knowledge" and bool(by_alias) and kind in ("research_finding", "interpretation")
        if not may_cite:
            if section.citations:
                flag("citations_dropped")
        else:
            for cited in section.citations:
                item = by_alias.get(cited.alias)
                if item is None:
                    flag("unknown_alias_dropped")
                    continue
                verified = verify_quote(cited.quote, item.text)
                if not verified:
                    flag("unverified_quote")
                record = {"alias": cited.alias, "chunk_id": item.chunk_id, "quote": cited.quote.strip(), "verified": verified}
                citations.append(record)
                key = (cited.alias, record["quote"])
                if key not in seen_citations:
                    seen_citations.add(key)
                    out.citations.append(record)

        # --- research findings need a valid citation
        if kind == "research_finding" and not citations:
            out.unsupported_claims.append({"text": section.text.strip(), "reason": "no_valid_citation"})
            flag("unsupported_research_claim")
            continue

        text = section.text.strip()
        # --- safety: dosing instructions and individual treatment directives are withheld
        problems = check_output(text)
        if problems:
            for code in problems:
                flag(code)
            flag("section_withheld")
            out.sections.append({"kind": "withheld", "text": WITHHELD_NOTE, "citations": []})
            continue
        out.sections.append({"kind": kind, "text": text, "citations": citations})

    # conflicts / limitations / unsupported claims are generated text too
    safe_conflicts = []
    for item in out.conflicting_evidence:
        if check_output(item):
            flag("section_withheld")
            safe_conflicts.append(WITHHELD_NOTE)
        else:
            safe_conflicts.append(item.strip())
    out.conflicting_evidence = safe_conflicts
    if out.limitations and check_output(out.limitations):
        flag("section_withheld")
        out.limitations = WITHHELD_NOTE
    for claim in out.unsupported_claims:
        if check_output(claim["text"]):
            claim["text"] = WITHHELD_NOTE

    # --- the assembled text must fit the message limit: drop trailing sections deterministically
    content = assemble_content(out.sections, out.conflicting_evidence, out.limitations, out.unsupported_claims)
    while len(content) > CONTENT_LIMIT and out.sections:
        out.sections.pop()
        flag("truncated_to_fit")
        content = assemble_content(out.sections, out.conflicting_evidence, out.limitations, out.unsupported_claims)
    if len(content) > CONTENT_LIMIT:  # conflicts/limitations alone are too long (cannot happen within the schema limits)
        content = content[:CONTENT_LIMIT]
    # citations list only keeps those still used by a remaining section
    used = {(c["alias"], c["quote"]) for s in out.sections for c in s["citations"]}
    out.citations = [c for c in out.citations if (c["alias"], c["quote"]) in used]
    out.content = content or "No supported answer could be produced for this question."
    out.flags = flags
    return out
