# MindEvidence Lab API (Batch 04)

Development-only HTTP API on `http://localhost:8001`. Since Batch 04 it needs a Google sign-in session; it is still plain HTTP and not production-ready (see [API_ACCESS_POLICY.md](API_ACCESS_POLICY.md)).
All patients are fictional. Interactive documentation: <http://localhost:8001/docs> · machine-readable: <http://localhost:8001/openapi.json>.

## Start it

From `backend/` with the virtual environment active and the database running (see `backend/README.md`):

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

`.env` must contain `APP_ENV=development` and a `SESSION_SECRET` of at least 32 characters, otherwise the app refuses to start. Google sign-in variables are described in [GOOGLE_AUTH_SETUP.md](GOOGLE_AUTH_SETUP.md); without them the login endpoint answers 503. The frontend uses port 8000, so the API uses 8001. Use the host name `localhost` everywhere (cookies are host-scoped).

## Conventions

- **Lists** return `{ "items": [...], "total": N, "limit": L, "offset": O }`. `limit` defaults to 50 (1 to 100, anything else is a 422); `offset` defaults to 0.
- **Errors** always look like this, including validation (422), missing items (404) and unexpected failures (500):

```json
{ "error": { "code": "not_found", "message": "Patient P-999 was not found.", "request_id": "2f461737-23a6-47a9-93e8-486d0f1d23d0" } }
```

  `details` (location, message, type) is added for validation errors. Codes: `validation_error` (422), `unauthorized` (401), `csrf_failed` and `forbidden` (403), `not_found` (404), `method_not_allowed` (405), `service_unavailable` and `auth_not_configured` (503), `internal_error` (500).
- **Request ids:** every response has an `X-Request-ID` header, also repeated in error bodies. You may send your own `X-Request-ID` (letters, digits, dashes, up to 64 characters); anything else is replaced by a generated UUID.
- **Ids:** patient ids look like `P-001` (`^P-\d{3}$`). A malformed id is 422; a well-formed id that does not exist is 404. Session ids are UUIDs.

## Authentication, CSRF and ownership (Batch 04)

- **Session cookie.** Signing in with Google sets the HttpOnly cookie `me_session` (SameSite=Lax, host-only, `Secure` only if `COOKIE_SECURE=true`). Every `/api/*` route needs it except `/api/health` and `/api/auth/*`. Without a valid cookie the answer is `401` with code `unauthorized`. A login ends after `SESSION_IDLE_MINUTES` without use (default 30) or `SESSION_MAX_HOURS` in total (default 8), or when you sign out.
- **CSRF.** `POST`, `PUT`, `PATCH` and `DELETE` must send the header `X-CSRF-Token` with the value from `GET /api/auth/me`; a missing or wrong value is `403` `csrf_failed`. A request whose `Origin` header is present and not in `CORS_ORIGINS` is also `403` `csrf_failed`.
- **Ownership.** Chat sessions belong to the user who created them. You can list, read and see messages of your own sessions only. Another user's session returns `404 not_found`, the same answer as a session that does not exist, so its existence is not revealed (decision for Batch 04). Sessions created before Batch 04 have no owner and are invisible to everyone.
- **Roles.** `student` (default) and `admin` (verified email listed in `ADMIN_EMAILS`). A reusable `require_role` dependency returns `403 forbidden` for the wrong role; no admin-only route exists yet.
- All `/api/auth/*` responses carry `Cache-Control: no-store`.

## Endpoints

