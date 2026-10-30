"""The audit event catalogue: for every event type the ONLY metadata keys that may be stored.

Privacy by construction: every model forbids extra keys, every string is short and limited to letters, digits and
`_ . : / -` (so free text, e-mail addresses and IP addresses cannot pass), values are numbers, booleans or short codes,
and the whole payload is capped at 4096 bytes (the database repeats that cap). Question, patient and chunk text,
prompts, answers, titles, tokens, keys and e-mail addresses have no key to live in."""
import json
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from db.models import VOCAB

EVENT_TYPES = VOCAB["audit_event_type"]
OUTCOMES = VOCAB["audit_outcome"]
MAX_METADATA_BYTES = 4096

IP_LIKE = re.compile(r"(?<!\d)\d{1,3}(\.\d{1,3}){3}(?!\d)|([0-9A-Fa-f]{0,4}:){2,}")  # IPv4 and IPv6 look-alikes


def _no_ip_address(value: str) -> str:
    if IP_LIKE.search(value):
        raise ValueError("looks like an IP address")
    return value


Code = Annotated[str, StringConstraints(max_length=120, pattern=r"^[A-Za-z0-9_.:/-]*$"), AfterValidator(_no_ip_address)]
ChunkId = Annotated[str, StringConstraints(max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*-c[0-9]{4,}$")]
PatientId = Annotated[str, StringConstraints(pattern=r"^P-\d{3}$")]
Uuid36 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f-]{36}$")]
Number = int | float | bool

RESULTS = ("answered", "no_evidence", "unsupported", "crisis")
FEEDBACK_REASONS = ("accurate", "clear", "good_sources", "inaccurate", "unclear", "missing_sources", "unsafe", "other")


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignInSucceeded(Meta):
    role: Literal["student", "admin"]


class SignInFailed(Meta):
    reason: Literal["access_denied", "state_invalid", "token_invalid", "email_unverified", "not_configured"]


class SignOut(Meta):
    pass


class PatientViewed(Meta):
    patient_id: PatientId


class SessionCreated(Meta):
    patient_id: PatientId


class QuestionSubmitted(Meta):
    question_chars: int = Field(ge=0, le=100_000)
    mode: Literal["general_knowledge", "rag", "both"]
    idempotent: bool
    config_fingerprint: Code
    model: Code | None = None
    prompt_version: Code | None = None
    retrieval_threshold: float | None = None
    top_k: int | None = Field(default=None, ge=0, le=1000)
    embedding_model: Code | None = None
    embedding_fingerprint: Code | None = None
    chunking_version: Code | None = None


class NodeExecuted(Meta):
    node: Code
    status: Literal["ok", "skipped", "ended", "error"]
    reason_code: Code | None = None
    counts: dict[Code, Number] = Field(default_factory=dict)
    chunk_ids: list[ChunkId] = Field(default_factory=list, max_length=20)

    @field_validator("counts")
    @classmethod
    def _few_counts(cls, value):
        if len(value) > 20:
            raise ValueError("too many counts")
        return value


class RetrievalExecuted(Meta):
    attempt: int = Field(ge=1, le=10)
    top_k: int | None = Field(default=None, ge=0, le=1000)
    threshold: float | None = None
    chunks: int = Field(ge=0, le=1000)
    chunk_ids: list[ChunkId] = Field(default_factory=list, max_length=20)
    evidence_level: Literal["none", "weak", "adequate"] | None = None


class LlmRequest(Meta):
    model: Code | None = None
    config_fingerprint: Code | None = None
    prompt_tokens: int = Field(default=0, ge=0, le=10_000_000)
    completion_tokens: int = Field(default=0, ge=0, le=10_000_000)
    retries: int = Field(default=0, ge=0, le=100)
    repair_attempted: bool = False
    status: Literal["ok", "error"]


class CitationValidated(Meta):
    citations: int = Field(ge=0, le=1000)
    verified: int = Field(ge=0, le=1000)
    unsupported_claims: int = Field(ge=0, le=1000)
    sections: int = Field(ge=0, le=1000)


class AnswerReturned(Meta):
    result: Literal[*RESULTS] | None = None  # None for a replayed idempotent request
    message_id: Uuid36 | None = None
    classification: Code | None = None
    llm_called: bool = False
    replayed: bool = False


class PipelineError(Meta):
    failed_node: Code | None = None
    retrieval_chunks: int | None = Field(default=None, ge=0, le=1000)


class AccessDenied(Meta):
    route: Code
    reason_code: Literal["not_owner", "role_required"]


class FeedbackSubmitted(Meta):
    message_id: Uuid36
    rating: Literal["helpful", "not_helpful"]
    reason: Literal[*FEEDBACK_REASONS] | None = None


MODELS: dict[str, type[Meta]] = {
    "sign_in_succeeded": SignInSucceeded, "sign_in_failed": SignInFailed, "sign_out": SignOut,
    "patient_viewed": PatientViewed, "session_created": SessionCreated, "question_submitted": QuestionSubmitted,
    "node_executed": NodeExecuted, "retrieval_executed": RetrievalExecuted, "llm_request": LlmRequest,
    "citation_validated": CitationValidated, "answer_returned": AnswerReturned, "pipeline_error": PipelineError,
    "access_denied": AccessDenied, "feedback_submitted": FeedbackSubmitted,
}
assert set(MODELS) == set(EVENT_TYPES), "every event type needs a metadata model"


class RejectedMetadata(ValueError):
    """The metadata does not fit its event type. Carries only key names and error kinds, never a value."""


def check_metadata(event_type: str, metadata: dict) -> dict:
    """The metadata exactly as it will be stored (None values dropped), or RejectedMetadata."""
    model = MODELS.get(event_type)
    if model is None:
        raise RejectedMetadata("unknown event type")
    try:
        clean = model(**metadata).model_dump(exclude_none=True)
    except ValidationError as error:
        raise RejectedMetadata("; ".join(f"{'.'.join(map(str, e['loc']))}:{e['type']}" for e in error.errors())) from None
    except TypeError:
        raise RejectedMetadata("metadata must be a mapping with string keys") from None
    if len(json.dumps(clean, separators=(",", ":")).encode("utf-8")) > MAX_METADATA_BYTES:
        raise RejectedMetadata("metadata too large")
    return clean
