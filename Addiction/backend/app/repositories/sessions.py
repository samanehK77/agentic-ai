"""Chat session and message access."""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import ChatMessage, ChatSession

SESSION_COLUMNS = (ChatSession.session_id, ChatSession.patient_id, ChatSession.title, ChatSession.owner_id, ChatSession.created_at)
MESSAGE_COLUMNS = (
    ChatMessage.message_id, ChatMessage.session_id, ChatMessage.role, ChatMessage.mode,
    ChatMessage.content, ChatMessage.created_at, ChatMessage.response, ChatMessage.generation,
    ChatMessage.trace, ChatMessage.graph_version,
)


def list_sessions(db: Session, owner_id: UUID, patient_id: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    filters = [ChatSession.owner_id == owner_id]
    if patient_id:
        filters.append(ChatSession.patient_id == patient_id)
    total = db.scalar(select(func.count()).select_from(ChatSession).where(*filters))
    query = (
        select(*SESSION_COLUMNS).where(*filters)
        .order_by(ChatSession.created_at.desc(), ChatSession.session_id)
        .limit(limit).offset(offset)
    )
    return [dict(row) for row in db.execute(query).mappings()], total


def get_session(db: Session, owner_id: UUID, session_id: UUID) -> dict | None:
    """Only the owner's session; another user's (or a legacy NULL-owner) session looks like it does not exist."""
    row = db.execute(
        select(*SESSION_COLUMNS).where(ChatSession.session_id == session_id, ChatSession.owner_id == owner_id)
    ).mappings().first()
    return dict(row) if row else None


def session_exists(db: Session, session_id: UUID) -> bool:
    """Whether the session exists at all, whoever owns it. Used only to tell a refusal from an unknown id in the audit log."""
    return db.scalar(select(ChatSession.session_id).where(ChatSession.session_id == session_id)) is not None


def create_session(db: Session, owner_id: UUID, patient_id: str, title: str) -> dict:
    session = ChatSession(patient_id=patient_id, title=title, owner_id=owner_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {column.key: getattr(session, column.key) for column in SESSION_COLUMNS}


def list_messages(db: Session, session_id: UUID, limit: int, offset: int) -> tuple[list[dict], int]:
    total = db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id))
    query = (
        select(*MESSAGE_COLUMNS).where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at, ChatMessage.message_id)
        .limit(limit).offset(offset)
    )
    return [dict(row) for row in db.execute(query).mappings()], total
