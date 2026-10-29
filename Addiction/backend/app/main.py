"""MindEvidence Lab API (Batch 03).

Run from backend/:
    uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from app.config import Settings, load_settings
from app.errors import install_error_handlers
from app.deps import current_user, require_role
from app.middleware import REQUEST_ID_HEADER, NoStoreAuthMiddleware, RequestIdMiddleware
from app.schemas.common import ERROR_401
from app.routers import admin_papers, auth, health, papers, patients, sessions
from db.config import get_engine

DESCRIPTION = """
Educational research assistant API for psychology students (addiction-treatment case studies).

**Development only, plain HTTP.** Sign in with Google (`GET /api/auth/google/login`); every route except
`/api/health` and `/api/auth/*` needs the session cookie, and state-changing requests need the `X-CSRF-Token`
header (see `docs/API_ACCESS_POLICY.md` for what is still not protected).

All patients are **fictional**. This is a teaching tool: it does not diagnose, prescribe or choose treatments.
"""

TAGS = [
    {"name": "health", "description": "Liveness and database check."},
    {"name": "auth", "description": "Google sign-in, current user and sign-out."},
    {"name": "patients", "description": "Synthetic patient cases and their histories."},
    {"name": "papers", "description": "Research corpus metadata (no document text)."},
    {"name": "admin", "description": "Administrator-only ingestion results, including full chunk text."},
    {"name": "sessions", "description": "Chat sessions and their messages."},
]


def create_app(engine: Engine | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()  # raises unless APP_ENV=development

    app = FastAPI(
        title="MindEvidence Lab API",
        version="0.4.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
    )
    app.state.engine = engine or get_engine()
    app.state.settings = settings
    app.state.used_states = {}  # OAuth states already consumed (state -> expiry), so a signed cookie works once

    # Added first = inner. Request ids are outermost so even CORS preflight responses carry one.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER, "X-CSRF-Token"],
        expose_headers=[REQUEST_ID_HEADER],
        allow_credentials=True,
    )
    app.add_middleware(NoStoreAuthMiddleware)
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    for router in (patients.router, papers.router, sessions.router):
        app.include_router(router, dependencies=[Depends(current_user)], responses=ERROR_401)  # 401 unless signed in
    # Administrator-only (401 when signed out, 403 for students). Read-only: nothing here starts an ingestion.
    app.include_router(admin_papers.router, dependencies=[Depends(require_role("admin"))], responses=ERROR_401)
    return app


app = create_app()
