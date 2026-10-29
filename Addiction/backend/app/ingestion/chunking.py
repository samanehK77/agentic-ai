"""Token-aware chunking that respects paragraph and sentence boundaries.

Chunks are built inside one section (same title and section type) only. Whole paragraphs are packed up to the
target size; an oversized paragraph is split at sentence boundaries; a single sentence longer than the maximum is
the only thing ever cut mid-sentence (at word boundaries). The overlap between neighbouring chunks is made of
whole trailing sentences. The token counter is injected, so tests run offline with a fake one.
"""
import re
from dataclasses import dataclass
from itertools import groupby

from app.ingestion.sections import Paragraph
from app.ingestion.tokens import TokenCounter

ABBREVIATIONS = {
    "e.g", "i.e", "et al", "al", "fig", "figs", "vs", "dr", "mr", "mrs", "ms", "no", "nos", "approx", "cf", "ref",
    "refs", "st", "inc", "ltd", "co", "eds", "ed", "vol", "pp", "p", "etc", "ca", "sd", "ci", "or", "rr", "vs",
}
_BOUNDARY = re.compile(r"""([.!?]["'”’)\]]*)\s+(?=["'“‘(\[]?[A-Z0-9])""")


@dataclass(frozen=True)
class Chunk:
    ordinal: int  # 1-based, continuous across the whole document
    text: str
    token_count: int
    page_start: int
    page_end: int
    section_title: str | None
    section_type: str


@dataclass(frozen=True)
class _Sentence:
    text: str
    page: int
    paragraph: int
    cost: int  # tokens without the [CLS]/[SEP] overhead


def split_sentences(text: str) -> list[str]:
    """Splits at '. ', '? ' or '! ' followed by a capital letter or digit, except after common abbreviations
    and single-letter initials ('J. Smith')."""
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        before = text[start:match.start() + 1].rstrip(".!?\"'”’)]")
        last_word = before.split()[-1].lower() if before.split() else ""
        if match.group(1).startswith(".") and (last_word.strip("(") in ABBREVIATIONS or len(last_word.strip("(")) == 1):
            continue
        sentences.append(text[start:match.end()].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _hard_split(sentence: str, counter: TokenCounter, base: int, limit: int) -> list[str]:
    """A sentence longer than the limit is cut at word boundaries (the only mid-sentence cut we ever make)."""
    pieces: list[str] = []
    current: list[str] = []
    for word in sentence.split():
        candidate = " ".join(current + [word])
        if current and counter.count(candidate) - base > limit:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _render(sentences: list[_Sentence]) -> str:
    paragraphs = [" ".join(s.text for s in group) for _, group in groupby(sentences, key=lambda s: s.paragraph)]
    return "\n\n".join(paragraphs)


def _chunk_section(paragraphs: list[Paragraph], counter: TokenCounter, target: int, maximum: int, overlap: int,
                   base: int) -> list[tuple[str, int, int, int]]:
    """Returns (text, token_count, page_start, page_end) per chunk."""
    cur: list[_Sentence] = []
    cur_cost = 0
    new = 0  # sentences added since the last flush (not counting carried-over overlap)
    out: list[tuple[str, int, int, int]] = []
    budget_target, budget_max = target - base, maximum - base

    def emit() -> None:
        text = _render(cur)
        count = counter.count(text)
        pages = [s.page for s in cur]
        out.append((text, count, min(pages), max(pages)))

    def flush() -> None:
        nonlocal cur, cur_cost, new
        if new == 0:
            return
        emit()
        tail: list[_Sentence] = []
        used = 0
        for sentence in reversed(cur[1:]):  # never carry the whole chunk
            if used + sentence.cost > overlap:
                break
            tail.insert(0, sentence)
            used += sentence.cost
        cur, cur_cost, new = tail, used, 0

    def add(sentence: _Sentence) -> None:
        nonlocal cur, cur_cost, new
        if new == 0 and cur and cur_cost + sentence.cost > budget_max:
            cur, cur_cost = [], 0  # the carried overlap would push this chunk over the limit
        cur.append(sentence)
        cur_cost += sentence.cost
        new += 1

    for index, para in enumerate(paragraphs):
        pieces: list[str] = []
        for sentence in split_sentences(para.text):
            if counter.count(sentence) - base > budget_max:
                pieces.extend(_hard_split(sentence, counter, base, budget_max))
            else:
                pieces.append(sentence)
        sentences = [_Sentence(p, para.page, index, counter.count(p) - base) for p in pieces]
        total = sum(s.cost for s in sentences)
        if cur_cost + total <= budget_target:
            for sentence in sentences:
                add(sentence)
        elif new > 0 and total <= budget_target:
            flush()
            if cur_cost + total <= budget_max:
                for sentence in sentences:
                    add(sentence)
                continue
            for sentence in sentences:
                if new > 0 and cur_cost + sentence.cost > budget_target:
                    flush()
                add(sentence)
        else:
            for sentence in sentences:
                if new > 0 and cur_cost + sentence.cost > budget_target:
                    flush()
                add(sentence)
    flush()
    return out


def chunk_paragraphs(paragraphs: list[Paragraph], counter: TokenCounter, target: int, maximum: int,
                     overlap: int) -> list[Chunk]:
    base = counter.count("")  # the fixed [CLS]/[SEP] overhead (0 for the fake counter)
    chunks: list[Chunk] = []
    for (title, kind), group in groupby(paragraphs, key=lambda p: (p.section_title, p.section_type)):
        for text, count, start, end in _chunk_section(list(group), counter, target, maximum, overlap, base):
            if not text.strip():
                continue
            chunks.append(Chunk(len(chunks) + 1, text, count, start, end, title, kind))
    return chunks
