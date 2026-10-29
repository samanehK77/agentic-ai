# Frontend integration (status after Batch 06)

The UI only talks to `frontend/js/api.js`. Since Batch 03 the **patient list and patient detail come from the API**; chat answers and citation chunks are still mock until Batches 05-07.

New frontend files: `js/config.js` (API base URL, default `http://localhost:8001`) and `js/adapters.js` (reshapes API JSON into the shapes the renderers already use). Layout and renderers are unchanged.

## What is real and what is mock

| `api.js` function | Source now | Endpoint |
|-------------------|------------|----------|
| `listPatients()` | **API** | `GET /api/patients?limit=100` |
| `getPatient(id)` | **API** | `GET /api/patients/{id}` and `GET /api/patients/{id}/history?limit=100` (two calls in parallel) |
| `getChunk(citationId)` | mock | Future: document tables (Batch 05/06) |
| `askQuestion(...)` | mock | Future: RAG + LLM (Batches 06-08) |

Rules:
- **No silent fallback.** If the API is unreachable or answers with an error, `api.js` throws and the existing error state is shown (with "Try again").
- **Mock patients only on request:** open the page with `?source=mock`. A red label "DEMO DATA (mock)" is then shown under the banner.
- The demo states `?state=loading|empty|error|no-evidence` still work and are applied before any request (so `?state=error` shows the error state without calling the API).

## Field mapping (API -> UI shape)

| UI field (`mock-data.js` shape) | API source | Adapter rule |
|---------------------------------|------------|--------------|
| `id` | `patient_id` | as is |
| `age` | `age_at_intake` | as is (age at intake) |
| `sex` | `gender` | `man` -> "Man", `woman` -> "Woman", `non_binary` -> "Non-binary", `other`, `unknown` |
| `category` | `primary_category` + `primary_use_subject` | "Alcohol", "Cannabis", "Opioids", "Stimulants"; `behavioral` -> "Behavioral: Online sports betting" |
| `summary` | `history_summary` | as is |
| `treatment_summary` | `treatment_summary` | as is |
| `background` | `background` | as is |
| `behaviors[]` | `factors` where `kind = observed_behavior` | `description` |
| `history[].period` | history items where `source = history`: `event_date` + `date_precision` | "2012" / "Sep 2012" / "14 Mar 2022" |
| `history[].event` | `summary` of those items | as is |
| `triggers[]` | `factors` where `kind = trigger` | `description` |
| `previous_interventions[].name` | `interventions[].type` + `setting` | "Outpatient counseling (Community clinic)" |
| `previous_interventions[].period` | `start_date`, `end_date` | "14 Mar 2022 to 20 Jun 2022", or "... to ongoing" |
| `previous_interventions[].outcome` | `reported_outcome` | as is |
| `progress.status` | latest `progress` item: `use_status` + `motivation` | "Reduced, motivation: engaged" |
| `progress.note` | latest `progress` item: `note` | as is |

Fields the API already provides but the UI does not show yet: `living_situation`, `employment_status`, `social_context`, `co_occurring_symptoms`, `motivation_at_intake`, `intake_date`, protective factors, the full progress list.

The seed text supersedes the Batch 01 mock text; some names, ages and details differ. The database is the source of truth.

## Not from this database

| Mock item | Where it comes from later |
|-----------|---------------------------|
| `CHUNKS[]` (`citation_id`, `document`, `section`, `page`, `text`, `score`) | Document and chunk tables (Batch 05) and retrieval (Batch 06). Field names already match. |
| `REPLIES`, reply `citations` | LLM answers with citations (Batch 07). |
| `TIMELINE_STEPS`, timeline events | Audit events (Batch 09). |
| `MODES` | Shared configuration. API values are `general_knowledge`, `rag`, `both`; the UI uses `gk`, `rag`, `both` and will map them when chat is connected. |

## Rules to keep
- Patient facts, research evidence and model interpretations stay in separate tables and separate UI blocks.
- Every patient response includes `is_synthetic: true`; the UI keeps its synthetic banner regardless.
- The API needs a Google sign-in session (Batch 04). The frontend sends `credentials: "include"` with every call and the `X-CSRF-Token` header (from `GET /api/auth/me`) with every POST. A 401 shows the signed-out state with the sign-in button; `?source=mock` never calls the API and needs no sign-in.
- Use the host name `localhost` for both the frontend and the API: the login cookie belongs to one host name.
- See `API_ACCESS_POLICY.md` for what is still not protected.

## Sign-in (Batch 04)

| UI part | Behaviour |
|---------|-----------|
| Page load | Calls `GET /api/auth/me`. 200: shows "Signed in as <name>" (textContent) and *Sign out*, then loads the patients. 401: signed-out state, sign-in link, "Sign in to see the patients". Other failures: the normal error state |
| *Sign in with Google* | A plain link to `API_BASE_URL/api/auth/google/login` (top-level navigation, not fetch) |
| `?auth_error=<code>` | Friendly message for `access_denied`, `state_invalid`, `token_invalid`, `email_unverified` (generic text for anything else), then removed from the address bar with `history.replaceState` |
| *Sign out* | `POST /api/auth/logout` with the CSRF header, then the signed-out state |
| Any later 401 (expired session) | Signed-out state |
| Avatars | None: no external images are loaded |

## Retrieval (Batch 06)

| `api.js` function | Source now | Endpoint |
|-------------------|------------|----------|
| `askQuestion(...)` in modes `rag` / `both` (not `?source=mock`) | **API** | `POST /api/retrieval/search` (cookie + `X-CSRF-Token`) |
| `askQuestion(...)` in mode `gk`, or any mode with `?source=mock` | mock (labelled) | none |
| `getChunk(...)` | not used for real chunks (they are already in the evidence list); mock only | none |

- **No fabricated citations.** Answer generation arrives in Batch 07, so in `rag` and `both` the reply is the placeholder "Answer generation arrives in Batch 07. Showing retrieved evidence only." with an empty citation list and a "No answer generated" chip. Only the Evidence Inspector shows chunks, and every chunk shown there was returned by a search (its `citation_id` is the real `chunk_id`).
- **Mapping (`adapters.evidenceChunk`)**: `chunk_id` -> `citation_id`, `title` -> `document`, `section_title` (or "(no section title)") -> `section`, `page_start`-`page_end` -> `page`, `text`, `similarity` -> `score` (shown as "cosine similarity 0.xx"), plus `section_type`, `possible_injection` and `real: true`.
- **Warning badge**: a chunk with `possible_injection` shows "Warning: possible instruction-like text" in the list and in the excerpt. All text is rendered with `textContent`; retrieved text is untrusted data.
- **Timeline**: a real "Chunks retrieved" event with the result count and latency, and "Answer generation: not implemented yet".
- **States**: zero results (or none above the threshold) -> the existing no-evidence state; 401 -> signed-out state; 429 and 503 (`retrieval_unavailable`, `retrieval_not_ready`, `index_incompatible`) -> the existing error state with the API's message; `?state=` demos and `?source=mock` still work; there is no silent fallback to mock data.

