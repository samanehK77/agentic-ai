"""Shapes for the auth endpoints. The Google subject id and Google tokens are never part of any response."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MeOut(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    role: Literal["student", "admin"]
    csrf_token: str = Field(description="Send this in the X-CSRF-Token header on POST, PUT, PATCH and DELETE.")
