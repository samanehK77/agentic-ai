"""SQLAlchemy 2.x models for the synthetic patient data (patient facts only).

Allowed values live in the VOCAB dict. The Alembic migration repeats them as CHECK
constraints, and a test confirms the two stay in sync.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, MetaData,
    SmallInteger, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy import text as sql_text  # the PaperChunk column named "text" shadows text() inside that class
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

VOCAB = {
    "gender": ("woman", "man", "non_binary", "other", "unknown"),
    "category": ("alcohol", "cannabis", "opioids", "stimulants", "behavioral"),
    "motivation": ("none_expressed", "ambivalent", "contemplating", "preparing", "engaged", "unknown"),
    "date_precision": ("year", "month", "day"),
    "event_type": (
        "onset", "escalation", "life_event", "health_event", "legal_or_work_event", "help_seeking",
        "treatment_contact", "reduction_attempt", "relapse", "recovery_milestone", "other",
    ),
    "use_pattern": ("daily", "several_per_week", "weekends", "binge_episodic", "intermittent", "unknown"),
    "use_status": ("active", "reduced", "supervised", "abstinent", "unknown"),
    "factor_kind": ("trigger", "risk_factor", "protective_factor", "observed_behavior"),
    "factor_context": ("emotional", "social", "work", "financial", "health", "environmental", "unknown"),
    "intervention_type": (
        "brief_advice", "outpatient_counseling", "group_support", "residential_program",
        "medication_supported_program", "inpatient_stay", "pain_management_program",
        "self_exclusion_or_blocking", "family_sessions", "other",
    ),
    "completion_status": ("completed", "dropped_out", "ongoing", "not_started", "unknown"),
    "progress_status": ("abstinent", "reduced", "unchanged", "increased", "relapse", "unknown"),
    # Batch 06
    "embedding_status": ("pending", "embedded", "skipped"),
    # Batch 05
    "metadata_source": ("project_list", "document_text"),
    "section_type": ("body", "table_or_figure", "references", "front_matter"),
    "run_status": ("running", "completed", "completed_with_errors", "failed"),
    # Batch 04
    "user_role": ("student", "admin"),
    # Batch 03
    "document_type": ("guideline", "guide", "review", "unknown"),
    "ingest_status": ("not_ingested", "ingested", "failed", "needs_ocr"),
    "message_role": ("user", "assistant"),
    "chat_mode": ("general_knowledge", "rag", "both"),
}


def _in(column: str, key: str) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in VOCAB[key])})"


NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _synthetic() -> Mapped[bool]:
    return mapped_column(Boolean, nullable=False, server_default=text("true"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


SYNTHETIC_CHECK = CheckConstraint("is_synthetic", name="is_synthetic_true")
NOT_FUTURE = "<= CURRENT_DATE"


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(Text, primary_key=True)
    age_at_intake: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gender: Mapped[str] = mapped_column(Text, nullable=False)
    primary_category: Mapped[str] = mapped_column(Text, nullable=False)
    intake_date: Mapped[date] = mapped_column(Date, nullable=False)
    living_situation: Mapped[str] = mapped_column(Text, nullable=False)
    employment_status: Mapped[str] = mapped_column(Text, nullable=False)
    social_context: Mapped[str] = mapped_column(Text, nullable=False)
    co_occurring_symptoms: Mapped[str] = mapped_column(Text, nullable=False)
    motivation_at_intake: Mapped[str] = mapped_column(Text, nullable=False)
    background: Mapped[str] = mapped_column(Text, nullable=False)
    history_summary: Mapped[str] = mapped_column(Text, nullable=False)
    treatment_summary: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = _synthetic()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()

    history_events: Mapped[list["HistoryEvent"]] = relationship(back_populates="patient", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("patient_id ~ '^P-[0-9]{3}$'", name="id_format"),
        CheckConstraint("age_at_intake BETWEEN 18 AND 110", name="adult_age"),
        CheckConstraint(_in("gender", "gender"), name="gender_values"),
        CheckConstraint(_in("primary_category", "category"), name="category_values"),
        CheckConstraint(_in("motivation_at_intake", "motivation"), name="motivation_values"),
        CheckConstraint(f"intake_date {NOT_FUTURE}", name="intake_not_future"),
        CheckConstraint(
            "length(trim(living_situation)) > 0 AND length(trim(employment_status)) > 0 "
            "AND length(trim(social_context)) > 0 AND length(trim(co_occurring_symptoms)) > 0 "
            "AND length(trim(background)) > 0 AND length(trim(history_summary)) > 0 "
            "AND length(trim(treatment_summary)) > 0",
            name="text_not_blank",
        ),
        SYNTHETIC_CHECK,
    )


def _patient_fk() -> Mapped[str]:
    return mapped_column(Text, ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False)


class HistoryEvent(Base):
    __tablename__ = "patient_history_events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = _patient_fk()
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    date_precision: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = _synthetic()
    created_at: Mapped[datetime] = _created()

    patient: Mapped[Patient] = relationship(back_populates="history_events")

    __table_args__ = (
        CheckConstraint("event_id LIKE patient_id || '-H%'", name="key_matches_patient"),
        CheckConstraint(_in("date_precision", "date_precision"), name="precision_values"),
        CheckConstraint(_in("event_type", "event_type"), name="type_values"),
        CheckConstraint(f"event_date {NOT_FUTURE}", name="date_not_future"),
        CheckConstraint("length(trim(description)) > 0", name="description_not_blank"),
        SYNTHETIC_CHECK,
        Index("ix_patient_history_events_patient_date", "patient_id", "event_date"),
    )


class UseRecord(Base):
    __tablename__ = "substance_or_behavior_use"

    use_id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = _patient_fk()
    category: Mapped[str] = mapped_column(Text, nullable=False)
    substance_or_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = _synthetic()
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("use_id LIKE patient_id || '-U%'", name="key_matches_patient"),
        CheckConstraint(_in("category", "category"), name="category_values"),
        CheckConstraint(_in("pattern", "use_pattern"), name="pattern_values"),
        CheckConstraint(_in("status", "use_status"), name="status_values"),
        CheckConstraint(f"start_date {NOT_FUTURE}", name="start_not_future"),
        CheckConstraint(f"end_date IS NULL OR end_date {NOT_FUTURE}", name="end_not_future"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="end_after_start"),
        CheckConstraint("end_date IS NULL OR status IN ('abstinent', 'unknown')", name="end_needs_abstinent_or_unknown"),
        CheckConstraint("length(trim(substance_or_behavior)) > 0", name="subject_not_blank"),
        SYNTHETIC_CHECK,
        Index("ix_substance_or_behavior_use_patient_start", "patient_id", "start_date"),
    )


class Factor(Base):
    __tablename__ = "triggers_and_risk_factors"

    factor_id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = _patient_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = _synthetic()
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("factor_id LIKE patient_id || '-F%'", name="key_matches_patient"),
        CheckConstraint(_in("kind", "factor_kind"), name="kind_values"),
        CheckConstraint(_in("context", "factor_context"), name="context_values"),
        CheckConstraint("length(trim(description)) > 0", name="description_not_blank"),
        SYNTHETIC_CHECK,
        Index("ix_triggers_and_risk_factors_patient_kind", "patient_id", "kind"),
    )


class Intervention(Base):
    __tablename__ = "previous_interventions"

    intervention_id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = _patient_fk()
    intervention_type: Mapped[str] = mapped_column(Text, nullable=False)
    setting: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    completion_status: Mapped[str] = mapped_column(Text, nullable=False)
    reported_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = _synthetic()
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("intervention_id LIKE patient_id || '-I%'", name="key_matches_patient"),
        CheckConstraint(_in("intervention_type", "intervention_type"), name="type_values"),
        CheckConstraint(_in("completion_status", "completion_status"), name="status_values"),
        CheckConstraint(f"start_date {NOT_FUTURE}", name="start_not_future"),
        CheckConstraint(f"end_date IS NULL OR end_date {NOT_FUTURE}", name="end_not_future"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="end_after_start"),
        CheckConstraint(
            "(completion_status = 'ongoing' AND end_date IS NULL) "
            "OR (completion_status IN ('completed', 'dropped_out') AND end_date IS NOT NULL) "
            "OR completion_status IN ('not_started', 'unknown')",
            name="status_matches_end_date",
        ),
        CheckConstraint("length(trim(setting)) > 0 AND length(trim(reported_outcome)) > 0", name="text_not_blank"),
        SYNTHETIC_CHECK,
        Index("ix_previous_interventions_patient_start", "patient_id", "start_date"),
    )


class ProgressObservation(Base):
    __tablename__ = "progress_observations"

    observation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[str] = _patient_fk()
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    use_status: Mapped[str] = mapped_column(Text, nullable=False)
    motivation: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = _synthetic()
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("observation_id LIKE patient_id || '-O%'", name="key_matches_patient"),
        CheckConstraint(_in("use_status", "progress_status"), name="use_status_values"),
        CheckConstraint(_in("motivation", "motivation"), name="motivation_values"),
        CheckConstraint(f"observed_on {NOT_FUTURE}", name="observed_not_future"),
        CheckConstraint("length(trim(note)) > 0", name="note_not_blank"),
        SYNTHETIC_CHECK,
        Index("ix_progress_observations_patient_date", "patient_id", "observed_on"),
    )


# ---------------------------------------------------------------- Batch 03 tables
# Papers hold metadata only (no document text, no chunks: those arrive in Batch 05).
# chat_sessions is named so it is never confused with the login session of Batch 04.


class Paper(Base):
    __tablename__ = "papers"

    paper_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    publication_year: Mapped[str] = mapped_column(Text, nullable=False)  # four digits or 'unknown'
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    ingest_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'not_ingested'"))
    created_at: Mapped[datetime] = _created()
    # Batch 05: ingestion state. file_name is internal only and never leaves the API layer.
    file_name: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunking_version: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    doi: Mapped[str | None] = mapped_column(Text)
    metadata_source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'project_list'"))
    low_text_pages: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, server_default=text("'{}'"))
    ingest_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("metadata_source", "metadata_source"), name="metadata_source_values"),
        CheckConstraint(r"file_name IS NULL OR (length(trim(file_name)) > 0 AND file_name !~ '[/\\]')", name="file_name_bare"),
        CheckConstraint("content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
        CheckConstraint("paper_id ~ '^[a-z0-9][a-z0-9-]*$'", name="id_format"),
        CheckConstraint(_in("document_type", "document_type"), name="document_type_values"),
        CheckConstraint(_in("ingest_status", "ingest_status"), name="ingest_status_values"),
        CheckConstraint("publication_year ~ '^(unknown|[0-9]{4})$'", name="year_format"),
        CheckConstraint(
            "length(trim(title)) > 0 AND length(trim(publisher)) > 0 AND length(trim(source_note)) > 0",
            name="text_not_blank",
        ),
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    patient_id: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL only for rows created before Batch 04; the API never shows those to anyone.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 120", name="title_length"),
        Index("ix_chat_sessions_patient_created", "patient_id", "created_at"),
        Index("ix_chat_sessions_owner_created", "owner_id", "created_at"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    # Batch 07: assistant rows carry the validated structured answer and telemetry (never prompt text).
    response: Mapped[dict | None] = mapped_column(JSONB)
    generation: Mapped[dict | None] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    request_hash: Mapped[str | None] = mapped_column(Text)
    # Batch 08: the workflow's execution trace (statistics only) and the graph version that produced the answer.
    trace: Mapped[list | None] = mapped_column(JSONB)
    graph_version: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("role = 'assistant' OR (trace IS NULL AND graph_version IS NULL)", name="trace_assistant_only"),
        CheckConstraint("trace IS NULL OR jsonb_typeof(trace) = 'array'", name="trace_is_array"),
        CheckConstraint("graph_version IS NULL OR length(trim(graph_version)) > 0", name="graph_version_not_blank"),
        CheckConstraint("idempotency_key IS NULL OR idempotency_key ~ '^[A-Za-z0-9._-]{8,64}$'", name="idempotency_key_format"),
        CheckConstraint("request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_format"),
        CheckConstraint("(idempotency_key IS NULL) = (request_hash IS NULL)", name="key_and_hash_together"),
        CheckConstraint(
            "role = 'assistant' OR (response IS NULL AND generation IS NULL AND idempotency_key IS NULL)",
            name="answer_fields_assistant_only"),
        Index("uq_chat_messages_session_idempotency", "session_id", "idempotency_key", unique=True,
              postgresql_where=text("idempotency_key IS NOT NULL")),
        CheckConstraint(_in("role", "message_role"), name="role_values"),
        CheckConstraint(f"mode IS NULL OR {_in('mode', 'chat_mode')}", name="mode_values"),
        CheckConstraint("length(trim(content)) > 0 AND length(content) <= 8000", name="content_length"),
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )


# ---------------------------------------------------------------- Batch 04 tables
# users are identified by Google's stable `sub`, never by email. auth_sessions are login sessions
# (not chat_sessions) and store only a SHA-256 hash of the cookie token.


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    google_sub: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'student'"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("google_sub", name="uq_users_google_sub"),
        CheckConstraint(_in("role", "user_role"), name="role_values"),
        CheckConstraint("length(trim(google_sub)) > 0", name="sub_not_blank"),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        Index("ix_auth_sessions_user_id", "user_id"),
    )


class PaperChunk(Base):
    __tablename__ = "paper_chunks"

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)  # <paper_id>-c<ordinal:04d>
    paper_id: Mapped[str] = mapped_column(Text, ForeignKey("papers.paper_id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text)
    section_type: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    possible_injection: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("false"))
    created_at: Mapped[datetime] = _created()
    # Batch 06: exact-search embeddings. NULL unless embedding_status = 'embedded'.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    embedding_fingerprint: Mapped[str | None] = mapped_column(Text)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'pending'"))

    __table_args__ = (
        CheckConstraint("chunk_id ~ '^[a-z0-9][a-z0-9-]*-c[0-9]{4,}$'", name="id_format"),
        CheckConstraint("chunk_id LIKE paper_id || '-c%'", name="key_matches_paper"),
        CheckConstraint("ordinal >= 1", name="ordinal_positive"),
        CheckConstraint("length(trim(text)) > 0", name="text_not_blank"),
        CheckConstraint("token_count > 0", name="token_count_positive"),
        CheckConstraint("page_start >= 1 AND page_end >= page_start", name="pages_valid"),
        CheckConstraint(_in("section_type", "section_type"), name="section_type_values"),
        CheckConstraint("text_sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint(_in("embedding_status", "embedding_status"), name="embedding_status_values"),
        CheckConstraint(
            "(embedding IS NOT NULL) = (embedding_status = 'embedded' AND embedding_fingerprint IS NOT NULL)",
            name="embedding_consistent"),
        Index("ix_paper_chunks_embedding_status", "embedding_status"),
        Index("ix_paper_chunks_paper_id", "paper_id"),
        Index("ix_paper_chunks_paper_ordinal", "paper_id", "ordinal", unique=True),
    )


class IngestionRun(Base):
    """Statistics about one ingestion run. Never contains document text."""

    __tablename__ = "ingestion_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    results: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (CheckConstraint(_in("status", "run_status"), name="status_values"),)
