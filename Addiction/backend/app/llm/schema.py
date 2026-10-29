"""The structured answer the model is asked to produce (validated with Pydantic v2). The server never trusts it:
see validate.py for what is checked afterwards."""
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

SectionKind = Literal["patient_fact", "research_finding", "general_knowledge", "interpretation"]


def _alias(value):
    if isinstance(value, str):
        match = re.fullmatch(r"\[?\s*([Ss]\d{1,2})\s*\]?", value.strip())
        if match:
            return match.group(1).upper()
    return value


Alias = Annotated[str, BeforeValidator(_alias), Field(pattern=r"^S\d{1,2}$")]


class ModelCitation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alias: Alias
    quote: str = Field(min_length=1, max_length=400)


class ModelSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: SectionKind
    text: str = Field(min_length=1, max_length=2500)
    citations: list[ModelCitation] = Field(default_factory=list, max_length=5)


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sections: list[ModelSection] = Field(min_length=1, max_length=8)
    conflicting_evidence: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list, max_length=5)
    limitations: str = Field(default="", max_length=1000)
    escalation_needed: bool = False


def describe_errors(error: ValidationError | ValueError) -> str:
    """A short description of what was wrong (field paths and error types only, never the offending values)."""
    if isinstance(error, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['type']}" for e in error.errors()[:8]]
        return "; ".join(parts)
    return "the reply was not a valid json object"
