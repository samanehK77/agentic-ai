"""Health diagnostics for operators: ok / warn / fail with a plain-language hint.

Every check reports booleans, counts, short codes and model facts only. It never returns a URL (with or without
credentials), a key, a file path or any secret. The same functions serve `python -m app.diagnostics` and the admin
endpoint `GET /api/admin/diagnostics`. Nothing here generates text with the model unless `deep` is requested by the CLI
(the endpoint never does), and nothing writes to the database."""
import importlib.util
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import retrieval as retrieval_repo
from app.retrieval.embedder import WEIGHTS_FILE, EmbedderProvider
from app.ingestion.config import BACKEND_DIR

OK, WARN, FAIL = "ok", "warn", "fail"
PROBE_TIMEOUT_SECONDS = 5.0


@dataclass
class Check:
    name: str
    status: str
    message: str  # what is the matter, or that all is well
    hint: str = ""  # how to fix it (empty when ok)
    facts: dict = field(default_factory=dict)  # booleans, counts, short codes only


@dataclass
class Context:
    engine: Engine
    settings: Settings
    provider: EmbedderProvider
    deep: bool = False
    audit_failures: int | None = None
    http_client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=PROBE_TIMEOUT_SECONDS)


def _safe(check: Callable[[Context], list[Check]], ctx: Context, name: str) -> list[Check]:
    """A check that crashes becomes a fail with the exception class only (never its text, which may hold a URL or secret)."""
    try:
        return check(ctx)
    except Exception as error:
        return [Check(name, FAIL, f"The check itself failed ({type(error).__name__}).", "Look at the server log.")]


# ---------------------------------------------------------------- database

