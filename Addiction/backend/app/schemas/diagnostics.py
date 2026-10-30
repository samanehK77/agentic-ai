"""API shape of the operator diagnostics: booleans, counts and codes only (no URLs, keys, paths or secrets)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "warn", "fail"]


class DiagnosticCheck(BaseModel):
    name: str
    status: Status
    message: str
    hint: str = Field(default="", description="How to fix it (empty when the check is ok).")
    facts: dict = Field(default_factory=dict, description="Booleans, counts and short codes only.")


class DiagnosticsReport(BaseModel):
    status: Status = Field(description="The worst status of all checks.")
    generated_at: datetime
    checks: list[DiagnosticCheck]
