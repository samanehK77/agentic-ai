"""Chat session and message access."""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import ChatMessage, ChatSession

SESSION_COLUMNS = (ChatSession.session_id, ChatSession.patient_id, ChatSession.title, ChatSession.owner_id, ChatSession.created_at)
MESSAGE_COLUMNS = (
    ChatMessage.message_id, ChatMessage.session_id, ChatMessage.role, ChatMessage.mode,
    ChatMessage.content, ChatMessage.created_at,
)


def list_sessions(db: Session, patient_id: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    filters = [ChatSession.patient_id == patient_id] if patient_id else []
    total = db.scalar(select(func.count()).select_from(ChatSession).where(*filters))
    query = (
        select(*SESSION_COLUMNS).where(*filters)
        .order_by(ChatSession.created_at.desc(), ChatSession.session_id)
        .limit(limit).offset(offset)
    )
    return [dict(row) for row in db.execute(query).mappings()], total


def get_session(db: Session, session_id: UUID) -> dict | None:
    row = db.execute(select(*SESSION_COLUMNS).where(ChatSession.session_id == session_id)).mappings().first()
    return dict(row) if row else None


def create_session(db: Session, patient_id: str, title: str) -> dict:
    session = ChatSession(patient_id=patient_id, title=title)
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
