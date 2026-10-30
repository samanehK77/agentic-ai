"""What a route hands to the services so they can record audit events: the audit service, the request id and the route name.
Every method is safe to call when auditing is switched off (audit is None) and never raises."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.service import AuditService, safe_code
from app.repositories import sessions as sessions_repo


@dataclass(frozen=True)
class AuditCtx:
    audit: AuditService | None
    request_id: str | None
    route: str  # the route's function name (no path parameters, no query string)

    def record(self, event_type: str, outcome: str = "ok", *, user_id: UUID | None = None, session_id: UUID | None = None,
               correlation_id: UUID | None = None, error_code: str | None = None, latency_ms: int | None = None,
               metadata: dict | None = None) -> None:
        if self.audit is not None:
            self.audit.record(event_type, outcome, correlation_id=correlation_id, user_id=user_id, session_id=session_id,
                              request_id=self.request_id, error_code=error_code, latency_ms=latency_ms, metadata=metadata)

    def denied(self, reason_code: str, *, user_id: UUID | None, session_id: UUID | None = None) -> None:
        self.record("access_denied", "denied", user_id=user_id, session_id=session_id, error_code=reason_code,
                    metadata={"route": safe_code(self.route), "reason_code": reason_code})

    def foreign_session(self, db: Session, user_id: UUID, session_id: UUID) -> None:
        """Called when a session lookup found nothing for this user: records the refusal only if the session exists
        (it belongs to someone else). The caller still answers 404, so nothing is revealed to the user."""
        if self.audit is None:
            return
        try:
            exists = sessions_repo.session_exists(db, session_id)
        except Exception:
            return
        if exists:
            self.denied("not_owner", user_id=user_id, session_id=session_id)


NO_AUDIT = AuditCtx(None, None, "unknown")
