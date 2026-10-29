"""PDF text extraction with PyMuPDF (text layer only; there is no OCR anywhere in this project)."""
import hashlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import pymupdf

from app.ingestion.config import IngestConfig


class ExtractionError(Exception):
    """The PDF cannot be used. The message is short and safe to store and show (no paths, no stack trace)."""


@dataclass(frozen=True)
class Block:
    page: int  # 1-based
    text: str  # lines joined with "\n"
    x0: float
    y0: float
    x1: float
    y1: float
    size: float  # dominant font size
    bold: bool
    n_lines: int
    avg_line_len: float


@dataclass(frozen=True)
class Page:
    number: int
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len("".join(block.text.split())) for block in self.blocks)

    def with_blocks(self, blocks: list[Block]) -> "Page":
        return replace(self, blocks=blocks)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def open_pdf(path: Path, config: IngestConfig) -> pymupdf.Document:
    size_mb = os.stat(path).st_size / (1024 * 1024)
    if size_mb > config.max_pdf_mb:
        raise ExtractionError(f"The file is larger than the allowed {config.max_pdf_mb} MB.")
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise ExtractionError("The file could not be opened as a PDF (it may be corrupt).") from None
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise ExtractionError("The PDF is encrypted or password protected.")
        if doc.page_count < 1:
            raise ExtractionError("The PDF has no pages.")
        if doc.page_count > config.max_pdf_pages:
            raise ExtractionError(f"The PDF has more than the allowed {config.max_pdf_pages} pages.")
    except ExtractionError:
        doc.close()
        raise
    return doc


def _read_block(page_number: int, raw: dict) -> Block | None:
    lines: list[str] = []
    sizes: dict[float, int] = {}
    bold_chars = total_chars = 0
    for line in raw.get("lines", []):
        pieces = []
        for span in line.get("spans", []):
            text = span.get("text", "")
            pieces.append(text)
            weight = len(text.strip())
            if weight:
                size = round(span.get("size", 0.0), 1)
                sizes[size] = sizes.get(size, 0) + weight
                total_chars += weight
                if span.get("flags", 0) & 16 or "bold" in span.get("font", "").lower():
                    bold_chars += weight
        line_text = "".join(pieces).rstrip()
        if line_text.strip():
            lines.append(line_text)
    if not lines:
        return None
    x0, y0, x1, y1 = raw["bbox"]
    dominant = max(sizes, key=sizes.get) if sizes else 0.0
    return Block(
        page=page_number, text="\n".join(lines), x0=x0, y0=y0, x1=x1, y1=y1, size=dominant,
        bold=total_chars > 0 and bold_chars / total_chars > 0.6, n_lines=len(lines),
        avg_line_len=sum(len(line) for line in lines) / len(lines))


def order_blocks(blocks: list[Block], width: float) -> list[Block]:
    """Reading order. Single column: top to bottom (left to right on the same line).
    Two columns (blocks cluster in the left and right halves and few span the middle): left column, then right.
    Heuristic: tables, sidebars and flowcharts can still come out in a surprising order."""
    if not blocks:
        return []
    mid = width / 2
    left = [b for b in blocks if b.x1 <= mid * 1.05]
    right = [b for b in blocks if b.x0 >= mid * 0.95]
    spanning = [b for b in blocks if b not in left and b not in right]
    if len(left) >= 3 and len(right) >= 3 and len(spanning) <= 0.2 * len(blocks):
        column_top = min(b.y0 for b in left + right)
        head = [b for b in spanning if b.y1 <= column_top + 2]
        tail = [b for b in spanning if b not in head]
        by_y = lambda items: sorted(items, key=lambda b: (b.y0, b.x0))  # noqa: E731
        return by_y(head) + by_y(left) + by_y(right) + by_y(tail)
    return sorted(blocks, key=lambda b: (round(b.y0 / 4), b.x0))


def read_pages(doc: pymupdf.Document) -> list[Page]:
    pages = []
    for index in range(doc.page_count):
        page = doc[index]
        raw = page.get_text("dict")
        blocks = [b for b in (_read_block(index + 1, raw_block) for raw_block in raw.get("blocks", [])
                              if raw_block.get("type") == 0) if b is not None]
        width, height = page.rect.width, page.rect.height
        pages.append(Page(number=index + 1, width=width, height=height, blocks=order_blocks(blocks, width)))
    return pages
