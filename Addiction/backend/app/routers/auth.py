"""Google sign-in, current user and sign-out. All responses carry Cache-Control: no-store (see middleware)."""
import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from app import auth_service
from app.auth_service import OAUTH_COOKIE, SESSION_COOKIE, LoginFailure
from app.deps import CurrentUser, DbSession
from app.errors import ApiError, request_id_of
from app.schemas.auth import MeOut
from app.schemas.common import ERROR_401, ERROR_403, ERROR_503

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("mindevidence.auth")

OAUTH_COOKIE_PATH = "/api/auth/google"


def _failure_redirect(settings, reason: str) -> RedirectResponse:
    response = RedirectResponse(f"{settings.frontend_url}/?{urlencode({'auth_error': reason})}", status_code=302)
    response.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH)
    return response


@router.get(
    "/google/login",
    status_code=302,
    summary="Start Google sign-in",
    description="Redirects the browser to Google. Open it as a normal page navigation, not with fetch. "
                "Accepts no parameters (there is no redirect target to tamper with).",
    responses={302: {"description": "Redirect to Google."}, **ERROR_503},
)
def google_login(request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.google_configured:
        logger.info("login_unavailable request=%s reason=not_configured", request_id_of(request))
        raise ApiError(503, "auth_not_configured", "Google sign-in is not configured on this server.")
    url, cookie = auth_service.begin_login(settings)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        OAUTH_COOKIE, cookie, max_age=auth_service.OAUTH_LIFETIME_SECONDS, httponly=True,
        samesite="lax", secure=settings.cookie_secure, path=OAUTH_COOKIE_PATH)
    return response


@router.get(
    "/google/callback",
    status_code=302,
    summary="Google redirects back here",
    description="Verifies the one-time state and the Google ID token, then starts a new login session and redirects to the "
                "frontend. On any problem it redirects to the frontend with `?auth_error=access_denied|state_invalid|"
                "token_invalid|email_unverified`.",
    responses={302: {"description": "Redirect to the frontend."}},
)
def google_callback(
    request: Request,
    db: DbSession,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> Response:
    settings = request.app.state.settings
    rid = request_id_of(request)
    if not settings.google_configured:
        return _failure_redirect(settings, "access_denied")
    try:
        token, user_id = auth_service.complete_login(
            db, settings, request.cookies.get(OAUTH_COOKIE), state, code, error, request.app.state.used_states)
    except LoginFailure as failure:
        logger.warning("login_failed request=%s reason=%s", rid, failure.reason)
        return _failure_redirect(settings, failure.reason)

    logger.info("login_success request=%s user=%s", rid, user_id)
    response = RedirectResponse(f"{settings.frontend_url}/", status_code=302)
    response.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=settings.session_max_hours * 3600, httponly=True,
        samesite="lax", secure=settings.cookie_secure, path="/")
    return response


@router.get(
    "/me",
    response_model=MeOut,
    summary="Who am I",
    description="The signed-in user and the CSRF token to send with state-changing requests.",
    responses=ERROR_401,
)
def me(user: CurrentUser) -> MeOut:
    return MeOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role, csrf_token=user.csrf_token)


@router.post(
    "/logout",
    status_code=204,
    summary="Sign out",
    description="Revokes the login session on the server and clears the cookie. Requires the X-CSRF-Token header.",
    responses={**ERROR_401, **ERROR_403},
)
def logout(request: Request, user: CurrentUser, db: DbSession) -> Response:
    auth_service.logout(db, user)
    logger.info("logout request=%s user=%s", request_id_of(request), user.id)
    settings = request.app.state.settings
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure)
    return response
