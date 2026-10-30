# MindEvidence Lab: frontend

Vanilla HTML, CSS and JavaScript (ES modules). No frameworks, no build step.
Everything shown is **synthetic or MOCK**: patients are fictional and every document excerpt is
invented placeholder text, never attributed to a real source.

**Data sources (since Batch 03):** the patient list and patient detail come from the API
(`http://localhost:8001`, see `docs/API.md`), behind Google sign-in (Batch 04). Chat replies, citations and the activity timeline
are still mock until Batches 05-09 and keep their "(mock)" labels. If the API is not running the
page shows the error state; it never falls back to mock data silently.
Open `http://localhost:8000/?source=mock` to use mock patients on purpose; a "DEMO DATA (mock)" label is then shown.

## Run it

ES modules do not work from `file://`, so serve the folder:

```bash
cd frontend
python -m http.server 8000
```

Then open <http://localhost:8000>.

The patients are loaded from the API, so start the database and the API first (see `backend/README.md`):

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

The API address is set in `js/config.js`. The API allows browser requests (with cookies) only from
`http://localhost:8000`. Use `localhost` for both the page and the API, never `127.0.0.1`: the login cookie belongs to one host name.
Signing in needs the Google variables described in `docs/GOOGLE_AUTH_SETUP.md`; `?source=mock` works without any backend or sign-in.

## Structure

```
frontend/
  index.html
  css/styles.css
  data/mock-data.js     mock patients, chunks, fixed replies (no UI code)
  js/config.js          API base URL (localhost:8001)
  js/adapters.js        reshapes API JSON into the shapes the UI uses (pure functions)
  js/api.js             ALL data access (API for patients; mock for chat and chunks)
  js/state.js           small observable store
  js/main.js            loads data, updates state, re-renders panels
  js/render/*.js        one module per panel (+ dom.js and states.js helpers)
```

### Data access (`js/api.js`)

UI code only calls `js/api.js`:

| Function | Source | Returns |
|----------|--------|---------|
| `listPatients()` | API (`?source=mock` for mock) | `[{ id, age, sex, category, summary, treatment_summary }]` |
| `getPatient(id)` | API (`?source=mock` for mock) | full patient object (profile plus history, via `adapters.js`) |
| `askQuestion({ patientId, mode, text })` | mock | `{ reply: { text, mode, citations }, chunks, events }` |
| `getChunk(citationId)` | mock | `{ citation_id, document, section, page, text, score }` |

The field mapping is in `docs/FRONTEND_INTEGRATION_PLAN.md`.

## Interaction checklist

| Done | Interaction | How to trigger it |
|------|-------------|-------------------|
| [x] | Select a patient, detail updates | Click a card in "Patient explorer", or use Arrow keys / Home / End then Enter |
| [x] | All 10 patients selectable | P-001 to P-010 in the explorer |
| [x] | Ask a question | Type in the chat box and press Send or Enter; your message appears, then a fixed mock reply |
| [x] | Open a citation | Click a `MOCK-Cxx` chip under a reply or a card in the Evidence inspector |
| [x] | Switch source mode | "Answer source mode" radio group: General Knowledge, RAG, Both |
| [x] | Mode changes evidence state | In General Knowledge the inspector says no retrieval happens; RAG and Both show retrieved mock chunks |
| [x] | Activity timeline | Each question adds mock retrieval and generation events |
| [x] | Google sign-in | Signed out: click "Sign in with Google" (needs `docs/GOOGLE_AUTH_SETUP.md`); signed in: your name and "Sign out" appear |
| [x] | Signed-out state | Without a session the patient panel says "Sign in to see the patients" |
| [x] | Sign-in error message | Open `http://localhost:8000/?auth_error=access_denied`: a message appears and the parameter is removed from the address bar |
| [x] | Loading state | Demo controls, or `?state=loading` |
| [x] | Empty state | Demo controls, or `?state=empty` |
| [x] | Error state | Demo controls, or `?state=error` (use "Try again" or Reset) |
| [x] | No-evidence state | Demo controls, or `?state=no-evidence`, then ask a question in RAG or Both mode |
| [x] | Skip link | Press Tab once on page load |
| [x] | Patients from the API | Start the API, open `http://localhost:8000`; 10 patients appear |
| [x] | API error state | Stop the API and reload: "Could not load patients" with "Try again" (no mock fallback) |
| [x] | Mock patients on purpose | `http://localhost:8000/?source=mock` shows the "DEMO DATA (mock)" label |

## Safety and honesty

- The banner "Synthetic data · Educational use only · Not clinical advice" is always visible.
- Mock replies are fixed text chosen only by mode, make no network calls, and give no treatment advice.
- All dynamic text is rendered with `textContent`; the code never uses `innerHTML`.
- Patient facts, research evidence and model interpretations differ by color, icon and text label:
  - Patient fact (synthetic): blue, person icon, solid left border
  - Research evidence (MOCK): green, document icon, dashed border
  - Model interpretation (mock): purple, speech-bubble icon, dotted border

## Retrieval (Batch 06)

In **RAG** and **Both** mode the question is sent to `POST /api/retrieval/search` and the Evidence Inspector shows the real chunks with their "cosine similarity". Answer generation arrives in Batch 07, so the reply is an explicit placeholder with **no citations**; General Knowledge replies stay fixed mock text. A chunk flagged `possible_injection` shows a warning badge. If search is not ready the page shows the API's message (for example "run python -m app.embedding"). `?source=mock` still shows mock evidence. See `docs/FRONTEND_INTEGRATION_PLAN.md` and `docs/RETRIEVAL.md`.

## Answers (Batch 07)

Outside `?source=mock` every question goes to `POST /api/sessions/{id}/messages` (one chat session per patient conversation, a fresh `Idempotency-Key` per submit, "New conversation" button, the newest conversation is resumed when you select a patient). Answers show sections (patient fact, research finding, model interpretation, general knowledge), citation badges that open the chunk and highlight the quote in the Evidence Inspector, unverified citations, unsupported claims, conflicting evidence, retrieved-but-not-cited chunks and the safety notice. `?source=mock` still shows fixed mock replies. See `docs/LLM.md`.

Run the frontend without browser caching: `python serve.py` (instead of `python -m http.server 8000`); with a normal server use Ctrl+Shift+R after updates.

## Workflow timeline (Batch 08)

The Activity timeline renders the answer's `execution_trace` (one item per workflow node, skipped nodes dimmed with the reason; answers stored before Batch 08 fall back to the short trace). While an answer is prepared the page counts the seconds (a local model can take minutes); the browser waits up to 540 s (`ANSWER_TIMEOUT_MS` in `js/config.js`); a busy model or rate limit shows the API's `Retry-After`. All text is set with `textContent`. See `docs/ORCHESTRATION.md` and `docs/FRONTEND_INTEGRATION_PLAN.md`.

## Audit timeline and admin page (Batch 09)

Signed in, the Activity timeline shows the real audit log of the conversation (`GET /api/audit/timeline`): per question the ordered steps with their time, retrieval details, model request, citation badges, the model configuration and, for failed runs, the error code with a plain-language diagnosis. Refresh button; a slow question shows as *running*. A Helpful / Not helpful row sits under each answer (`POST .../feedback`). `admin.html` (admins only) shows the audit summary and event list. `?source=mock` and `?state=` still work. See `docs/OBSERVABILITY.md`.
