# Google sign-in setup (Batch 04)

How to create the Google OAuth client, which variables go into your `.env`, and how to test the real login by hand.

> **The real Google login cannot be verified automatically.** The automated tests replace Google with a fake (they sign test ID tokens with a local key and run the real verification library on them). Only you can confirm that signing in with your own Google account works. Use the checklist at the end and treat the login as *untested against real Google* until you have done it.

This is a **local development setup over plain HTTP**. Nothing here makes the app ready for production.

## 1. Create the OAuth client in Google Cloud Console

1. Open <https://console.cloud.google.com/> and create (or pick) a project.
2. **APIs & Services → OAuth consent screen**: choose *External*, give the app a name (for example `MindEvidence Lab (local)`), add your email as support and developer contact. No extra scopes are needed: the app asks only for `openid`, `email` and `profile`. It never asks for Gmail access.
3. While the consent screen is in **Testing** mode, only accounts listed under **Test users** can sign in. **Add your own Google account there** (and the second account you will use for the isolation test). Without this, Google shows "access blocked".
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type *Web application*.
5. Enter exactly:
   - **Authorized JavaScript origins:** `http://localhost:8000`
   - **Authorized redirect URIs:** `http://localhost:8001/api/auth/google/callback`
6. Copy the *Client ID* and *Client secret* into your `.env` (next section). The secret is shown in the console only; never paste it into chat, code or git.

Always use the host name `localhost` (never `127.0.0.1`) for the frontend and the API. Login cookies belong to one host name, so mixing the two breaks sign-in.

## 2. Variables for `.env`

Add these to your git-ignored `.env` (the names are also in `.env.example`, without values):

| Name | Meaning |
|------|---------|
| `GOOGLE_CLIENT_ID` | Client ID from step 1 |
| `GOOGLE_CLIENT_SECRET` | Client secret from step 1 |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8001/api/auth/google/callback` (must match Google exactly) |
| `FRONTEND_URL` | `http://localhost:8000` (where the browser returns after sign-in) |
| `SESSION_SECRET` | Random text, **at least 32 characters**; the app refuses to start otherwise |
| `COOKIE_SECURE` | `false` for local HTTP (default). Set `true` only when the site is served over HTTPS |
| `ADMIN_EMAILS` | Optional, comma-separated. A verified Google email in this list gets the `admin` role at login |
| `SESSION_IDLE_MINUTES` | Optional, default `30`: sign-out after this much inactivity |
| `SESSION_MAX_HOURS` | Optional, default `8`: absolute maximum lifetime of a login |
| `CORS_ORIGINS` | Optional, default `http://localhost:8000`. Remove `127.0.0.1` if you set it before |

Generate a `SESSION_SECRET` in PowerShell:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

If the Google variables are missing the app still starts: `GET /api/auth/google/login` answers `503 auth_not_configured`, and every protected route still answers `401`.

## 3. Apply the database changes and start

From `Addiction\backend` (virtual environment active):

```powershell
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Serve the frontend from `Addiction\frontend` with `python -m http.server 8000`, then open <http://localhost:8000>.

## 4. Manual test checklist (you do this)

| Done | Step | Expected |
|------|------|----------|
| [ ] | Open `http://localhost:8000` while signed out | "Sign in to see the patients" and a *Sign in with Google* button |
| [ ] | Click *Sign in with Google* and pick your test account | Google's consent screen, then back on `localhost:8000` |
| [ ] | Look at the header | "Signed in as <your name>" and a *Sign out* button; the 10 patients load |
| [ ] | Reload the page | Still signed in |
| [ ] | Click *Sign out* | Back to the signed-out state; reloading keeps you signed out |
| [ ] | Click sign-in again and press *Cancel* / deny on Google's screen | A friendly "Sign-in was cancelled or not allowed" message, and `?auth_error=...` disappears from the address bar |
| [ ] | Sign in with account A, create a chat session (`POST /api/sessions`, see `docs/API.md`), sign out | The session exists for A |
| [ ] | Sign in with a second account B (also a test user) and list sessions | B sees none of A's sessions; opening A's session id returns 404 |
| [ ] | Wait longer than `SESSION_IDLE_MINUTES` (or set it to 1) and reload | Signed out |

Tell Claude which rows passed or failed; do not claim the login works before you have run them.
