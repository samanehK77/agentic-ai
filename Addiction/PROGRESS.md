# Progress

Living log of where the project stands. Update it at the end of every batch.

## Batch status
| Batch | Description | Status |
|-------|-------------|--------|
| 00 | Scaffold, SPEC, CLAUDE.md, corpus PDFs | Done |
| 01 | Frontend with mock data | Done |
| 02 | PostgreSQL data model and seed | Not started |
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
- Batch 01: vanilla HTML/CSS/ES-module frontend in `frontend/` with mock data (see `frontend/README.md`). Verified in the browser: 10 patients, chat, citations, mode switch, timeline, loading/empty/error/no-evidence states, no console errors, no `innerHTML`. Not yet committed.

## Open questions / decisions
- Document 4 is a psychosocial-interventions review, not the Cochrane review named in SPEC.md.

## Batch 01 decisions
- All data access is in `frontend/js/api.js`; Batch 03 swaps its bodies for `fetch()`.
- Demo states via `?state=loading|empty|error|no-evidence` and a Demo controls panel.
- Mock document titles are generic ("MOCK Document A"); nothing is attributed to WHO, NIDA or Cochrane.
- Replies depend only on mode; no-evidence replies cite nothing.
- Auto answer mode left out (optional in SPEC).
- Run with `cd frontend && python -m http.server 8000`.

## Known issues
- Only visual check done by DOM inspection; a screenshot could not be captured because the app window was hidden.

## Next step
Batch 02: PostgreSQL data model and seed.
