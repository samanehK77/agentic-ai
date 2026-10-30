"""Administrator-only views of the audit log: metadata and statistics, never content."""
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app import services
from app.deps import DbSession, PageParams
from app.schemas.audit import AdminAuditEventOut, AuditSummary, EventType, Outcome
from app.schemas.common import ERROR_403, ERROR_422, Page

router = APIRouter(prefix="/api/admin/audit", tags=["admin"])

DateFrom = Annotated[datetime | None, Query(description="Only events at or after this time (ISO 8601).")]
DateTo = Annotated[datetime | None, Query(description="Only events before this time (ISO 8601).")]


@router.get(
    "/events",
    response_model=Page[AdminAuditEventOut],
    summary="List audit events (admin)",
    description="Administrators only, newest first. Metadata only: question, patient and chunk text, prompts, answers, tokens "
                "and e-mail addresses are never stored, so they cannot be returned.",
    responses={**ERROR_403, **ERROR_422},
)
def list_events(
    db: DbSession, page: PageParams,
    event_type: Annotated[EventType | None, Query()] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    outcome: Annotated[Outcome | None, Query()] = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[AdminAuditEventOut]:
    items, total = services.admin_audit_events(db, event_type, user_id, outcome, date_from, date_to, page.limit, page.offset)
    return Page[AdminAuditEventOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/summary",
    response_model=AuditSummary,
    summary="Audit statistics (admin)",
    description="Counts per event type and day, error rate, no-evidence rate, p50 and p95 answer latency and the number of "
                "failed audit writes of this server process.",
    responses={**ERROR_403, **ERROR_422},
)
def summary(request: Request, db: DbSession, date_from: DateFrom = None, date_to: DateTo = None) -> AuditSummary:
    audit = request.app.state.audit
    return AuditSummary(**services.admin_audit_summary(db, date_from, date_to, audit.failures))
