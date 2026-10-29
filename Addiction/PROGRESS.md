# Progress

Living log of where the project stands. Update it at the end of every batch.

## Batch status
| Batch | Description | Status |
|-------|-------------|--------|
| 00 | Scaffold, SPEC, CLAUDE.md, corpus PDFs | Done |
| 01 | Frontend with mock data | Done |
| 02 | PostgreSQL data model and seed | Done |
| 03 | FastAPI backend | Done |
| 04 | Google sign-in | Done (real login tested by the user) |
| 05 | Document ingestion | Done |
| 06 | pgvector retrieval | Done (committed locally; not pushed) |
| 07 | DeepSeek answers with citations | Not started |
| 08 | LangGraph orchestration | Not started |
| 09 | Observability, audit, and Gmail reports | Not started |
| 10 | Integration and classroom demo | Not started |

## Done so far
- GitHub private repo `samanehK77/agentic-ai`; project lives in `Addiction/`.
- Folder structure, `docs/SPEC.md`, `CLAUDE.md`, `.env.example`, `.gitignore`.
- Five research PDFs in `data/papers/` (git-ignored).
- Batch 01: vanilla HTML/CSS/ES-module frontend in `frontend/` with mock data (see `frontend/README.md`). Verified in the browser: 10 patients, chat, citations, mode switch, timeline, loading/empty/error/no-evidence states, no console errors, no `innerHTML`. Committed (c23c13b).
- Batch 02: PostgreSQL schema (6 tables), Alembic migration, idempotent seed of P-001..P-010, SQL queries, 74 passing pytest tests, `docs/DATA_DICTIONARY.md`, `docs/FRONTEND_INTEGRATION_PLAN.md`, `backend/README.md`. Committed (f5e2025).
- Batch 03: FastAPI API on port 8001 (health, patients, history, papers, chat sessions, messages), migration 0002 (`papers`, `chat_sessions`, `chat_messages`), papers seed, standard error format and request ids, CORS, `APP_ENV=development` guard, `docs/API.md`, `docs/API_ACCESS_POLICY.md`; frontend patient list and detail now load from the API. Committed.

- Batch 05: PDF ingestion pipeline (`python -m app.ingestion`): five registered PDFs extracted with PyMuPDF, cleaned, chunked to about 220 tokens and stored (migration 0004: ingestion fields on `papers`, `paper_chunks`, `ingestion_runs`); admin-only read endpoints; `docs/INGESTION.md`. 488 tests passing at the last full run.

- Batch 06: embeddings with all-MiniLM-L6-v2 (migration 0005, pgvector, exact search, no ANN index), `python -m app.embedding`, `POST /api/retrieval/search`, real evidence in the Evidence Inspector, `python -m app.eval_retrieval`, `docs/RETRIEVAL.md`. 585 tests (584 passed with torch installed, 1 skipped).

## Open questions / decisions
- Resolved in Batch 05: the Cochrane review named in SPEC.md is now the fifth document; the psychosocial-interventions review stays as an additional document.

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

## Batch 05 decisions
- **Google login confirmed by the user** (2026-10-29): the manual checklist in `docs/GOOGLE_AUTH_SETUP.md` passed, including the second-account isolation test. The corresponding known issue was removed.
- **Chunk size deviates from SPEC:** about 220 tokens (max 250, overlap 40) instead of 400-700, because all-MiniLM-L6-v2 truncates at 256 word pieces. Tokens are counted with the model's own `tokenizer.json` (pinned revision `1110a243`, no model weights, no torch); counting includes [CLS]/[SEP]. `docs/SPEC.md` Retrieval line updated. The parameters and tokenizer revision are stored in `papers.chunking_version`, so changing them triggers re-chunking.
- **Corpus is five documents** (Cochrane review added; the psychosocial review stays as an additional document). Metadata read from the first pages of each PDF; `metadata_source` records `document_text` vs `project_list`. NIDA's year is 2018 (the "Revised January 2018" third edition; first published 2014). The Med Sci Monit review's publishing company is not stated in the text, so the journal name is recorded.
- Ingestion is a **CLI** (`python -m app.ingestion`), idempotent (file hash + chunking_version), one transaction per document, PostgreSQL advisory lock, no OCR, no network. No HTTP endpoint triggers it.
- Admin endpoints are read-only (`/api/admin/papers`, `/papers/{id}`, `/papers/{id}/chunks`, `/chunks/{id}`), 401 / 403 / 404 / 422; file names, paths and hashes are never returned; full chunk text only to admins.
- Everything about structure (headers/footers, ToC, references, tables, section titles) is heuristic; limits are listed in `docs/INGESTION.md`.
- Test-suite changes to older tests (not weakened): five papers instead of four, new tables in the table list, new CHECK constraints in the vocabulary drift test, new admin routes in the OpenAPI list.

## Batch 05 results on this machine (real run, 2026-10-29)
All five documents `ingested`, none `failed` or `needs_ocr`; 2,579 chunks in total, all at most 250 tokens. A second run reported every document `unchanged`.

