"""Business rules between the routers and the repositories (no SQL here, no HTTP types in the repositories)."""
from uuid import UUID

from sqlalchemy.orm import Session

from app.errors import not_found, service_unavailable
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


def list_sessions(db: Session, patient_id: str | None, limit: int, offset: int):
    return sessions_repo.list_sessions(db, patient_id, limit, offset)


def create_session(db: Session, patient_id: str, title: str | None) -> dict:
    if not patients_repo.patient_exists(db, patient_id):
        raise not_found(f"Patient {patient_id} was not found.")
    return sessions_repo.create_session(db, patient_id, title or f"Conversation about {patient_id}")


def get_session(db: Session, session_id: UUID) -> dict:
    session = sessions_repo.get_session(db, session_id)
    if session is None:
        raise not_found("Chat session was not found.")
    return session


def list_messages(db: Session, session_id: UUID, limit: int, offset: int):
    get_session(db, session_id)  # 404 for an unknown session
    return sessions_repo.list_messages(db, session_id, limit, offset)
