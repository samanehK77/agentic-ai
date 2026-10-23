"""Paper metadata only: no document text, no chunks and no file paths (those arrive in Batch 05)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from db.models import VOCAB


class PaperOut(BaseModel):
    paper_id: str = Field(examples=["who-mhgap-guideline-2023"])
    title: str
    document_type: Literal[*VOCAB["document_type"]]
    publisher: str = Field(description="'unknown' when not recorded.")
    publication_year: str = Field(description="Four digits, or 'unknown' when not recorded.", examples=["2023"])
    source_note: str
    ingest_status: Literal[*VOCAB["ingest_status"]]
    created_at: datetime