| Document | Pages | Low-text pages | Chunks | Tokens min / median / max | Notes |
|----------|-------|----------------|--------|---------------------------|-------|
| Cochrane combined interventions (2025) | 113 | 0 | 802 | 3 / 83 / 250 | 557 header/footer blocks and 44 dot-leader lines removed; 144 reference chunks; many short chunks from tables and study characteristics |
| NIDA Principles (3rd ed.) | 47 | 0 | 168 | 46 / 174 / 242 | has a PDF outline (115 entries); no reference section detected |
| Psychosocial interventions review | 12 | 0 | 97 | 7 / 179 / 221 | 27 reference chunks |
| WHO mhGAP guideline 2023 | 184 | 4 (pages 2, 18, 33, 183) | 843 | 6 / 141 / 250 | 116 reference chunks |
| WHO mhGAP Intervention Guide v2.0 | 174 | 10 | 669 | 3 / 63 / 250 | landscape, flowcharts and tables: about 145 chunks under 20 tokens and noisy section titles (for example "PROTOCOL") |

Retrieval quality was not measured (Batch 06). No chunk was flagged `possible_injection`.

## Batch 06 decisions
- **Embedding model and fingerprint:** `sentence-transformers/all-MiniLM-L6-v2` at the revision pinned in Batch 05 (`1110a243...`), 384 dimensions, L2-normalized, CPU only, loaded offline; the weights file is checked against the pinned SHA-256 at load. Every vector stores its fingerprint; search refuses (503 `index_incompatible`) if any embedded chunk has another one.
- **Eligibility:** only `body` / `table_or_figure` chunks with at least 20 tokens (`EMBED_MIN_TOKENS`) are embedded; references, front matter and tiny fragments are `skipped` (no vector). Re-evaluated at every run; re-ingested chunks come back as `pending`.
- **Exact search, no ANN index** (about 2,000 vectors; approximate indexes can return fewer than k rows with a WHERE filter). All filters are in the WHERE clause before `ORDER BY ... LIMIT`. Reconsider HNSW above about 50,000 vectors, evaluated against exact results (`docs/RETRIEVAL.md`).
- **torch is optional:** `requirements-embeddings.txt` is separate; the API and the tests run without it (search answers 503 `retrieval_unavailable`). The model loads lazily once (optional warm-up `RETRIEVAL_WARMUP`); the route is a sync function so FastAPI runs it in its thread pool.
- **Policy decision:** signed-in students receive the text of the chunks a search returns (at most 20 of at most 250 tokens, rate limited to 30 searches per minute per user by default); admin routes are unchanged (`docs/API_ACCESS_POLICY.md`). Query text is never logged.
- **No fabricated citations:** in RAG and Both mode the frontend shows the explicit placeholder "Answer generation arrives in Batch 07. Showing retrieved evidence only." with no citations; a citation id is always a real `chunk_id`.
- Correction to a note in the Batch 06 prompt: Batch 05 had already been pushed (`64ee02f`) before Batch 06 started.
- Changes to older tests (not weakened): the Batch 05 "no vector extension" test now checks migration 0004 on its own; table/vocabulary/OpenAPI lists updated.

## Batch 06 results on this machine (real run, 2026-10-29)
- **Embedding:** 2,002 chunks embedded in 30.7 s (63 batches of 32); 577 skipped: 287 references, 16 front matter, 274 too short. Second run: "0 pending", 0.1 s, nothing changed. 0 failed.
- **Evaluation (smoke-level, 15 in-domain + 4 out-of-domain queries, keyword labels, NOT a benchmark):** Recall@1 0.80, Recall@3 0.93, Recall@5 0.93, MRR 0.87. Top-1 cosine similarity: in-domain min 0.63 / median 0.71 / max 0.79; out-of-domain min 0.19 / median 0.23 / max 0.28 (the two ranges did not overlap on these queries).
- **Weakest query:** "behavioral couples therapy" found nothing relevant in the top 10: the three matching chunks of the psychosocial review exist and rank 2nd, 5th and 20th when the search is limited to that paper, but chunks of other documents outrank them across the whole corpus. Labels were not changed to fit this.
- **Suspicious:** 14 of the 95 chunks in the top 5 of all queries have fewer than 40 tokens; one 27-token table chunk of the psychosocial review (`...-c0050`) shows up for three different queries. Out-of-domain queries still return chunks (similarity 0.18 to 0.28): a threshold is needed in Batch 07 (the gap above suggests somewhere around 0.4 to 0.55, to be checked with more queries).
- **Browser check:** the signed-out state, `?source=mock` and the rendering of real chunks (a synthetic hit with an `<img onerror>` payload showed as plain text, the warning badge and the "retrieved" evidence label appear, the placeholder reply has no citations) were verified in the browser pane. A real search from the page was **not** verified end to end because it needs a Google sign-in; the endpoint itself is covered by 44 API tests with a fake embedder and by the evaluation run through the same search code.

## Known issues
- Retrieval: short table/flowchart fragments from ingestion still rank high for some queries; no reranking or keyword/hybrid search; the evaluation set is tiny.
- Ingestion heuristics are imperfect (see `docs/INGESTION.md`): the Intervention Guide's flowcharts produce many tiny fragments, some Cochrane running-header text survives as short chunks, and section titles can be noisy.
- The symbolic-link rejection test is skipped on this Windows machine because creating symlinks needs extra permission; the check itself is in `resolve_pdf`.
- No rate limiting; plain HTTP; `/docs` is open in development; used OAuth states are remembered per process only (see `docs/API_ACCESS_POLICY.md`).
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
Batch 07: DeepSeek answers with citations (backend only, behind a provider interface; use a similarity threshold and keep citations pointing only to retrieved chunks).
