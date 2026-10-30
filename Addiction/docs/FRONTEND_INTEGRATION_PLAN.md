# Frontend integration (status after Batch 07)

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

## Answers (Batch 07)

The Batch 06 placeholder reply is gone. Outside `?source=mock`, all three modes call the real answer endpoint.

| UI action | Call |
|-----------|------|
| Select a patient | after the patient loads, `GET /api/sessions?patient_id=&limit=1` and, if one exists, `GET /api/sessions/{id}/messages` to **resume** the newest conversation (best effort) |
| First question for a patient (or after "New conversation") | `POST /api/sessions` (a new chat session) |
| Every question | `POST /api/sessions/{id}/messages` with credentials, `X-CSRF-Token` and a **fresh `Idempotency-Key`** (`crypto.randomUUID()`); the send button is disabled while the request is pending |
| "New conversation" | clears the patient's messages, evidence and timeline; the next question creates a new session |

- **Rendering (`render/answer.js`, `textContent` only):** sections keep the three-way separation (patient fact: blue, research finding: green dashed, model interpretation: purple dotted) plus a distinct grey style for **general knowledge (not from the documents)** and a red style for withheld sections. Citation badges are buttons labelled `S1`, `S2 · unverified`...; activating one (click, Enter or Space) shows that answer's evidence in the Evidence Inspector, highlights the chunk and the cited quote and moves focus to the excerpt. Unsupported claims, conflicting evidence, limitations, validation notes and a generation line (model, prompt version, tokens, latency) are shown. The escalation notice is a prominent `role="alert"` box.
- **Evidence Inspector:** the chunks shown to the model, grouped as "Cited in the answer", "Retrieved but not cited" and "Kept out of the model's prompt" (possible instruction-like text or context budget), each with `S`-alias, similarity, `stale` marker and injection warning. The evidence of an earlier answer stays visible after switching mode; a General Knowledge answer clears it.
- **Timeline:** built from the answer's `trace` (retrieval, generation, validation, safety).
- **Errors:** 401 -> signed-out state; 429, 502, 503 (`llm_not_configured`, `llm_unavailable`, retrieval errors) and 504 -> clear messages in the chat (and the evidence panel); `?state=` demos and `?source=mock` (fixed mock replies, MOCK labels, no network) still work; there is no silent fallback to mock.
- The same question can be asked in `general_knowledge` and `rag` mode to compare: no evidence and no citations versus real chunks and citations.
- `frontend/serve.py` serves the folder with `Cache-Control: no-store`, so a reload shows the newest files (plain `python -m http.server` may leave stale scripts in the browser cache).

## Workflow timeline (Batch 08)

The Activity timeline now shows the answer workflow: a summary line (classification, whether documents were searched), then one item per node with its duration, a short detail (chunks found, evidence level, quotes verified, tokens) and its status. Nodes that did not run are dimmed and marked **skipped** with the reason (for example "history question: documents not searched"); an unsupported request shows **ended** at "Classify question". Everything comes from the statistics-only `execution_trace` of the answer and is rendered with `textContent`; answers stored before Batch 08 fall back to the short Batch 07 trace list. While an answer is being prepared the page shows an elapsed-seconds counter and "a local model can take a few minutes"; the browser waits up to 540 s (`ANSWER_TIMEOUT_MS` in `js/config.js`, above the server's 480 s workflow limit), the send button stays disabled, and a 503 "busy" or 429 shows the API's `Retry-After` as "Try again in about N seconds". `?source=mock` and `?state=` demos are unchanged.

## Activity timeline from the audit log (Batch 09)

Signed in, the Activity timeline no longer comes from the answer's own trace but from `GET /api/audit/timeline?session_id=` (the conversation in use). It shows, per question (newest first, the newest expanded): an outcome badge (answered, no evidence, not supported, safety notice, replayed, failed, running, interrupted), the total answer time, the correlation id (first 8 characters), the ordered events with their own time, the retrieval details (`top_k`, threshold, chunk count, chunk ids), the model request (model, tokens, retries), a citation badge ("3 of 5 quotes verified"), and for a failed run the error code with a plain-language diagnosis. A **Model configuration** box (model, prompt version, retrieval settings, embedding and chunking fingerprints, configuration fingerprint) comes from the latest `question_submitted`. A Refresh button reloads it; while a slow answer is prepared the list is refreshed every 5 seconds, so the question shows as *running* (the node steps are written when the run ends). 401 shows the signed-out state; 404, 429 and 503 have their own messages. `?source=mock` and `?state=` keep the earlier mock timeline and demo states. Under each real answer two buttons (Helpful / Not helpful) and a fixed reason list post feedback. `admin.html` (link shown only to admins) shows the summary and the filterable event list; students get a plain "administrators only" message and the API refuses them anyway. All text is set with `textContent`.
