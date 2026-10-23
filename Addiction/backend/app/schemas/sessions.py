"""Chat session shapes. A chat session is a conversation about one patient (not a login session)."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from db.models import VOCAB

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class SessionCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"patient_id": "P-001", "title": "Questions about P-001"}]},
    )

    patient_id: str = Field(pattern=r"^P-\d{3}$", examples=["P-001"])
    title: Title | None = Field(default=None, description="1 to 120 characters. Defaults to 'Conversation about <patient_id>'.")


class SessionOut(BaseModel):
    session_id: UUID
    patient_id: str
    title: str
    owner_id: UUID | None = Field(default=None, description="Reserved for Batch 04 (sign-in); always null for now.")
    created_at: datetime


class MessageOut(BaseModel):
    message_id: UUID
    session_id: UUID
    role: Literal[*VOCAB["message_role"]]
    mode: Literal[*VOCAB["chat_mode"]] | None
    content: str
    created_at: datetime
