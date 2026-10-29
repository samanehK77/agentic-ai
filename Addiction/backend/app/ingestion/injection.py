"""A simple marker for instruction-like phrases inside document text.

This is only a flag for administrator review. It is NOT a security control: retrieved text stays untrusted data
in every later batch no matter what this returns.
"""
import re

PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts?|messages)",
    r"disregard (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts?)",
    r"forget (all |your |the )?(previous|prior|earlier) (instructions|prompts?)",
    r"\bsystem prompt\b",
    r"\byou are now\b",
    r"\bact as (a|an|the)\b",
    r"new instructions?\s*:",
    r"do not (tell|reveal to) the user",
    r"reveal (your|the) (hidden |secret )?(instructions|prompt)",
    r"\b(developer|admin) mode\b",
]
_REGEX = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)


def looks_like_injection(text: str) -> bool:
    return _REGEX.search(text) is not None
