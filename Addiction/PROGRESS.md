# Progress

Living log of where the project stands. Update it at the end of every batch.

## Batch status
| Batch | Description | Status |
|-------|-------------|--------|
| 00 | Scaffold, SPEC, CLAUDE.md, corpus PDFs | Done |
| 01 | Frontend with mock data | Done |
| 02 | PostgreSQL data model and seed | Done |
| 03 | FastAPI backend | Done |
| 04 | Google sign-in | Done (real Google login not yet tested by the user) |
| 05 | Document ingestion | Not started |
| 06 | pgvector retrieval | Not started |
| 07 | DeepSeek answers with citations | Not started |
| 08 | LangGraph orchestration | Not started |
| 09 | Observability, audit, and Gmail reports | Not started |
| 10 | Integration and classroom demo | Not started |

## Done so far
- GitHub private repo `samanehK77/agentic-ai`; project lives in `Addiction/`.
- Folder structure, `docs/SPEC.md`, `CLAUDE.md`, `.env.example`, `.gitignore`.
- Four research PDFs placed in `data/papers/` (git-ignored).
- Batch 01: vanilla HTML/CSS/ES-module frontend in `frontend/` with mock data (see `frontend/README.md`). Verified in the browser: 10 patients, chat, citations, mode switch, timeline, loading/empty/error/no-evidence states, no console errors, no `innerHTML`. Committed (c23c13b).
- Batch 02: PostgreSQL schema (6 tables), Alembic migration, idempotent seed of P-001..P-010, SQL queries, 74 passing pytest tests, `docs/DATA_DICTIONARY.md`, `docs/FRONTEND_INTEGRATION_PLAN.md`, `backend/README.md`. Committed (f5e2025).
- Batch 03: FastAPI API on port 8001 (health, patients, history, papers, chat sessions, messages), migration 0002 (`papers`, `chat_sessions`, `chat_messages`), papers seed, standard error format and request ids, CORS, `APP_ENV=development` guard, `docs/API.md`, `docs/API_ACCESS_POLICY.md`; frontend patient list and detail now load from the API. Committed.

## Open questions / decisions
- Document 4 is a psychosocial-interventions review, not the Cochrane review named in SPEC.md. Decision (user, Batch 04): keep this paper and continue; SPEC.md is left unchanged.

## Batch 01 decisions
- All data access is in `frontend/js/api.js`; Batch 03 swaps its bodies for `fetch()`.
- Demo states via `?state=loading|empty|error|no-evidence` and a Demo controls panel.
- Mock document titles are generic ("MOCK Document A"); nothing is attributed to WHO, NIDA or Cochrane.
- Replies depend only on mode; no-evidence replies cite nothing.
- Auto answer mode left out (optional in SPEC).
- Run with `cd frontend && python -m http.server 8000`.

## Batch 02 decisions
- Text natural keys (`P-001-H01`, ...) built from the patient id and list position: deterministic, idempotent upserts, and a CHECK ties every key to its patient.
- Vocabularies are `CHECK ... IN (...)` constraints (easy to extend in a later migration); the same lists live in `db/models.py` and a test confirms they match the database.
- `observed_behavior` and `protective_factor` are `kind` values in `triggers_and_risk_factors` (keeps the six tables requested). Use status has `supervised` for use inside a supervised program.
- `history_summary`, `treatment_summary` and `background` are stored on `patients` so the frontend can map its mock fields; tests check the detail tables agree (latest progress vs use status, interventions vs history events).
- pgvector: only the image is used now; `CREATE EXTENSION vector` belongs to Batch 06.
- Default DB host is `127.0.0.1` (not `localhost`): on Windows `localhost` hung on IPv6.
- Credentials only via environment variables or the git-ignored `.env`. I never read or created `.env`; verification used throwaway credentials in a temporary Docker project that was removed.
- Seed text supersedes the mock text from Batch 01; the integration plan lists the differences.

## Batch 03 decisions
- **Development only, no authentication.** The app refuses to start unless `APP_ENV=development` (you must add it to your `.env`); the run command binds to `127.0.0.1`. `docs/API_ACCESS_POLICY.md` says plainly that it is not secure; ownership checks (401/403) arrive with Batch 04.
- Layers: routers (no SQL) -> `services.py` (rules, 404s) -> repositories (all SQL). The profile and history endpoints execute the reviewed `db/queries/*.sql` files; history paging appends LIMIT/OFFSET to the same ordered query. `patient_history.sql` gained a `date_precision` column.
- One error format for everything (422, 404, 405, 503, 500); validation details never echo the input; 500s are generic. Unreachable database -> 503 `service_unavailable` (also for the other endpoints).
- `X-Request-ID`: accepted only if it matches `^[A-Za-z0-9-]{1,64}$`, otherwise replaced by a UUID; added to every response and error body.
- `limit` above 100 is a 422, not silently capped.
- Added `GET /api/sessions/{session_id}` (not in the brief) so the `Location` header of `POST /api/sessions` points at a real resource.
- `chat_sessions.patient_id` is `ON DELETE RESTRICT`; `chat_messages` cascade with their session. `owner_id` is nullable with no foreign key until Batch 04.
- Papers: metadata only, taken from file names and `data/papers/README.md`; PDFs were never opened. Unknown publisher or year is stored as the text `unknown`. No file paths are stored or exposed. **The fourth document is a psychosocial-interventions review, not the Cochrane review named in `docs/SPEC.md`.**
- Frontend: no silent fallback to mock data; `?source=mock` shows a "DEMO DATA (mock)" label. Chat replies and citation chunks stay mock.

