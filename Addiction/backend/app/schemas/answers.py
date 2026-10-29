"""Shapes for answering a question in a chat session. Chat text and chunk text are untrusted data."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.trace import ClassificationOut, EvidenceAssessmentOut, ExecutionTraceEvent, RetrievalDecisionOut
from db.models import VOCAB

Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Mode = Literal[*VOCAB["chat_mode"]]


class MessageCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"content": "Which medications are used to treat opioid addiction?", "mode": "rag"}]},
    )

    content: Content = Field(description="The question, 1 to 1000 characters after trimming.")
    mode: Mode = Field(description="general_knowledge (no retrieval), rag (documents only) or both.")


class SectionCitation(BaseModel):
    alias: str = Field(examples=["S1"])
    chunk_id: str
    quote: str
    verified: bool = Field(description="True if the quote appears in the cited chunk. It does not prove the quote supports the claim.")


class SectionOut(BaseModel):
    kind: Literal["patient_fact", "research_finding", "general_knowledge", "interpretation", "withheld"]
    text: str
    citations: list[SectionCitation]


class CitationOut(BaseModel):
    citation_id: str = Field(description="The real chunk id (same as chunk_id).")
    alias: str
    chunk_id: str
    paper_id: str | None
    source_title: str | None
    section_title: str | None
    page_start: int | None
    page_end: int | None
    quote: str
    verified: bool
    stale: bool = Field(description="True if the chunk no longer exists or its text changed since the answer was written.")


class EvidenceOut(BaseModel):
    alias: str | None = Field(description="S-number used in the prompt; null if the chunk was kept out of the prompt.")
    chunk_id: str
    paper_id: str | None
    source_title: str | None
    section_title: str | None
    section_type: str | None
    page_start: int | None
    page_end: int | None
    text: str | None = Field(description="Chunk text (untrusted data); null if the chunk no longer exists.")
    similarity: float = Field(description="Cosine similarity at retrieval time: a score, not a probability.")
    cited: bool
    possible_injection: bool
    excluded_reason: str | None = Field(description="possible_injection or context_budget when the chunk was kept out of the prompt.")
    stale: bool


class UnsupportedClaim(BaseModel):
    text: str
    reason: str


class SafetyOut(BaseModel):
    escalation: bool
    notice: str | None
    flags: list[str]


class GenerationOut(BaseModel):
    llm_called: bool
    model: str | None = None
    prompt_version: str | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    repair_attempted: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class TraceEvent(BaseModel):
    type: Literal["retrieval", "generation", "validation", "safety"]
    label: str
    detail: str = ""
    latency_ms: int | None = None


class AnswerOut(BaseModel):
    request_id: str | None = None
    session_id: UUID
    message_id: UUID
    user_message_id: UUID | None = None
    created_at: datetime
    mode: Mode
    no_evidence: bool
    content: str = Field(description="The assembled plain text of the answer (also what is stored as the message).")
    sections: list[SectionOut]
    citations: list[CitationOut]
    evidence: list[EvidenceOut]
    unsupported_claims: list[UnsupportedClaim]
    conflicting_evidence: list[str]
    limitations: str
    safety: SafetyOut
    generation: GenerationOut
    trace: list[TraceEvent] = Field(description="The short user-facing activity list (unchanged since Batch 07).")
    # Batch 08 (additive): what the workflow decided and did. Statistics only; null for answers stored before the graph.
    classification: ClassificationOut | None = None
    retrieval_decision: RetrievalDecisionOut | None = None
    evidence_assessment: EvidenceAssessmentOut | None = None
    execution_trace: list[ExecutionTraceEvent] | None = Field(
        default=None, description="One entry per workflow node, in graph order; nodes that did not run are 'skipped' with the reason.")
    graph_version: str | None = None
