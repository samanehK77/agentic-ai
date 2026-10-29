"""Administrator-only views of the ingestion state. Never includes the file name, a path or the file hash."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from db.models import VOCAB


class AdminPaperOut(BaseModel):
    paper_id: str = Field(examples=["who-mhgap-guideline-2023"])
    title: str
    document_type: Literal[*VOCAB["document_type"]]
    publisher: str
    publication_year: str
    doi: str | None
    metadata_source: Literal[*VOCAB["metadata_source"]] = Field(description="Where the metadata came from.")
    ingest_status: Literal[*VOCAB["ingest_status"]]
    ingest_note: str | None = Field(description="Short reason for failed or needs_ocr documents.")
    page_count: int | None
    low_text_page_count: int
    chunk_count: int
    chunking_version: str | None
    ingested_at: datetime | None


class AdminPaperDetail(AdminPaperOut):
    low_text_pages: list[int] = Field(description="1-based numbers of pages skipped for having almost no text.")
    chunks_by_section_type: dict[str, int]


class ChunkOut(BaseModel):
    """Full chunk text: copyrighted source material, returned to administrators only."""

    chunk_id: str = Field(examples=["who-mhgap-guideline-2023-c0042"])
    paper_id: str
    ordinal: int
    text: str
    token_count: int
    page_start: int
    page_end: int
    section_title: str | None
    section_type: Literal[*VOCAB["section_type"]]
    possible_injection: bool = Field(description="Heuristic flag for admin review; not a security control.")
    created_at: datetime
