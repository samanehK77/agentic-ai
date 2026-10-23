# Progress

Living log of where the project stands. Update it at the end of every batch.

## Batch status
| Batch | Description | Status |
|-------|-------------|--------|
| 00 | Scaffold, SPEC, CLAUDE.md, corpus PDFs | Done |
| 01 | Frontend with mock data | Done |
| 02 | PostgreSQL data model and seed | Done |
| 03 | FastAPI backend | Not started |
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
- Batch 02: PostgreSQL schema (6 tables), Alembic migration, idempotent seed of P-001..P-010, SQL queries, 74 passing pytest tests, `docs/DATA_DICTIONARY.md`, `docs/FRONTEND_INTEGRATION_PLAN.md`, `backend/README.md`. Not yet committed.

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

## Known issues
- Only visual check done by DOM inspection; a screenshot could not be captured because the app window was hidden.

## Next step
Batch 03: FastAPI backend (patient endpoints on top of this schema).
