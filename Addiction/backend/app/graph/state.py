"""The typed state of one run. Inputs are set once; nodes return partial updates. `execution_trace` and `user_trace`
are append-only (reducer: concatenation). Chunk text and patient text may sit in memory here during a run, but the state
is never persisted as a whole and never traced: only the final response and the statistics-only trace are stored."""
import operator
from typing import Annotated, Any

from pydantic import BaseModel, Field


class GraphState(BaseModel):
    # ---- inputs
    user_id: str
    session_id: str
    patient_id: str
    mode: str
    question: str
    request_id: str | None = None
    patient_profile: dict | None = None  # the validated patient record (read once by the service)
    history: list[tuple[str, str]] = Field(default_factory=list)  # recent (role, text) turns

    # ---- decisions
    safety: dict = Field(default_factory=lambda: {"triggered": False, "personal": False, "escalation": False, "flags": []})
    classification: dict | None = None  # {label, reason_code}
    retrieval_decision: dict | None = None  # {needed, reason_code, reason}
    evidence_assessment: dict | None = None  # {sufficient, level, reason_code, ...counts}
    termination: dict | None = None  # {reason_code, message}: set when the run ends without a model answer

    # ---- working data
    retrieval_query: str | None = None
    attempts: int = 0  # retrieval attempts so far (at most 2)
    evidence: list[Any] = Field(default_factory=list)  # EvidenceItem objects
    raw_answer: Any = None  # the parsed ModelAnswer
    validated: Any = None  # the ValidatedAnswer
    citation_validation: dict | None = None
    generation: dict = Field(default_factory=lambda: {"llm_called": False})
    flags: list[str] = Field(default_factory=list)
    model_escalation: bool = False

    # ---- output
    result: dict | None = None  # set by format_output

    # ---- append-only
    user_trace: Annotated[list[dict], operator.add] = Field(default_factory=list)  # the user-facing `trace` of the answer
    execution_trace: Annotated[list[dict], operator.add] = Field(default_factory=list)  # one TraceEvent per executed node
