"""Per-document processing: PDF -> cleaned paragraphs -> chunks. No database access here."""
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from app.ingestion.chunking import Chunk, chunk_paragraphs
from app.ingestion.clean import remove_running_headers_footers
from app.ingestion.config import IngestConfig
from app.ingestion.extract import ExtractionError, file_sha256, open_pdf, read_pages
from app.ingestion.injection import looks_like_injection
from app.ingestion.sections import build_paragraphs
from app.ingestion.tokens import TokenCounter

logger = logging.getLogger("mindevidence.ingestion")

SECTION_TYPES = ("body", "table_or_figure", "references", "front_matter")


@dataclass
class DocResult:
    paper_id: str
    status: str  # ingested | needs_ocr | failed (what is stored in papers.ingest_status)
    reason: str | None = None
    content_sha256: str | None = None
    page_count: int = 0
    low_text_pages: list[int] = field(default_factory=list)
    characters: int = 0
    headers_footers_removed: int = 0
    leader_lines_removed: int = 0
    toc_pages: list[int] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    injection_flags: list[bool] = field(default_factory=list)
    unchanged: bool = False  # set by the CLI: the stored version already matches, nothing was written
    action: str = ""  # written | unchanged | dry-run (set by the CLI)

    def token_stats(self) -> dict:
        counts = [chunk.token_count for chunk in self.chunks]
        if not counts:
            return {"min": 0, "median": 0, "max": 0}
        return {"min": min(counts), "median": int(median(counts)), "max": max(counts)}

    def section_counts(self) -> dict:
        counts = {kind: 0 for kind in SECTION_TYPES}
        for chunk in self.chunks:
            counts[chunk.section_type] += 1
        return counts


def process_pdf(path: Path, paper_id: str, config: IngestConfig, counter: TokenCounter) -> DocResult:
    result = DocResult(paper_id=paper_id, status="failed")
    try:
        result.content_sha256 = file_sha256(path)
        doc = open_pdf(path, config)
        try:
            pages = read_pages(doc)
            toc = doc.get_toc()
        finally:
            doc.close()
    except ExtractionError as error:
        result.reason = str(error)
        return result
    except Exception as error:  # a PDF that PyMuPDF cannot handle must not stop the other documents
        logger.warning("extraction failed for %s: %s", paper_id, type(error).__name__)
        result.reason = "The PDF could not be read."
        return result

    result.page_count = len(pages)
    pages, result.headers_footers_removed = remove_running_headers_footers(pages, config)
    low = {page.number for page in pages if page.chars < config.low_text_min_chars}
    result.low_text_pages = sorted(low)
    result.characters = sum(page.chars for page in pages if page.number not in low)

    if len(low) / len(pages) > config.needs_ocr_ratio:
        result.status = "needs_ocr"
        result.reason = (f"{len(low)} of {len(pages)} pages have almost no text layer; "
                         "the document probably needs OCR, which this project does not do.")
        return result

    paragraphs, stats = build_paragraphs(pages, toc, low)
    result.leader_lines_removed = stats.leader_lines_removed
    result.toc_pages = stats.toc_pages
    result.chunks = chunk_paragraphs(paragraphs, counter, config.chunk_target, config.chunk_max, config.chunk_overlap)
    if not result.chunks:
        result.status = "needs_ocr"
        result.reason = "No usable text was found in the document."
        return result
    result.injection_flags = [looks_like_injection(chunk.text) for chunk in result.chunks]
    result.status = "ingested"
    return result


def chunk_rows(paper_id: str, result: DocResult) -> list[dict]:
    """Database rows for the chunks. Ids and hashes depend only on the document and the chunk text, so they are
    identical on every run over the same input."""
    return [
        {
            "chunk_id": f"{paper_id}-c{chunk.ordinal:04d}", "paper_id": paper_id, "ordinal": chunk.ordinal,
            "text": chunk.text, "token_count": chunk.token_count, "page_start": chunk.page_start,
            "page_end": chunk.page_end, "section_title": chunk.section_title, "section_type": chunk.section_type,
            "text_sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(), "possible_injection": flag,
        }
        for chunk, flag in zip(result.chunks, result.injection_flags)
    ]
