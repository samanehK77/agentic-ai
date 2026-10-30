"""Administrator-only operator diagnostics. Never generates text with the model and never loads the embedding model."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from app.diagnostics.checks import Context, overall, run_all
from app.schemas.common import ERROR_403
from app.schemas.diagnostics import DiagnosticsReport

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get(
    "/diagnostics",
    response_model=DiagnosticsReport,
    summary="Operator diagnostics (admin)",
    description="Administrators only. Checks of the database, migrations, pgvector, the document index, the embedding model, the "
                "language model server (reachability and facts, no generation), sign-in configuration and the audit table. Each "
                "check is ok, warn or fail with a hint. Booleans, counts and codes only: no URLs, keys, paths or secrets. "
                "`/api/health` stays the minimal public check.",
    responses=ERROR_403,
)
def diagnostics(request: Request) -> DiagnosticsReport:
    state = request.app.state
    ctx = Context(state.engine, state.settings, state.embedder_provider, deep=False, audit_failures=state.audit.failures)
    checks = run_all(ctx)
    return DiagnosticsReport(status=overall(checks), generated_at=datetime.now(timezone.utc),
                             checks=[c.__dict__ for c in checks])