| Method and path | Description |
|-----------------|-------------|
| `GET /api/health` | **Public.** 200 when the API and database work; 503 otherwise |
| `GET /api/auth/google/login` | **Public.** Redirects the browser to Google (open it as a page, not with fetch). 503 `auth_not_configured` without Google settings |
| `GET /api/auth/google/callback` | **Public.** Google returns here; sets the session cookie and redirects to `FRONTEND_URL`, or to `FRONTEND_URL/?auth_error=access_denied\|state_invalid\|token_invalid\|email_unverified` |
| `GET /api/auth/me` | The signed-in user: `id`, `email`, `display_name`, `role`, `csrf_token` (never the Google id). 401 if signed out |
| `POST /api/auth/logout` | Revokes the session on the server and clears the cookie. 204; needs `X-CSRF-Token` |
| `GET /api/patients?category=&limit=&offset=` | Patients; `category` is one of `alcohol`, `cannabis`, `opioids`, `stimulants`, `behavioral` |
| `GET /api/patients/{patient_id}` | Full profile (always `is_synthetic: true`) |
| `GET /api/patients/{patient_id}/history?limit=&offset=` | Chronological history across all record types |
| `GET /api/papers?limit=&offset=` | Research paper metadata (no text, no file paths) |
| `GET /api/sessions?patient_id=&limit=&offset=` | Your chat sessions, newest first |
| `POST /api/sessions` | Create a chat session owned by you; 201 with a `Location` header; needs `X-CSRF-Token` |
| `GET /api/sessions/{session_id}` | One of your chat sessions (404 for anyone else's) |
| `GET /api/sessions/{session_id}/messages?limit=&offset=` | Messages of your session, oldest first (empty list for a new session; 404 for anyone else's) |

Chat messages cannot be created yet; no endpoint writes them until Batches 07 and 08.

## Examples (Windows PowerShell)

The API needs the session cookie, which only the browser receives (it is HttpOnly). Easiest: sign in at <http://localhost:8000>, then in the browser's developer tools (Application → Cookies → `localhost`) copy the value of `me_session`. Put it in a variable (do not paste it into chats or commit it):

```powershell
$cookie = "me_session=<value copied from the browser>"
$me = Invoke-RestMethod http://localhost:8001/api/auth/me -Headers @{ Cookie = $cookie }
$me.email, $me.role
```

Without the cookie you get 401, and a POST without the CSRF header gets 403:

```powershell
try { Invoke-RestMethod http://localhost:8001/api/patients } catch { $_.ErrorDetails.Message }
try { Invoke-RestMethod -Method Post http://localhost:8001/api/sessions -Headers @{ Cookie = $cookie } -ContentType "application/json" -Body '{"patient_id":"P-001"}' } catch { $_.ErrorDetails.Message }
```

For the read examples below add `-Headers @{ Cookie = $cookie }`; for POST requests also add `"X-CSRF-Token" = $me.csrf_token` to the headers.

Health check:

```powershell
Invoke-RestMethod http://localhost:8001/api/health
```

List patients, and only the alcohol cases:

```powershell
(Invoke-RestMethod "http://localhost:8001/api/patients").items | Select-Object patient_id, primary_category, age_at_intake
(Invoke-RestMethod "http://localhost:8001/api/patients?category=alcohol").total
```

Pagination (patients 3 to 5):

```powershell
(Invoke-RestMethod "http://localhost:8001/api/patients?limit=3&offset=2").items.patient_id
```

One patient, and their first history entries:

```powershell
Invoke-RestMethod http://localhost:8001/api/patients/P-001
(Invoke-RestMethod "http://localhost:8001/api/patients/P-001/history?limit=5").items
```

Papers:

```powershell
(Invoke-RestMethod http://localhost:8001/api/papers).items | Select-Object paper_id, publisher, publication_year, ingest_status
```

Create a chat session, then read its (empty) messages:

```powershell
$headers = @{ Cookie = $cookie; "X-CSRF-Token" = $me.csrf_token }
$body = '{"patient_id":"P-001","title":"My questions"}'
$response = Invoke-WebRequest -Method Post -Uri http://localhost:8001/api/sessions -Headers $headers -ContentType "application/json" -Body $body
$response.StatusCode
$response.Headers.Location
$session = $response.Content | ConvertFrom-Json
Invoke-RestMethod "http://localhost:8001/api/sessions/$($session.session_id)/messages" -Headers @{ Cookie = $cookie }
```

Same thing with `curl.exe` (the `.exe` matters in PowerShell; plain `curl` is an alias for something else). Quoting JSON on a PowerShell command line differs between versions, so pipe the JSON in instead; this works everywhere:

```powershell
curl.exe -i http://localhost:8001/api/health
'{"patient_id":"P-001","title":"My questions"}' | curl.exe -i -X POST http://localhost:8001/api/sessions -H "Content-Type: application/json" -H "Cookie: $cookie" -H "X-CSRF-Token: $($me.csrf_token)" --data-binary "@-"
```

Seeing an error body (PowerShell throws on 4xx, so read the response text):

```powershell
try { Invoke-RestMethod http://localhost:8001/api/patients/P-999 } catch { $_.ErrorDetails.Message }
```

Expected: a `not_found` error for `P-999` and a `validation_error` for `ABC`:

```powershell
try { Invoke-RestMethod http://localhost:8001/api/patients/ABC } catch { $_.ErrorDetails.Message }
```

Send your own request id and see it echoed:

```powershell
(Invoke-WebRequest http://localhost:8001/api/health -Headers @{ "X-Request-ID" = "my-test-001" }).Headers["X-Request-ID"]
```

## Response shapes

The full schemas are in `/openapi.json`. Main ones:

- `PatientSummary`: `patient_id`, `age_at_intake`, `gender`, `primary_category`, `primary_use_subject`, `intake_date`, `history_summary`, `treatment_summary`, `is_synthetic`.
- `PatientProfile`: everything above plus `living_situation`, `employment_status`, `social_context`, `co_occurring_symptoms`, `motivation_at_intake`, `background`, `use_records`, `factors`, `interventions`, `progress`.
- `HistoryItem`: `event_date`, `date_precision` (history events only), `source` (`history`, `use`, `intervention`, `progress`), `record_id`, `kind`, `summary`.
- `PaperOut`: `paper_id`, `title`, `document_type`, `publisher`, `publication_year`, `source_note`, `ingest_status`, `created_at`. `publisher` and `publication_year` are the text `unknown` when not recorded.
- `SessionOut`: `session_id`, `patient_id`, `title`, `owner_id` (the signed-in user's id), `created_at`.
- `MessageOut`: `message_id`, `session_id`, `role`, `mode`, `content`, `created_at`.
- `MeOut`: `id`, `email`, `display_name`, `role` (`student` or `admin`), `csrf_token`. The Google subject id and Google tokens are never returned or stored.

The OpenAPI document declares the `me_session` cookie as the security scheme of every protected route and lists the `X-CSRF-Token` header parameter.
