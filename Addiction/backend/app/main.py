"""MindEvidence Lab API (Batch 03).

Run from backend/:
    uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
"""
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from app.config import Settings, StartupError, load_settings
from app.errors import install_error_handlers
from app.answers.service import Pipeline
from app.audit import AuditService
from app.deps import current_user, require_role
from app.diagnostics.checks import startup_summary
from app.llm.base import BaseLLMClient
from app.llm.concurrency import ConcurrencyLimitedClient
from app.llm.deepseek import DeepSeekClient
from app.middleware import REQUEST_ID_HEADER, NoStoreAuthMiddleware, RequestIdMiddleware
from app.schemas.common import ERROR_401
from app.retrieval.embedder import Embedder, EmbedderProvider
from app.retrieval.ratelimit import SlidingWindowLimiter
from app.routers import admin_audit, admin_diagnostics, admin_papers, audit, auth, health, papers, patients, retrieval, sessions
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
    {"name": "retrieval", "description": "Semantic search over the embedded research chunks."},
    {"name": "audit", "description": "Your activity timeline (metadata only) and answer feedback."},
]


def _warm_up(provider: EmbedderProvider) -> None:
    """Optional (RETRIEVAL_WARMUP=true): load the model at startup. A failure is only logged; search then answers 503."""
    try:
        provider.get()
    except Exception as error:
        logging.getLogger("mindevidence.retrieval").warning("warm-up skipped: %s", type(error).__name__)


def create_app(engine: Engine | None = None, settings: Settings | None = None, embedder: Embedder | None = None,
               llm_client: BaseLLMClient | None = None) -> FastAPI:
    settings = settings or load_settings()  # raises unless APP_ENV=development

    app = FastAPI(
        title="MindEvidence Lab API",
        version="0.4.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
    )
    app.state.engine = engine or get_engine()
    app.state.settings = settings
    line, problems = startup_summary(settings)
    startup_log = logging.getLogger("mindevidence.startup")
    if not startup_log.handlers and not logging.getLogger().handlers:  # under uvicorn nothing shows INFO lines by default
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        startup_log.addHandler(handler)
        startup_log.setLevel(logging.INFO)
    startup_log.info(line)
    for problem in problems:
        startup_log.warning("configuration: %s", problem)
    # The embedding model loads lazily on the first search (torch is optional). Tests pass a fake embedder.
    app.state.embedder_provider = EmbedderProvider.fixed(embedder) if embedder else EmbedderProvider()
    app.state.rate_limiter = SlidingWindowLimiter(settings.retrieval_rate_limit_per_minute)
    # The LLM client never makes a network call at construction; without a key it simply reports configured=False.
    if settings.graph_total_timeout_seconds <= settings.llm.timeout_seconds:
        raise StartupError("GRAPH_TOTAL_TIMEOUT_SECONDS must be larger than LLM_TIMEOUT_SECONDS.")
    # A local model serves one request at a time: model calls queue behind a small semaphore (LLM_MAX_CONCURRENCY).
    app.state.llm_client = ConcurrencyLimitedClient(
        llm_client or DeepSeekClient(settings.llm), settings.llm.max_concurrency, settings.llm.queue_wait_seconds)
    app.state.audit = AuditService(app.state.engine)  # the append-only audit log: its own transactions, fail-open
    app.state.answer_pipeline = Pipeline(settings, app.state.llm_client, app.state.embedder_provider,
                                         SlidingWindowLimiter(settings.answer_rate_limit_per_minute), audit=app.state.audit)
    if settings.retrieval_warmup and embedder is None:
        _warm_up(app.state.embedder_provider)
    app.state.used_states = {}  # OAuth states already consumed (state -> expiry), so a signed cookie works once

    # Added first = inner. Request ids are outermost so even CORS preflight responses carry one.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER, "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],  # the browser may read the retry hint of a 429/503
        allow_credentials=True,
    )
    app.add_middleware(NoStoreAuthMiddleware)
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    for router in (patients.router, papers.router, sessions.router, retrieval.router, audit.router):
        app.include_router(router, dependencies=[Depends(current_user)], responses=ERROR_401)  # 401 unless signed in
    # Administrator-only (401 when signed out, 403 for students). Read-only: nothing here starts an ingestion.
    for router in (admin_papers.router, admin_audit.router, admin_diagnostics.router):
        app.include_router(router, dependencies=[Depends(require_role("admin"))], responses=ERROR_401)
    return app


app = create_app()
