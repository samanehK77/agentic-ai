"""Helpers for the answer tests: a mock model that answers from the evidence it is shown."""
import json
import re

from tests.fake_llm import answer_json, section

CHUNK_RE = re.compile(r'<chunk alias="(S\d+)"[^>]*>\n(.*?)\n</chunk>', re.S)


def parts(payload: dict) -> tuple[str, str, str]:
    """(mode, system text, user text) of a request payload."""
    system = payload["messages"][0]["content"]
    user = payload["messages"][1]["content"]
    mode = re.search(r"MODE: (\w+)", system).group(1)
    return mode, system, user


def faithful_responder(payload: dict, call: int) -> str:
    """A well-behaved model: quotes the first chunk it was shown (rag/both), labels general knowledge honestly."""
    mode, _, user = parts(payload)
    chunks = CHUNK_RE.findall(user)
    sections = [section("patient_fact", "The hypothetical patient is described in the synthetic record.")]
    if mode in ("rag", "both") and chunks:
        alias, text = chunks[0]
        sections.append(section("research_finding", "The first retrieved chunk reports a finding.", (alias, " ".join(text.split()[:6]))))
        sections.append(section("interpretation", "This is relevant to the case, for qualified clinicians to interpret."))
    if mode in ("general_knowledge", "both"):
        sections.append(section("general_knowledge", "In general, psychosocial support is often combined with other care."))
    return answer_json(sections, limitations="Based on a few retrieved chunks.")


def scripted(*contents):
    """A responder that returns the given contents in order (the last one repeats)."""
    def responder(payload, call):
        return contents[min(call, len(contents)) - 1]
    return responder


def user_text(call: dict) -> str:
    return call["payload"]["messages"][1]["content"]


def system_text(call: dict) -> str:
    return call["payload"]["messages"][0]["content"]


def all_request_text(provider) -> str:
    return json.dumps([c["payload"] for c in provider.calls])
