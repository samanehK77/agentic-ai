# MindEvidence Lab: frontend (Batch 01, mock data)

Vanilla HTML, CSS and JavaScript (ES modules). No frameworks, no build step, no backend.
Everything shown is **synthetic or MOCK**: patients are fictional and every document excerpt is
invented placeholder text, never attributed to a real source.

## Run it

ES modules do not work from `file://`, so serve the folder:

```bash
cd frontend
python -m http.server 8000
```

Then open <http://localhost:8000>.

## Structure

```
frontend/
  index.html
  css/styles.css
  data/mock-data.js     mock patients, chunks, fixed replies (no UI code)
  js/api.js             ALL data access; async functions returning mock data
  js/state.js           small observable store
  js/main.js            loads data, updates state, re-renders panels
  js/render/*.js        one module per panel (+ dom.js and states.js helpers)
```

### Replacing the mock with a backend (Batch 03)

UI code only calls `js/api.js`. Replace the bodies of these functions with `fetch()` calls that return the same shapes:

| Function | Returns |
|----------|---------|
| `listPatients()` | `[{ id, age, sex, category, summary, treatment_summary }]` |
| `getPatient(id)` | full patient object |
| `askQuestion({ patientId, mode, text })` | `{ reply: { text, mode, citations }, chunks, events }` |
| `getChunk(citationId)` | `{ citation_id, document, section, page, text, score }` |

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
| [x] | Google sign-in (not active) | Hover or focus "Sign in with Google" to see the tooltip |
| [x] | Loading state | Demo controls, or `?state=loading` |
| [x] | Empty state | Demo controls, or `?state=empty` |
| [x] | Error state | Demo controls, or `?state=error` (use "Try again" or Reset) |
| [x] | No-evidence state | Demo controls, or `?state=no-evidence`, then ask a question in RAG or Both mode |
| [x] | Skip link | Press Tab once on page load |

## Safety and honesty

- The banner "Synthetic data · Educational use only · Not clinical advice" is always visible.
- Mock replies are fixed text chosen only by mode, make no network calls, and give no treatment advice.
- All dynamic text is rendered with `textContent`; the code never uses `innerHTML`.
- Patient facts, research evidence and model interpretations differ by color, icon and text label:
  - Patient fact (synthetic): blue, person icon, solid left border
  - Research evidence (MOCK): green, document icon, dashed border
  - Model interpretation (mock): purple, speech-bubble icon, dotted border
