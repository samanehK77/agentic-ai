"""Turns cleaned pages into paragraphs labelled with a section title and a section type.

Everything here is a heuristic (outline, font sizes, a few keywords). Section titles are never invented:
when neither the PDF outline nor a heading heuristic gives one, the title stays None.
"""
import re
from dataclasses import dataclass, field
from statistics import median

from app.ingestion.clean import is_leader_line, normalize_text, strip_leader_lines
from app.ingestion.extract import Block, Page

REFERENCES_HEADING = re.compile(
    r"^(?:(?:\d+|[ivx]+)[.)]?\s*)?((?:additional |other )?references?(?: cited| list)?(?: to studies .{0,80})?|"
    r"bibliography|literature cited|works cited)\s*:?$", re.IGNORECASE)
AFTER_REFERENCES = re.compile(r"^(?:\w+\s*)?(appendi(?:x|ces)|annex(?:es)?|supplement\w*|glossary|characteristics of|"
                              r"data and analyses|additional tables|acknowledg\w+)\b", re.IGNORECASE)
CAPTION = re.compile(r"^(table|figure|fig\.|box|chart|flowchart)\s*[0-9A-Z]", re.IGNORECASE)
CONTENTS_HEADING = re.compile(r"^(table of )?contents$", re.IGNORECASE)
ENDS_WITH_PAGE_NUMBER = re.compile(r"\s\d{1,3}$")

MAX_TITLE_CHARS = 200
_SPACED_LETTERS = re.compile(r"\b(?:[A-Za-z] ){3,}[A-Za-z]\b")  # at least four single letters in a row
_DOUBLED_REFERENCES = re.compile(r"^references\s+(?=references)", re.IGNORECASE)


def despace_heading(text: str) -> str:
    """'R E F E R E N C E S References to ...' -> 'REFERENCES References to ...' -> 'References to ...'
    (some documents letter-space their running section labels)."""
    text = _SPACED_LETTERS.sub(lambda m: m.group().replace(" ", ""), text)
    return _DOUBLED_REFERENCES.sub("", text)


@dataclass(frozen=True)
class Paragraph:
    text: str
    page: int
    section_title: str | None
    section_type: str  # body | table_or_figure | references | front_matter


@dataclass
class SectionStats:
    leader_lines_removed: int = 0
    toc_pages: list[int] = field(default_factory=list)
    front_matter_end: int = 0
    used_outline: bool = False
    headings_found: int = 0


def is_table_like(block: Block, text: str) -> bool:
    if CAPTION.match(text):
        return True
    letters = sum(c.isalpha() for c in text)
    digits = sum(c.isdigit() for c in text)
    if block.n_lines >= 5 and block.avg_line_len < 28:
        return True  # many short lines: a table, a flowchart or a list of labels
    return len(text) >= 20 and digits > 0.4 * (letters + digits)


def body_font_size(pages: list[Page]) -> float:
    weighted: list[float] = []
    for page in pages:
        for block in page.blocks:
            chars = len(block.text)
            if chars >= 60 and block.size > 0:
                weighted.extend([block.size] * min(chars // 20, 50))
    return median(weighted) if weighted else 0.0


def is_heading_block(block: Block, text: str, body_size: float) -> bool:
    if not text or block.n_lines > 3 or len(text) > 120 or text.endswith((".", ",", ";")):
        return False
    letters = sum(c.isalpha() for c in text)
    if letters < 3 or sum(c.isdigit() for c in text) > 0.5 * len(text) or CAPTION.match(text):
        return False
    if body_size <= 0:
        return False
    return block.size >= body_size * 1.15 or (block.bold and block.size >= body_size * 0.95 and len(text) <= 90)


def _is_toc_page(page: Page) -> bool:
    lines = [line for block in page.blocks for line in block.text.split("\n")]
    if len(lines) < 3:
        return False
    leaders = sum(is_leader_line(line) for line in lines)
    if leaders >= 0.3 * len(lines):
        return True
    first = [normalize_text(line) for line in lines[:6]]
    if any(CONTENTS_HEADING.match(line) for line in first):
        numbered = sum(bool(ENDS_WITH_PAGE_NUMBER.search(line)) for line in lines)
        return numbered >= 0.4 * len(lines) or len(lines) <= 40
    return False


def _outline_lookup(toc: list[list]):
    entries = sorted(((int(page), index, str(title)) for index, (_, title, page) in enumerate(toc) if int(page) >= 1))

    def title_for(page: int) -> str | None:
        found = None
        for entry_page, _, title in entries:
            if entry_page <= page:
                found = title
            else:
                break
        return normalize_text(found)[:MAX_TITLE_CHARS] if found else None

    return title_for


def build_paragraphs(pages: list[Page], toc: list[list], low_text_pages: set[int]) -> tuple[list[Paragraph], SectionStats]:
    stats = SectionStats(used_outline=bool(toc))
    usable = [p for p in pages if p.number not in low_text_pages]

    # 1. Dot leaders out; find table-of-contents pages.
    cleaned: list[Page] = []
    for page in usable:
        blocks = []
        for block in page.blocks:
            text, removed = strip_leader_lines(block.text)
            stats.leader_lines_removed += removed
            if text.strip():
                blocks.append(Block(**{**block.__dict__, "text": text, "n_lines": len(text.split("\n"))}))
        cleaned.append(page.with_blocks(blocks))
    toc_pages = [p.number for p in pages[: max(12, len(pages) // 6)] if p.number not in low_text_pages and _is_toc_page(p)]
    stats.toc_pages = toc_pages
    # Front matter: everything up to the last table-of-contents page; without one, only a title page (documents of 4+ pages).
    stats.front_matter_end = max(toc_pages) if toc_pages else (1 if len(pages) >= 4 else 0)

    body_size = body_font_size(cleaned)
    title_for = _outline_lookup(toc) if toc else None

    paragraphs: list[Paragraph] = []
    title: str | None = None
    in_references = False
    for page in cleaned:
        for block in page.blocks:
            text = normalize_text(block.text)
            if not any(c.isalnum() for c in text):
                continue
            if block.n_lines <= 3 and len(text) <= 120:
                text = despace_heading(text)
            if title_for:
                new_title = title_for(page.number)
                if new_title != title:
                    title = new_title
                    in_references = bool(title and REFERENCES_HEADING.match(title))
            elif is_heading_block(block, text, body_size):
                stats.headings_found += 1
                title = text[:MAX_TITLE_CHARS]
                if REFERENCES_HEADING.match(text):
                    in_references = True
                elif in_references and AFTER_REFERENCES.match(text):
                    in_references = False
                continue  # the heading is stored as the section title, not as body text
            if REFERENCES_HEADING.match(text) and block.n_lines <= 2:
                in_references = True
                if not title_for:
                    title = text
                continue
            if page.number <= stats.front_matter_end:
                kind = "front_matter"
            elif in_references:
                kind = "references"
            elif is_table_like(block, text):
                kind = "table_or_figure"
            else:
                kind = "body"
            paragraphs.append(Paragraph(text=text, page=page.number, section_title=title, section_type=kind))
    return paragraphs, stats
