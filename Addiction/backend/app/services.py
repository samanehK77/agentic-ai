"""Business rules between the routers and the repositories (no SQL here, no HTTP types in the repositories)."""
from uuid import UUID

from sqlalchemy.orm import Session

from app.auth_service import AuthUser
from app.answers import service as answers_service
from app.retrieval import service as retrieval_service
from app.errors import not_found, service_unavailable
from app.repositories import admin_papers as admin_papers_repo
from app.repositories import health as health_repo
from app.repositories import papers as papers_repo
from app.repositories import patients as patients_repo
from app.repositories import sessions as sessions_repo


def check_database(db: Session) -> None:
    if not health_repo.ping(db):
        raise service_unavailable()


def list_patients(db: Session, category: str | None, limit: int, offset: int):
    return patients_repo.list_patients(db, category, limit, offset)


def get_patient_profile(db: Session, patient_id: str) -> dict:
    profile = patients_repo.get_profile(db, patient_id)
    if profile is None:
        raise not_found(f"Patient {patient_id} was not found.")
    return profile


def get_patient_history(db: Session, patient_id: str, limit: int, offset: int):
    if not patients_repo.patient_exists(db, patient_id):
        raise not_found(f"Patient {patient_id} was not found.")
    return patients_repo.get_history(db, patient_id, limit, offset)


def list_papers(db: Session, limit: int, offset: int):
    return papers_repo.list_papers(db, limit, offset)


def list_sessions(db: Session, user: AuthUser, patient_id: str | None, limit: int, offset: int):
    return sessions_repo.list_sessions(db, user.id, patient_id, limit, offset)


def create_session(db: Session, user: AuthUser, patient_id: str, title: str | None) -> dict:
    if not patients_repo.patient_exists(db, patient_id):
        raise not_found(f"Patient {patient_id} was not found.")
    return sessions_repo.create_session(db, user.id, patient_id, title or f"Conversation about {patient_id}")


def get_session(db: Session, user: AuthUser, session_id: UUID) -> dict:
    # Someone else's session gets the same 404 as a missing one, so its existence is not revealed.
    session = sessions_repo.get_session(db, user.id, session_id)
    if session is None:
        raise not_found("Chat session was not found.")
    return session


def list_messages(db: Session, user: AuthUser, session_id: UUID, limit: int, offset: int):
    get_session(db, user, session_id)  # 404 for an unknown or foreign session
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