## Batch 04 decisions
- **Google OAuth Authorization Code + PKCE (S256) + OIDC**, scopes `openid email profile` only. State, nonce and PKCE verifier live in a signed (HMAC with `SESSION_SECRET`), HttpOnly, 10-minute cookie that is deleted at the start of the callback; used states are also remembered in memory so a captured cookie cannot be replayed. No `next` parameter.
- ID token checked by the `google-auth` library (signature, issuer, audience, expiry) plus our own nonce check; `email_verified` must be exactly `true`. Google's tokens are discarded. The token exchange uses `httpx` with TLS verification on.
- Identity is `users.google_sub`; email is just an updatable attribute. Role `admin` only for verified emails in `ADMIN_EMAILS`, recomputed at every login.
- Login session: cookie `me_session`, random 256-bit token, only its SHA-256 in `auth_sessions`; new token at each login (no fixation); idle (30 min) and absolute (8 h) limits, both configurable; logout sets `revoked_at`; expired rows are deleted lazily.
- CSRF: per-session token in `GET /api/auth/me`, header `X-CSRF-Token`, constant-time compare, plus Origin check. Implemented inside the `current_user` dependency so it cannot be forgotten on a new route.
- Every `/api/*` router except health and auth is protected at `include_router` level. `require_role` added (tested through a test-only route).
- Ownership: sessions filtered by `owner_id`; foreign or ownerless sessions are 404 `not_found` (existence not revealed). Legacy NULL-owner rows were kept, not deleted.
- CORS now: `http://localhost:8000` only, credentials allowed, `X-CSRF-Token` allowed header. 127.0.0.1 removed everywhere (cookies are host-scoped).
- Migration 0003 adds `users`, `auth_sessions`, the FK `chat_sessions.owner_id -> users.id` (`ON DELETE RESTRICT`).
- The session fixtures in `tests/conftest.py` create users and login sessions directly in the test database; Google is faked (a local RSA key signs test ID tokens, so the real verification code runs).
- Test-suite changes to older tests (not weakened): the PII scan skips `users`/`auth_sessions` (sign-in data), the table lists include the new tables, the owner-FK test now expects the FK, CORS tests use `localhost`.

## Known issues
- **The real Google login has not been tested by a human.** Tests use a fake Google. Follow the checklist in `docs/GOOGLE_AUTH_SETUP.md`.
- No rate limiting; plain HTTP; `/docs` is open in development; used OAuth states are remembered per process only (see `docs/API_ACCESS_POLICY.md`).
- The signed-in UI state (name and sign-out button) could not be seen in my checks because it needs a real Google login; the signed-out state, `?auth_error=` message and `?source=mock` were checked in the browser.
- The patient detail view makes two requests (profile + history) because the profile endpoint does not embed history events.
- Starlette's test client prints a deprecation warning about `httpx` (it prefers a newer `httpx2` package); tests still pass. The brief asked for httpx, so it is kept.
- The `?state=error` demo is applied in the frontend before any request, so it does not test the API's own errors; stopping the API does.
- Only visual check done by DOM inspection; a screenshot could not be captured because the app window was hidden.

## How to resume (Windows PowerShell)
1. `cd $HOME\Desktop\agentic-ai\Addiction`, then `docker compose up -d` (data is kept in the Docker volume).
2. Terminal A, API: `cd backend`, `.\.venv\Scripts\Activate.ps1`, `alembic upgrade head`, `uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload`.
3. Terminal B, frontend: `cd frontend`, `python -m http.server 8000`, open <http://localhost:8000>.
4. `.env` must contain the database settings, `APP_ENV=development`, `SESSION_SECRET` (32+ characters) and the Google variables from `docs/GOOGLE_AUTH_SETUP.md` (git-ignored, never committed). Always open `http://localhost:8000` (not 127.0.0.1).

## Next step
Test the real Google login yourself (`docs/GOOGLE_AUTH_SETUP.md`, checklist), then Batch 05: document ingestion.
