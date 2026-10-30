"""Shared FastAPI dependencies and parameter types."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Path, Query, Request
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app import auth_service, security
from app.audit.context import AuditCtx
from app.auth_service import SESSION_COOKIE, AuthUser
from app.errors import csrf_failed, forbidden, request_id_of, unauthorized

PATIENT_ID_PATTERN = r"^P-\d{3}$"

PatientIdPath = Annotated[
    str,
    Path(pattern=PATIENT_ID_PATTERN, description="Synthetic patient id, P-001 to P-010.", examples=["P-001"]),
]


def get_db(request: Request) -> Iterator[Session]:
    """One database session per request, always closed afterwards."""
    with Session(request.app.state.engine) as session:
        yield session


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1 to 100).")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of items to skip.")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


DbSession = Annotated[Session, Depends(get_db)]
PageParams = Annotated[Pagination, Depends(pagination)]


def audit_ctx(request: Request) -> AuditCtx:
    """What services need to record audit events for this request (the route's function name, never its path or query)."""
    route = request.scope.get("route")
    return AuditCtx(getattr(request.app.state, "audit", None), request_id_of(request), getattr(route, "name", None) or "unknown")


Audit = Annotated[AuditCtx, Depends(audit_ctx)]


# ---------------------------------------------------------------- authentication

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
session_cookie_scheme = APIKeyCookie(name=SESSION_COOKIE, auto_error=False, description="Login session cookie set by Google sign-in.")


def current_user(
    request: Request,
    db: DbSession,
    token: Annotated[str | None, Depends(session_cookie_scheme)],
    csrf_header: Annotated[
        str | None,
        Header(alias="X-CSRF-Token", description="Required on POST, PUT, PATCH and DELETE; value from GET /api/auth/me."),
    ] = None,
) -> AuthUser:
    """The signed-in user, or 401. State-changing requests must also pass the CSRF and Origin checks."""
    user = auth_service.authenticate(db, request.app.state.settings, token)
    if user is None:
        raise unauthorized()
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None and origin not in request.app.state.settings.cors_origins:
            raise csrf_failed()
        if not csrf_header or not security.safe_equal(csrf_header, user.csrf_token):
            raise csrf_failed()
    return user


CurrentUser = Annotated[AuthUser, Depends(current_user)]


def require_role(*roles: str):
    """Dependency factory for role-restricted routes: `Depends(require_role("admin"))`."""

    def check(user: CurrentUser, ctx: Audit) -> AuthUser:
        if user.role not in roles:
            ctx.denied("role_required", user_id=user.id)
            raise forbidden()
        return user

    return check
