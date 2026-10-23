"""Patient response shapes. Patient facts only: no research claims, citations or interpretations."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from db.models import VOCAB

Gender = Literal[*VOCAB["gender"]]
Category = Literal[*VOCAB["category"]]
Motivation = Literal[*VOCAB["motivation"]]
UsePattern = Literal[*VOCAB["use_pattern"]]
UseStatus = Literal[*VOCAB["use_status"]]
FactorKind = Literal[*VOCAB["factor_kind"]]
FactorContext = Literal[*VOCAB["factor_context"]]
InterventionType = Literal[*VOCAB["intervention_type"]]
CompletionStatus = Literal[*VOCAB["completion_status"]]
ProgressStatus = Literal[*VOCAB["progress_status"]]
EventType = Literal[*VOCAB["event_type"]]


class PatientSummary(BaseModel):
    patient_id: str = Field(examples=["P-001"])
    age_at_intake: int
    gender: Gender
    primary_category: Category
    primary_use_subject: str | None = Field(default=None, description="What the primary use record is about, e.g. 'Alcohol'.")
    intake_date: date
    history_summary: str
    treatment_summary: str
    is_synthetic: Literal[True] = Field(description="Always true: every patient in this system is fictional.")


class UseRecordOut(BaseModel):
    id: str
    category: Category
    subject: str
    pattern: UsePattern
    start_date: date
    end_date: date | None
    status: UseStatus


class FactorOut(BaseModel):
    id: str
    kind: FactorKind
    context: FactorContext
    description: str


class InterventionOut(BaseModel):
    id: str
    type: InterventionType
    setting: str
    start_date: date
    end_date: date | None
    completion_status: CompletionStatus
    reported_outcome: str


class ProgressOut(BaseModel):
    id: str
    observed_on: date
    use_status: ProgressStatus
    motivation: Motivation
    note: str


class PatientProfile(PatientSummary):
    living_situation: str
    employment_status: str
    social_context: str
    co_occurring_symptoms: str
    motivation_at_intake: Motivation
    background: str
    use_records: list[UseRecordOut]
    factors: list[FactorOut]
    interventions: list[InterventionOut]
    progress: list[ProgressOut]


class HistoryItem(BaseModel):
    event_date: date
    date_precision: Literal[*VOCAB["date_precision"]] | None = Field(
        default=None, description="How exact event_date is; only set for history events.")
    source: Literal["history", "use", "intervention", "progress"]
    record_id: str = Field(examples=["P-001-H01"])
    kind: str = Field(examples=["onset"])
    summary: str