def check_database(ctx: Context) -> list[Check]:
    try:
        with Session(ctx.engine) as db:
            db.execute(text("SELECT 1"))
            revision = db.scalar(text("SELECT version_num FROM alembic_version")) if _table_exists(db, "alembic_version") else None
            vector = bool(db.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")))
    except Exception as error:
        return [Check("database", FAIL, "The database is not reachable.",
                      "Start it with: docker compose up -d (and check POSTGRES_* in .env).", {"reachable": False, "error": type(error).__name__})]
    out = [Check("database", OK, "The database answers.", facts={"reachable": True})]
    head = _alembic_head()
    if revision is None:
        out.append(Check("migrations", FAIL, "The database has no migration history.", "Run: alembic upgrade head (from backend/).",
                         {"at_head": False, "current": None}))
    elif revision == head:
        out.append(Check("migrations", OK, "The schema is at the latest migration.", facts={"at_head": True, "current": revision}))
    else:
        out.append(Check("migrations", FAIL, "The schema is not at the latest migration.", "Run: alembic upgrade head (from backend/).",
                         {"at_head": False, "current": revision, "head": head}))
    out.append(Check("pgvector", OK if vector else FAIL, "The pgvector extension is installed." if vector else "The pgvector extension is missing.",
                     "" if vector else "Use the pgvector/pgvector image (docker compose up -d) and run: alembic upgrade head.",
                     {"present": vector}))
    return out


def _table_exists(db: Session, name: str) -> bool:
    return bool(db.scalar(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{name}"}))


def _alembic_head() -> str | None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


# ---------------------------------------------------------------- corpus and embeddings

def check_corpus(ctx: Context) -> list[Check]:
    with Session(ctx.engine) as db:
        papers = db.scalar(text("SELECT count(*) FROM papers WHERE ingest_status = 'ingested'")) or 0
        total_papers = db.scalar(text("SELECT count(*) FROM papers")) or 0
        row = db.execute(text("""
            SELECT count(*) AS chunks,
                   count(*) FILTER (WHERE embedding_status = 'embedded') AS embedded,
                   count(*) FILTER (WHERE embedding_status = 'pending') AS pending,
                   count(*) FILTER (WHERE embedding_status = 'skipped') AS skipped
            FROM paper_chunks""")).mappings().one()
        embedded, fingerprints = retrieval_repo.index_state(db)
    facts = {"papers_registered": total_papers, "papers_ingested": papers, **dict(row)}
    out = []
    if papers == 0 or row["chunks"] == 0:
        out.append(Check("corpus", FAIL, "No documents have been ingested.", "Place the PDFs in data/papers/ and run: python -m app.ingestion.", facts))
    elif papers < total_papers:
        out.append(Check("corpus", WARN, f"{papers} of {total_papers} documents are ingested.", "Run: python -m app.ingestion (see docs/INGESTION.md).", facts))
    else:
        out.append(Check("corpus", OK, "All registered documents are ingested.", facts=facts))
    running = ctx.provider.fingerprint
    index_facts = {"embedded_chunks": embedded, "index_fingerprints": len(fingerprints), "matches_running_model": fingerprints == [running]}
    if embedded == 0:
        out.append(Check("index", FAIL, "No chunk has been embedded yet.", "Run: python -m app.embedding (needs requirements-embeddings.txt).", index_facts))
    elif fingerprints != [running]:
        out.append(Check("index", FAIL, "The stored embeddings come from a different model or settings.",
                         "Re-embed with: python -m app.embedding --force", index_facts))
    elif row["pending"] > 0:
        out.append(Check("index", WARN, f"{row['pending']} chunk(s) are still waiting to be embedded.", "Run: python -m app.embedding", index_facts))
    else:
        out.append(Check("index", OK, "The index matches the embedding model.", facts=index_facts))
    return out


def check_embedder(ctx: Context) -> list[Check]:
    """State only. The model is loaded here only with --deep (it takes seconds and several hundred MB of memory)."""
    loaded = ctx.provider._embedder is not None
    weights = _model_dir() / WEIGHTS_FILE
    facts = {"loaded": loaded, "weights_present": weights.is_file(), "sentence_transformers_installed": importlib.util.find_spec("sentence_transformers") is not None}
    if loaded:
        return [Check("embedding_model", OK, "The embedding model is loaded.", facts=facts)]
    if not facts["sentence_transformers_installed"]:
        return [Check("embedding_model", WARN, "sentence-transformers is not installed: search and RAG answers return 503.",
                      "Run: pip install -r requirements-embeddings.txt", facts)]
    if not facts["weights_present"]:
        return [Check("embedding_model", WARN, "The embedding model files are missing: search and RAG answers return 503.",
                      "Download the model as described in docs/RETRIEVAL.md.", facts)]
    if ctx.deep:
        started = time.perf_counter()
        try:
            ctx.provider.get()
        except Exception as error:
            return [Check("embedding_model", FAIL, "The embedding model could not be loaded.", "See docs/RETRIEVAL.md.",
                          {**facts, "error": type(error).__name__})]
        return [Check("embedding_model", OK, "The embedding model loaded.", facts={**facts, "loaded": True, "load_seconds": round(time.perf_counter() - started, 1)})]
    return [Check("embedding_model", OK, "The model files and packages are present; the model loads on the first search.", facts=facts)]


def _model_dir() -> Path:
    import os

    from app.retrieval.embedder import DEFAULT_MODEL_DIR
    return Path(os.environ.get("EMBEDDING_MODEL_PATH", "").strip() or DEFAULT_MODEL_DIR)


# ---------------------------------------------------------------- language model

def _root_url(base_url: str) -> str:
    return re.sub(r"/v1/?$", "", base_url.rstrip("/"))


def _headers(settings: Settings) -> dict:
    return {"Authorization": f"Bearer {settings.llm.api_key}"} if settings.llm.api_key else {}


def check_llm(ctx: Context) -> list[Check]:
    llm = ctx.settings.llm
    base_facts = {"configured": llm.configured, "local": llm.local, "model": llm.model}
    if not llm.configured:
        return [Check("llm", FAIL, "No language model is configured.",
                      "Set LLM_BASE_URL and LLM_MODEL for a local Ollama model, or DEEPSEEK_API_KEY for the remote provider.", base_facts)]
    try:
        with ctx.http_client_factory() as http:
            response = http.get(llm.base_url.rstrip("/") + "/models", headers=_headers(ctx.settings))
    except httpx.HTTPError as error:
        return [Check("llm", FAIL, "The model server is not reachable.",
                      "Start Ollama and check LLM_BASE_URL (from a container use host.docker.internal).",
                      {**base_facts, "reachable": False, "error": type(error).__name__})]
    if response.status_code in (401, 403):
        return [Check("llm", FAIL, "The model server rejected the credentials.", "Check the API key.", {**base_facts, "reachable": True, "authorized": False})]
    if response.status_code != 200:
        return [Check("llm", WARN, "The model server answered, but not with a model list.", "Check that LLM_BASE_URL ends with /v1.",
                      {**base_facts, "reachable": True, "status_code": response.status_code})]
    try:
        names = {item.get("id") for item in response.json().get("data", [])}
    except ValueError:
        names = set()
    listed = llm.model in names or f"{llm.model}:latest" in names
    facts = {**base_facts, "reachable": True, "models_listed": len(names), "model_listed": listed}
    out = [Check("llm", OK if listed else WARN, "The model server is reachable and the model is installed." if listed
                 else "The model server is reachable, but the configured model is not in its list.",
                 "" if listed else "Pull or create the model (for Ollama: ollama list, ollama pull / ollama create).", facts)]
    out.extend(_model_facts(ctx))
    if ctx.deep:
        out.append(_deep_generation(ctx))
    return out


def _model_facts(ctx: Context) -> list[Check]:
    """Parameter size, quantization and context length, when the server exposes them (Ollama's /api/show). No file paths."""
    llm = ctx.settings.llm
    if not llm.local:
        return [Check("llm_model_facts", OK, "A remote provider: model details are not exposed by this check.", facts={"exposed": False})]
    try:
        with ctx.http_client_factory() as http:
            response = http.post(_root_url(llm.base_url) + "/api/show", json={"model": llm.model})
        info = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        info = {}
    if not info:
        return [Check("llm_model_facts", OK, "The server does not expose model details (Ollama's /api/show was not available).", facts={"exposed": False})]
    details = info.get("details") or {}
    context = _context_length(info)
    needed = llm.context_token_budget + llm.max_output_tokens
    facts = {"exposed": True, "parameter_size": _short(details.get("parameter_size")), "quantization": _short(details.get("quantization_level")),
             "context_length": context, "tokens_needed": needed}
    if context is not None and context < needed:
        return [Check("llm_model_facts", WARN, f"The model's context length ({context}) is smaller than the prompt budget plus the output limit ({needed}): prompts may be silently truncated.",
                      "Raise the model's context (Ollama: num_ctx in the Modelfile) or lower LLM_CONTEXT_TOKEN_BUDGET / LLM_MAX_OUTPUT_TOKENS.", facts)]
    return [Check("llm_model_facts", OK, "Model details read from the local server.", facts=facts)]


def _short(value) -> str | None:
    return value[:40] if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.\- ]+", value) else None


def _context_length(info: dict) -> int | None:
    """The context the model really runs with: num_ctx from its parameters if set, else the architecture's maximum."""
    match = re.search(r"^\s*num_ctx\s+(\d+)", info.get("parameters") or "", re.MULTILINE)
    if match:
        return int(match.group(1))
    for key, value in (info.get("model_info") or {}).items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value
    return None


def _deep_generation(ctx: Context) -> Check:
    """ONE tiny real generation (CLI --deep only, after the owner approved it): no patient data, no document text."""
    from app.llm.base import LLMError, LLMMessage
    from app.llm.deepseek import DeepSeekClient

    client = DeepSeekClient(ctx.settings.llm)
    started = time.perf_counter()
    try:
        result = client.complete([LLMMessage("system", "You reply with a single json object and nothing else."),
                                  LLMMessage("user", 'Return the json object {"ok": true}.')], json_mode=True, max_tokens=60, temperature=0.0)
    except LLMError as error:
        return Check("llm_generation", FAIL, "The tiny test generation failed.", "Check the model server log and LLM_TIMEOUT_SECONDS.",
                     {"error": type(error).__name__})
    seconds = round(time.perf_counter() - started, 1)
    return Check("llm_generation", OK, "One tiny generation worked.",
                 facts={"seconds": seconds, "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens, "finish_reason": result.finish_reason[:20]})


# ---------------------------------------------------------------- sign-in, environment, audit

def check_environment(ctx: Context) -> list[Check]:
    s = ctx.settings
    out = [Check("environment", OK if s.app_env == "development" else FAIL, f"APP_ENV is {s.app_env!r}." if s.app_env == "development"
                 else "APP_ENV must be 'development': this is a local development setup.", "" if s.app_env == "development" else "Set APP_ENV=development.",
                 {"app_env": s.app_env[:20]})]
    present = {"client_id": bool(s.google_client_id), "client_secret": bool(s.google_client_secret), "redirect_uri": bool(s.google_redirect_uri),
               "session_secret": len(s.session_secret) >= 32, "admin_emails": len(s.admin_emails)}
    if s.google_configured:
        out.append(Check("google_sign_in", OK, "Google sign-in variables are present (their values are not shown; the round trip itself is not tested here).",
                         facts=present))
    else:
        out.append(Check("google_sign_in", WARN, "Google sign-in is not configured: nobody can sign in.", "See docs/GOOGLE_AUTH_SETUP.md.", present))
    if not s.admin_emails:
        out.append(Check("admin_accounts", WARN, "No administrator e-mail is configured: the admin pages stay closed.", "Set ADMIN_EMAILS.", {"admin_emails": 0}))
    return out


def check_audit(ctx: Context) -> list[Check]:
    with Session(ctx.engine) as db:
        exists = _table_exists(db, "audit_events")
        can_insert = bool(db.scalar(text("SELECT has_table_privilege(current_user, 'audit_events', 'INSERT')"))) if exists else False
        trigger = bool(db.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_audit_events_append_only' AND NOT tgisinternal"))) if exists else False
    facts = {"table_present": exists, "insert_privilege": can_insert, "append_only_trigger": trigger, "write_failures_since_start": ctx.audit_failures}
    if not exists:
        return [Check("audit_log", FAIL, "The audit table is missing.", "Run: alembic upgrade head (from backend/).", facts)]
    if not can_insert:
        return [Check("audit_log", FAIL, "The database user cannot write audit events.", "Grant INSERT on audit_events.", facts)]
    if not trigger:
        return [Check("audit_log", WARN, "The append-only trigger is missing: audit rows could be changed.", "Run: alembic upgrade head.", facts)]
    if ctx.audit_failures:
        return [Check("audit_log", WARN, f"{ctx.audit_failures} audit write(s) failed since the server started.", "Look at the server log for audit_write_failed lines.", facts)]
    return [Check("audit_log", OK, "The audit table is writable and append-only.", facts=facts)]


CHECKS = (("database", check_database), ("corpus", check_corpus), ("embedding_model", check_embedder), ("llm", check_llm),
          ("environment", check_environment), ("audit_log", check_audit))


def run_all(ctx: Context) -> list[Check]:
    results: list[Check] = []
    for name, check in CHECKS:
        results.extend(_safe(check, ctx, name))
    return results


def overall(checks: list[Check]) -> str:
    statuses = {c.status for c in checks}
    return FAIL if FAIL in statuses else WARN if WARN in statuses else OK


def startup_summary(settings: Settings) -> tuple[str, list[str]]:
    """One safe line for the log at startup and the configuration problems as short warnings (never a value)."""
    warnings = []
    if not settings.google_configured:
        warnings.append("google sign-in is not configured")
    if not settings.llm.configured:
        warnings.append("no language model is configured")
    if not settings.admin_emails:
        warnings.append("no administrator e-mail is configured")
    if settings.retrieval_min_similarity is None:
        warnings.append("the retrieval similarity threshold is switched off")
    line = (f"startup env={settings.app_env} google={'configured' if settings.google_configured else 'missing'} "
            f"llm={'local' if settings.llm.local else 'remote' if settings.llm.configured else 'missing'} "
            f"admins={len(settings.admin_emails)} top_k={settings.answer_top_k}")
    return line, warnings
