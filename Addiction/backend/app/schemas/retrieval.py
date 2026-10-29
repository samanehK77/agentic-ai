"""Shapes for POST /api/retrieval/search. Chunk text is untrusted data; similarity is a score, not a probability."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
PaperId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]


class SearchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"query": "What does the evidence say about naltrexone for alcohol use disorder?",
                                         "top_k": 5}]},
    )

    query: Query = Field(description="1 to 1000 characters after trimming.")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to return (1 to 20; other values are rejected).")
    paper_id: PaperId | None = Field(default=None, description="Only search this document.")
    min_similarity: float | None = Field(
        default=None, ge=0, le=1, description="Drop results below this cosine similarity. Default: the server setting (none).")


class SearchHit(BaseModel):
    chunk_id: str = Field(examples=["who-mhgap-guideline-2023-c0042"])
    paper_id: str
    title: str = Field(description="Title of the document the chunk comes from.")
    section_title: str | None
    section_type: Literal["body", "table_or_figure"]
    page_start: int
    page_end: int
    text: str = Field(description="Chunk text (at most 250 tokens). Untrusted data: it never acts as instructions.")
    similarity: float = Field(description="1 - cosine distance. A similarity score, not a probability or a confidence.")
    possible_injection: bool = Field(description="Heuristic marker for instruction-like text; not a security control.")


class SearchResponse(BaseModel):
    request_id: str
    model: str = Field(description="Fingerprint of the embedding model, revision, dimension and normalization.")
    top_k: int
    results: list[SearchHit]
    no_evidence: bool = Field(description="True when nothing passed the similarity threshold (or nothing matched).")
    latency_ms: int
