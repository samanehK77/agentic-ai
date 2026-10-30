"""Business rules between the routers and the repositories (no SQL here, no HTTP types in the repositories)."""
from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.context import NO_AUDIT, AuditCtx
from app.auth_service import AuthUser
from app.answers import service as answers_service
from app.retrieval import service as retrieval_service
from app.errors import not_found, service_unavailable
from app.audit.timeline import build_groups
from app.repositories import admin_papers as admin_papers_repo
from app.repositories import answers as answers_repo
from app.repositories import audit as audit_repo
from app.repositories import health as health_repo
from app.repositories import papers as papers_repo
from app.repositories import patients as patients_repo
from app.repositories import sessions as sessions_repo


def check_database(db: Session) -> None:
    if not health_repo.ping(db):
        raise service_unavailable()


def list_patients(db: Session, category: str | None, limit: int, offset: int):
    return patients_repo.list_patients(db, category, limit, offset)


def get_patient_profile(db: Session, patient_id: str, user: AuthUser | None = None, ctx: AuditCtx = NO_AUDIT) -> dict:
    profile = patients_repo.get_profile(db, patient_id)
    if profile is None:
        raise not_found(f"Patient {patient_id} was not found.")
    ctx.record("patient_viewed", user_id=user.id if user else None, metadata={"patient_id": patient_id})
    return profile


def get_patient_history(db: Session, patient_id: str, limit: int, offset: int):
    if not patients_repo.patient_exists(db, patient_id):
        raise not_found(f"Patient {patient_id} was not found.")
    return patients_repo.get_history(db, patient_id, limit, offset)


def list_papers(db: Session, limit: int, offset: int):
    return papers_repo.list_papers(db, limit, offset)


def list_sessions(db: Session, user: AuthUser, patient_id: str | None, limit: int, offset: int):
    return sessions_repo.list_sessions(db, user.id, patient_id, limit, offset)


def create_session(db: Session, user: AuthUser, patient_id: str, title: str | None, ctx: AuditCtx = NO_AUDIT) -> dict:
    if not patients_repo.patient_exists(db, patient_id):
        raise not_found(f"Patient {patient_id} was not found.")
    session = sessions_repo.create_session(db, user.id, patient_id, title or f"Conversation about {patient_id}")
    ctx.record("session_created", user_id=user.id, session_id=session["session_id"], metadata={"patient_id": patient_id})
    return session


def get_session(db: Session, user: AuthUser, session_id: UUID, ctx: AuditCtx = NO_AUDIT) -> dict:
    # Someone else's session gets the same 404 as a missing one, so its existence is not revealed.
    session = sessions_repo.get_session(db, user.id, session_id)
    if session is None:
        ctx.foreign_session(db, user.id, session_id)  # audit only; the answer is the same 404
        raise not_found("Chat session was not found.")
    return session


def list_messages(db: Session, user: AuthUser, session_id: UUID, limit: int, offset: int, ctx: AuditCtx = NO_AUDIT):
    get_session(db, user, session_id, ctx)  # 404 for an unknown or foreign session
    items, total = sessions_repo.list_messages(db, session_id, limit, offset)
    return answers_service.attach_answers(db, items), total


# ---------------------------------------------------------------- administrator views of ingestion (Batch 05)

def admin_list_papers(db: Session, limit: int, offset: int):
    return admin_papers_repo.list_papers(db, limit, offset)


def admin_get_paper(db: Session, paper_id: str) -> dict:
    paper = admin_papers_repo.get_paper(db, paper_id)
    if paper is None:
        raise not_found(f"Paper {paper_id} was not found.")
    return paper


def admin_list_chunks(db: Session, paper_id: str, section_type: str | None, limit: int, offset: int):
    if not admin_papers_repo.paper_exists(db, paper_id):
        raise not_found(f"Paper {paper_id} was not found.")
    return admin_papers_repo.list_chunks(db, paper_id, section_type, limit, offset)


def admin_get_chunk(db: Session, chunk_id: str) -> dict:
    chunk = admin_papers_repo.get_chunk(db, chunk_id)
    if chunk is None:
        raise not_found(f"Chunk {chunk_id} was not found.")
    return chunk


# ---------------------------------------------------------------- semantic search (Batch 06)

def retrieval_search(db: Session, provider, *, query: str, top_k: int, paper_id: str | None,
                     min_similarity: float | None) -> dict:
    if paper_id is not None and not admin_papers_repo.paper_exists(db, paper_id):
        raise not_found(f"Paper {paper_id} was not found.")
    return retrieval_service.search(db, provider, query=query, top_k=top_k, paper_id=paper_id,
                                    min_similarity=min_similarity)


# ---------------------------------------------------------------- audit log and feedback (Batch 09)

def audit_timeline(db: Session, user: AuthUser, session_id: UUID, limit: int, offset: int, ctx: AuditCtx = NO_AUDIT):
    """The signed-in user's audit events of their own session, grouped by question. 404 for anyone else's session."""
    get_session(db, user, session_id, ctx)
    ids, total = audit_repo.timeline_groups(db, user.id, session_id, limit, offset)
    return build_groups(ids, audit_repo.events_of_groups(db, user.id, session_id, ids)), total


def admin_audit_events(db: Session, event_type, user_id, outcome, date_from, date_to, limit: int, offset: int):
    return audit_repo.list_events(db, event_type, user_id, outcome, date_from, date_to, limit, offset)


def admin_audit_summary(db: Session, date_from, date_to, write_failures: int) -> dict:
    raw = audit_repo.summary(db, date_from, date_to)
    answered, errors, no_evidence = raw["answered_total"], raw["errors"], raw["no_evidence"]
    finished = answered + errors
    return {
        "date_from": date_from, "date_to": date_to, "per_day": raw["per_day"], "answers_returned": answered,
        "pipeline_errors": errors, "error_rate": round(errors / finished, 4) if finished else None,
        "no_evidence_rate": round(no_evidence / answered, 4) if answered else None,
        "answer_latency_p50_ms": None if raw["p50"] is None else round(float(raw["p50"]), 1),
        "answer_latency_p95_ms": None if raw["p95"] is None else round(float(raw["p95"]), 1),
        "audit_write_failures": write_failures}


def submit_feedback(db: Session, audit, user: AuthUser, session_id: UUID, message_id: UUID, rating: str, reason: str | None,
                    ctx: AuditCtx = NO_AUDIT) -> tuple[dict, bool]:
    """Owner-only, assistant messages only (anything else is 404). The first rating of a message stands."""
    get_session(db, user, session_id, ctx)
    if answers_repo.get_trace(db, session_id, message_id) is None:
        raise not_found("Message was not found.")
    metadata, created = audit.record_feedback(
        user_id=user.id, session_id=session_id, request_id=ctx.request_id, message_id=str(message_id), rating=rating, reason=reason)
    return {"message_id": message_id, "rating": metadata["rating"], "reason": metadata.get("reason"),
            "already_recorded": not created}, created

