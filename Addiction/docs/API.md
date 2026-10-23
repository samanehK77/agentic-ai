# MindEvidence Lab API (Batch 03)

Development-only HTTP API on `http://127.0.0.1:8001`. **No authentication; not secure** (see [API_ACCESS_POLICY.md](API_ACCESS_POLICY.md)).
All patients are fictional. Interactive documentation: <http://127.0.0.1:8001/docs> · machine-readable: <http://127.0.0.1:8001/openapi.json>.

## Start it

From `backend/` with the virtual environment active and the database running (see `backend/README.md`):

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

`.env` must contain `APP_ENV=development`, otherwise the app refuses to start. The frontend uses port 8000, so the API uses 8001.

## Conventions

- **Lists** return `{ "items": [...], "total": N, "limit": L, "offset": O }`. `limit` defaults to 50 (1 to 100, anything else is a 422); `offset` defaults to 0.
- **Errors** always look like this, including validation (422), missing items (404) and unexpected failures (500):

```json
{ "error": { "code": "not_found", "message": "Patient P-999 was not found.", "request_id": "2f461737-23a6-47a9-93e8-486d0f1d23d0" } }
```

  `details` (location, message, type) is added for validation errors. Codes: `validation_error` (422), `not_found` (404), `method_not_allowed` (405), `service_unavailable` (503), `internal_error` (500).
- **Request ids:** every response has an `X-Request-ID` header, also repeated in error bodies. You may send your own `X-Request-ID` (letters, digits, dashes, up to 64 characters); anything else is replaced by a generated UUID.
- **Ids:** patient ids look like `P-001` (`^P-\d{3}$`). A malformed id is 422; a well-formed id that does not exist is 404. Session ids are UUIDs.

## Endpoints

| Method and path | Description |
|-----------------|-------------|
| `GET /api/health` | 200 when the API and database work; 503 otherwise |
| `GET /api/patients?category=&limit=&offset=` | Patients; `category` is one of `alcohol`, `cannabis`, `opioids`, `stimulants`, `behavioral` |
| `GET /api/patients/{patient_id}` | Full profile (always `is_synthetic: true`) |
| `GET /api/patients/{patient_id}/history?limit=&offset=` | Chronological history across all record types |
| `GET /api/papers?limit=&offset=` | Research paper metadata (no text, no file paths) |
| `GET /api/sessions?patient_id=&limit=&offset=` | Chat sessions, newest first |
| `POST /api/sessions` | Create a chat session; 201 with a `Location` header |
| `GET /api/sessions/{session_id}` | One chat session |
| `GET /api/sessions/{session_id}/messages?limit=&offset=` | Messages, oldest first (empty list for a new session) |

Chat messages cannot be created yet; no endpoint writes them until Batches 07 and 08.

## Examples (Windows PowerShell)

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

List patients, and only the alcohol cases:

```powershell
(Invoke-RestMethod "http://127.0.0.1:8001/api/patients").items | Select-Object patient_id, primary_category, age_at_intake
(Invoke-RestMethod "http://127.0.0.1:8001/api/patients?category=alcohol").total
```

Pagination (patients 3 to 5):

```powershell
(Invoke-RestMethod "http://127.0.0.1:8001/api/patients?limit=3&offset=2").items.patient_id
```

One patient, and their first history entries:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/patients/P-001
(Invoke-RestMethod "http://127.0.0.1:8001/api/patients/P-001/history?limit=5").items
```

Papers:

```powershell
(Invoke-RestMethod http://127.0.0.1:8001/api/papers).items | Select-Object paper_id, publisher, publication_year, ingest_status
```

Create a chat session, then read its (empty) messages:

```powershell
$body = '{"patient_id":"P-001","title":"My questions"}'
$response = Invoke-WebRequest -Method Post -Uri http://127.0.0.1:8001/api/sessions -ContentType "application/json" -Body $body
$response.StatusCode
$response.Headers.Location
$session = $response.Content | ConvertFrom-Json
Invoke-RestMethod "http://127.0.0.1:8001/api/sessions/$($session.session_id)/messages"
```

Same thing with `curl.exe` (the `.exe` matters in PowerShell; plain `curl` is an alias for something else). Quoting JSON on a PowerShell command line differs between versions, so pipe the JSON in instead; this works everywhere:

```powershell
curl.exe -i http://127.0.0.1:8001/api/health
'{"patient_id":"P-001","title":"My questions"}' | curl.exe -i -X POST http://127.0.0.1:8001/api/sessions -H "Content-Type: application/json" --data-binary "@-"
```

Seeing an error body (PowerShell throws on 4xx, so read the response text):

```powershell
try { Invoke-RestMethod http://127.0.0.1:8001/api/patients/P-999 } catch { $_.ErrorDetails.Message }
```

Expected: a `not_found` error for `P-999` and a `validation_error` for `ABC`:

```powershell
try { Invoke-RestMethod http://127.0.0.1:8001/api/patients/ABC } catch { $_.ErrorDetails.Message }
```

Send your own request id and see it echoed:

```powershell
(Invoke-WebRequest http://127.0.0.1:8001/api/health -Headers @{ "X-Request-ID" = "my-test-001" }).Headers["X-Request-ID"]
```

## Response shapes

The full schemas are in `/openapi.json`. Main ones:

- `PatientSummary`: `patient_id`, `age_at_intake`, `gender`, `primary_category`, `primary_use_subject`, `intake_date`, `history_summary`, `treatment_summary`, `is_synthetic`.
- `PatientProfile`: everything above plus `living_situation`, `employment_status`, `social_context`, `co_occurring_symptoms`, `motivation_at_intake`, `background`, `use_records`, `factors`, `interventions`, `progress`.
- `HistoryItem`: `event_date`, `date_precision` (history events only), `source` (`history`, `use`, `intervention`, `progress`), `record_id`, `kind`, `summary`.
- `PaperOut`: `paper_id`, `title`, `document_type`, `publisher`, `publication_year`, `source_note`, `ingest_status`, `created_at`. `publisher` and `publication_year` are the text `unknown` when not recorded.
- `SessionOut`: `session_id`, `patient_id`, `title`, `owner_id` (always `null` for now), `created_at`.
- `MessageOut`: `message_id`, `session_id`, `role`, `mode`, `content`, `created_at`.
