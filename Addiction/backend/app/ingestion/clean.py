"""Text cleaning: Unicode normalization, hyphen joining, dot leaders and repeating headers/footers.

All of this is heuristic. It is tuned for the project's five documents and will misjudge some pages.
"""
import math
import re
import unicodedata
from collections import defaultdict

from app.ingestion.config import IngestConfig
from app.ingestion.extract import Block, Page

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SOFT_HYPHEN_BREAK = re.compile("­[ \t]*(?=[a-z])")
_HYPHEN_BREAK = re.compile(r"(?<=\w)-[ \t]*\n[ \t]*(?=[a-z])")
_SPACES = re.compile(r"[ \t  -​  　]+")
_LEADER = re.compile(r"(\.{4,}|(?:\. ){4,}|…{2,}|(?:· ?){4,})")


def normalize_text(text: str) -> str:
    """NFKC, soft hyphens and control characters removed, hyphenated line breaks joined (only when the next
    fragment starts in lowercase), line breaks and runs of whitespace collapsed to single spaces."""
    text = unicodedata.normalize("NFKC", text)
    text = _SOFT_HYPHEN_BREAK.sub("", text).replace("­", "")
    text = _CONTROL.sub(" ", text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n"))
    text = _HYPHEN_BREAK.sub("", text)
    text = text.replace("\n", " ")
    return _SPACES.sub(" ", text).strip()


def is_leader_line(line: str) -> bool:
    """A table-of-contents style line: a dot leader (or a long run of dots) followed by a page number or nothing."""
    return _LEADER.search(line) is not None


def strip_leader_lines(block_text: str) -> tuple[str, int]:
    kept = [line for line in block_text.split("\n") if not is_leader_line(line)]
    return "\n".join(kept), len(block_text.split("\n")) - len(kept)


def repeat_key(text: str) -> str:
    """Digits normalized, so 'Page 7' and 'Page 8' (or a bare page number) count as the same running line."""
    collapsed = " ".join(unicodedata.normalize("NFKC", text).lower().split())
    return re.sub(r"\d+", "#", collapsed)


_PAGE_NUMBER = re.compile(r"^(page\s*)?([ivxlcdm]{1,7}|\d{1,4})(\s*(of|/)\s*\d{1,4})?$", re.IGNORECASE)


def _in_margin(block: Block, page: Page, fraction: float) -> bool:
    """The block starts in the top margin or ends in the bottom margin of the page."""
    return block.y0 <= page.height * fraction or block.y1 >= page.height * (1 - fraction)


def _is_page_number(block: Block) -> bool:
    return len(block.text) <= 14 and _PAGE_NUMBER.match(" ".join(block.text.split())) is not None


def remove_running_headers_footers(pages: list[Page], config: IngestConfig) -> tuple[list[Page], int]:
    """Removes running headers and footers: blocks in the top or bottom margin that
    (1) are a bare page number (digits or roman numerals), or
    (2) repeat (digits normalized) on at least header_footer_ratio of the pages, or
    (3) are short (at most two lines) and repeat on at least 3 pages and 3% of the pages (chapter running heads).
    Returns the cleaned pages and the number of blocks removed. Documents under 4 pages are left alone."""
    if len(pages) < 4:
        return pages, 0
    seen: dict[str, set[int]] = defaultdict(set)
    for page in pages:
        for block in page.blocks:
            if _in_margin(block, page, config.margin_fraction):
                seen[repeat_key(block.text)].add(page.number)
    needed = max(3, math.ceil(config.header_footer_ratio * len(pages)))
    needed_short = max(3, math.ceil(0.03 * len(pages)))
    repeating = {key for key, where in seen.items() if len(where) >= needed}
    short_repeating = {key for key, where in seen.items() if len(where) >= needed_short}
    removed = 0
    cleaned = []
    for page in pages:
        kept = []
        for block in page.blocks:
            key = repeat_key(block.text)
            if _in_margin(block, page, config.margin_fraction) and (
                    _is_page_number(block) or key in repeating
                    or (key in short_repeating and block.n_lines <= 2 and len(block.text) <= 80)):
                removed += 1
            else:
                kept.append(block)
        cleaned.append(page.with_blocks(kept))
    return cleaned, removed
