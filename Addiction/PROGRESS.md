# Progress

Living log of where the project stands. Update it at the end of every batch.

## Batch status
| Batch | Description | Status |
|-------|-------------|--------|
| 00 | Scaffold, SPEC, CLAUDE.md, corpus PDFs | Done |
| 01 | Frontend with mock data | Done |
| 02 | PostgreSQL data model and seed | Done |
| 03 | FastAPI backend | Done |
| 04 | Google sign-in | Not started |
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
- Document 4 is a psychosocial-interventions review, not the Cochrane review named in SPEC.md.

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

## Known issues
- The patient detail view makes two requests (profile + history) because the profile endpoint does not embed history events.
- Starlette's test client prints a deprecation warning about `httpx` (it prefers a newer `httpx2` package); tests still pass. The brief asked for httpx, so it is kept.
- The `?state=error` demo is applied in the frontend before any request, so it does not test the API's own errors; stopping the API does.
- Only visual check done by DOM inspection; a screenshot could not be captured because the app window was hidden.

## How to resume (Windows PowerShell)
1. `cd $HOME\Desktop\agentic-ai\Addiction`, then `docker compose up -d` (data is kept in the Docker volume).
2. Terminal A, API: `cd backend`, `.\.venv\Scripts\Activate.ps1`, `uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload`.
3. Terminal B, frontend: `cd frontend`, `python -m http.server 8000`, open <http://localhost:8000>.
4. `.env` must contain the database settings and `APP_ENV=development` (git-ignored, never committed).

## Next step
Batch 04: Google sign-in (replace the development-only access with real authentication and session ownership).
