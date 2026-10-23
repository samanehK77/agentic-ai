# API access policy (Batch 03)

## Status: development only, NOT secure

The MindEvidence Lab API has **no authentication and no authorization**. Anyone who can reach the server can call every endpoint, including creating chat sessions and reading every session. It must be treated as an open local tool, not as a protected service.

Do not deploy it, expose it to a network, or put real data behind it. The data is fictional, but the access model is still unsafe for anything beyond a single developer's machine.

## What the code does to limit the risk

These are guard rails for a local setup. **They are not security controls.**

- The app refuses to start unless `APP_ENV=development`.
- The documented run command binds to `127.0.0.1` only, so other machines cannot connect.
- CORS allows only the origins in `CORS_ORIGINS` (default `http://127.0.0.1:8000` and `http://localhost:8000`), only `GET`, `POST` and `OPTIONS`, no credentials and no wildcard. CORS only controls which web pages a browser lets read responses; it does not stop other programs from calling the API.
- Errors never include stack traces or SQL, and request ids are validated.
- The API serves metadata about papers but no document text and no server file paths.

## What is not protected

| Area | Today |
|------|-------|
| Who can call the API | Anyone who can reach `127.0.0.1:8001` on this machine |
| Chat sessions | `owner_id` is always `null`. Every caller sees and can open every session |
| Rate limiting | None |
| Transport | Plain HTTP, no TLS |
| Interactive docs (`/docs`) | Open, because the app only runs in development |

## What changes with Batch 04 (Google sign-in)

- Requests without a valid sign-in session receive `401` (not signed in).
- A signed-in user who requests another user's chat session receives `403`, or `404` if we decide not to reveal that it exists.
- `chat_sessions.owner_id` will be filled from the signed-in user and checked on every session and message endpoint. The column already exists (nullable, no foreign key yet).
- Patient and paper endpoints will require sign-in, and administrator-only actions will get their own role check.
- The `APP_ENV` guard stays until those controls exist and have been tested.

Nothing in this repository should be described as secure until those changes are made and tested.
