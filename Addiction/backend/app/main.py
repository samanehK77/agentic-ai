"""MindEvidence Lab API (Batch 03).

Run from backend/:
    uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from app.config import Settings, load_settings
from app.errors import install_error_handlers
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.routers import health, papers, patients, sessions
from db.config import get_engine

DESCRIPTION = """
Educational research assistant API for psychology students (addiction-treatment case studies).

**Development only, not secure.** There is no authentication yet: every endpoint is open to anyone who can
reach the server, so it must run on `127.0.0.1` only (see `docs/API_ACCESS_POLICY.md`).

All patients are **fictional**. This is a teaching tool: it does not diagnose, prescribe or choose treatments.
"""

TAGS = [
    {"name": "health", "description": "Liveness and database check."},
    {"name": "patients", "description": "Synthetic patient cases and their histories."},
    {"name": "papers", "description": "Research corpus metadata (no document text yet)."},
    {"name": "sessions", "description": "Chat sessions and their messages."},
]


def create_app(engine: Engine | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()  # raises unless APP_ENV=development

    app = FastAPI(
        title="MindEvidence Lab API",
        version="0.3.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
    )
    app.state.engine = engine or get_engine()

    # Added first = inner. Request ids are outermost so even CORS preflight responses carry one.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        allow_credentials=False,
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    for router in (health.router, patients.router, papers.router, sessions.router):
        app.include_router(router)
    return app


app = create_app()
