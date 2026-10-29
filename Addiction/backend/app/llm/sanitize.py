"""Neutralizes untrusted text before it goes into a prompt block.

Patient text, chunk text, earlier conversation turns and the user's question are untrusted data. They are placed only in
delimited blocks of the user message, and the angle brackets that form the delimiters are replaced by look-alike
characters, so the text cannot close a block or open a fake one.
"""
import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_TABLE = {ord("<"): "‹", ord(">"): "›"}  # single angle quotation marks


def neutralize(text: str, max_chars: int | None = None) -> str:
    cleaned = _CONTROL.sub(" ", unicodedata.normalize("NFKC", text or ""))
    cleaned = cleaned.translate(_TABLE)
    if max_chars is not None and len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


def attribute(value: str, max_chars: int = 160) -> str:
    """Safe text for an attribute value inside a tag: no quotes, no brackets, one line."""
    return " ".join(neutralize(value, max_chars).replace('"', "'").split())
