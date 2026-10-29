# API access policy (Batch 06)

## Status: authenticated, but development only

Since Batch 04 the API requires a Google sign-in session. It is still a **local development setup over plain HTTP** and is not described as production-ready. The app refuses to start unless `APP_ENV=development`, and the documented run command binds to `127.0.0.1`.

## What is protected now

| Area | Today |
|------|-------|
| Who can call the API | Only signed-in users (cookie `me_session`) for every `/api/*` route except `/api/health` and `/api/auth/*`; others get `401 unauthorized` |
| Login | Google OAuth 2.0 Authorization Code flow with PKCE (S256), `state` and `nonce`; the ID token is verified with the `google-auth` library (signature, issuer, audience, expiry, nonce) and the email must be verified. Scopes: `openid email profile` only |
| Identity | Users are keyed by Google's stable `sub`, never by email. Google's tokens are discarded after verification and never stored |
| Session | Random 256-bit token in an HttpOnly, SameSite=Lax, host-only cookie (`Secure` when `COOKIE_SECURE=true`); only its SHA-256 hash is stored; a new token at every login; idle and absolute timeouts enforced on the server; logout revokes it |
| CSRF | State-changing requests need the `X-CSRF-Token` header (constant-time comparison) and an allowed `Origin` if one is sent |
| CORS | Explicit origins (`CORS_ORIGINS`, default `http://localhost:8000`), credentials allowed, methods `GET`/`POST`/`OPTIONS`, no wildcard |
| Chat sessions | Owned by the creating user. Other users get `404 not_found` (we do not reveal that the session exists). Sessions from before Batch 04 have no owner and are visible to nobody |
| Roles | `student` / `admin` (admin only for verified emails in `ADMIN_EMAILS`, recomputed at each login). `require_role("admin")` protects the `/api/admin/*` routes (401 signed out, 403 for students) |
| Ingestion results | `/api/admin/papers*` and `/api/admin/chunks/*` are read-only and admin-only. They return the **full chunk text** (copyrighted source material), so only administrators can see it. Students see paper metadata only (`GET /api/papers`) and get no chunk endpoint until Batch 07 defines citation rules |
| Search results | `POST /api/retrieval/search` is open to every signed-in user (and needs the CSRF header). **Decision (Batch 06):** a student receives the text of the chunks a search returns (each at most 250 tokens, at most 20 per request, rate limited to 30 searches per minute by default), because the Evidence Inspector needs it. This supersedes the Batch 05 rule "full chunk text only to admins" for this endpoint only. The admin routes are unchanged, and students still cannot list or page through chunks. Chunk text is untrusted data: it never acts as instructions. |
| Logs | Auth events log the event, a reason code, the request id and the user id; never tokens, codes, secrets or email addresses |

## Why ingestion is not an HTTP endpoint

Ingestion is a command-line job (`python -m app.ingestion`, see `docs/INGESTION.md`) and no HTTP route starts, uploads or re-runs it. This keeps the attack surface small: no file upload, no file names or paths taken from a request, no long-running work inside a request handler, and no way for a compromised admin session to point the server at other files. Only PDFs registered in `papers.json`, as plain files directly inside `data/papers/`, can be read. The admin endpoints never return file names, paths or file hashes.

## Why students may receive chunk text (Batch 06)

The Evidence Inspector (SPEC) has to show the passages behind an answer, so a search must return the text. The exposure is bounded: only chunks that match a question are returned, at most 20 of at most 250 tokens each per request, under a per-user rate limit, never file names, paths or hashes, and no endpoint lets a student enumerate chunks. The documents are copyrighted; this is a development and teaching setup and the limits above reduce, but do not remove, the risk of someone collecting the corpus by repeated searches. The query text is never logged.

## What is still not protected

| Area | Today |
|------|-------|
| Transport | Plain HTTP, no TLS. Cookies are sent unencrypted on the local machine; `COOKIE_SECURE=true` must only be used behind HTTPS |
| Rate limiting | Only on semantic search (per user, in-process, default 30 per minute); none on login attempts or other API calls |
| Interactive docs (`/docs`, `/openapi.json`) | Open without sign-in, because the app only runs in development |
| OAuth `state` memory | Used login states are remembered in the process, so restarting the API forgets them (a signed state cookie still expires after 10 minutes) |
| Patient and paper data | Any signed-in user can read all synthetic patients and paper metadata (there is no per-patient permission) |
| Multiple servers | One process only; nothing is shared between processes |

Nothing in this repository should be described as production-ready or clinically validated.
