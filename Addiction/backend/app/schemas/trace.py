"""API shapes for the workflow's decisions and execution trace (Batch 08). Statistics only: no question, patient or chunk text."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ClassificationOut(BaseModel):
    label: Literal["unsupported_request", "comparison", "patient_history_lookup", "research_question"]
    reason_code: str


class RetrievalDecisionOut(BaseModel):
    needed: bool
    reason_code: str
    reason: str = Field(description="Written by the backend, never by the model.")


class EvidenceAssessmentOut(BaseModel):
    sufficient: bool
    level: Literal["none", "weak", "adequate"]
    reason_code: str
    retrieved: int
    usable: int
    excluded_possible_injection: int
    top_similarity: float
    retry_follow_up: bool = False


class ExecutionTraceEvent(BaseModel):
    node: str
    status: Literal["ok", "skipped", "ended", "error"]
    started_at: str | None = None
    duration_ms: int = 0
    reason_code: str | None = None
    reason: str = ""
    counts: dict[str, int | float | bool] = Field(default_factory=dict)
    chunk_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    correlation_id: str | None = None


class TraceResponse(BaseModel):
    message_id: UUID
    graph_version: str | None
    execution_trace: list[ExecutionTraceEvent]
