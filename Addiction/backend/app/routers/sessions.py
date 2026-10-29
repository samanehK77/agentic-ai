from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app import services
from app.deps import CurrentUser, DbSession, PageParams
from app.schemas.common import ERROR_404, ERROR_422, Page
from app.schemas.sessions import MessageOut, SessionCreate, SessionOut

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get(
    "",
    response_model=Page[SessionOut],
    summary="List chat sessions",
    description="Your own chat sessions only, newest first.",
    responses=ERROR_422,
)
def list_sessions(
    user: CurrentUser,
    db: DbSession,
    page: PageParams,
    patient_id: Annotated[str | None, Query(pattern=r"^P-\d{3}$", description="Only sessions about this patient.")] = None,
) -> Page[SessionOut]:
    items, total = services.list_sessions(db, user, patient_id, page.limit, page.offset)
    return Page[SessionOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "",
    response_model=SessionOut,
    status_code=201,
    summary="Create a chat session",
    description="Starts a conversation about one patient. The new session's URL is returned in the Location header.",
    responses={**ERROR_404, **ERROR_422},
)
def create_session(body: SessionCreate, request: Request, response: Response, user: CurrentUser, db: DbSession) -> SessionOut:
    session = services.create_session(db, user, body.patient_id, body.title)
    response.headers["Location"] = str(request.url_for("get_session", session_id=session["session_id"]))
    return SessionOut(**session)


@router.get(
    "/{session_id}",
    response_model=SessionOut,
    summary="Get one chat session",
    responses={**ERROR_404, **ERROR_422},
)
def get_session(session_id: UUID, user: CurrentUser, db: DbSession) -> SessionOut:
    return SessionOut(**services.get_session(db, user, session_id))


@router.get(
    "/{session_id}/messages",
    response_model=Page[MessageOut],
    summary="List the messages of a chat session",
    description="Oldest first. Another user's session returns 404. A session with no messages returns an empty list. Nothing writes messages yet (Batches 07-08).",
    responses={**ERROR_404, **ERROR_422},
)
def list_messages(session_id: UUID, user: CurrentUser, db: DbSession, page: PageParams) -> Page[MessageOut]:
    items, total = services.list_messages(db, user, session_id, page.limit, page.offset)
    return Page[MessageOut](items=items, total=total, limit=page.limit, offset=page.offset)
