"""The signed-in user's activity timeline (their own chat sessions only)."""
from uuid import UUID

from fastapi import APIRouter, Query

from app import services
from app.deps import Audit, CurrentUser, DbSession, PageParams
from app.schemas.audit import TimelinePage
from app.schemas.common import ERROR_404, ERROR_422

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get(
    "/timeline",
    response_model=TimelinePage,
    summary="Activity timeline of one of your chat sessions",
    description=(
        "Your audit events for one chat session, grouped by question (`correlation_id`), newest first; `limit` and `offset` "
        "count groups. Each group has its outcome, total latency, the model configuration and the ordered events with their "
        "own latency. Events hold metadata only (counts, codes, chunk ids): never the question, patient or chunk text. "
        "Another user's session and an unknown session both return 404."),
    responses={**ERROR_404, **ERROR_422},
)
def get_timeline(
    user: CurrentUser, db: DbSession, page: PageParams, ctx: Audit,
    session_id: UUID = Query(description="The chat session (required)."),
) -> TimelinePage:
    items, total = services.audit_timeline(db, user, session_id, page.limit, page.offset, ctx)
    return TimelinePage(items=items, total=total, limit=page.limit, offset=page.offset)
