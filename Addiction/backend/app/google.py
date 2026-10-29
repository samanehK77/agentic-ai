"""The only module that talks to Google (token exchange and ID-token verification).

Tests replace `exchange_code` and `_certs_request`; they never call Google. TLS verification is always on.
"""
from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"  # no Gmail or other scopes


class GoogleError(Exception):
    """The code exchange or the ID token was not accepted. Never carries Google's raw response."""


def authorization_url(settings: Settings, state: str, nonce: str, code_challenge: str) -> str:
    query = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{AUTH_URL}?{query}"


def exchange_code(settings: Settings, code: str, code_verifier: str) -> str:
    """Trades the one-time code (plus the PKCE verifier) for an ID token. Other tokens are discarded."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        token = response.json().get("id_token")
    except (httpx.HTTPError, ValueError):
        raise GoogleError("token exchange failed") from None
    if not isinstance(token, str) or not token:
        raise GoogleError("no id_token in the response")
    return token


def _certs_request():
    return google_requests.Request()


def verify_id_token(settings: Settings, token: str) -> dict:
    """Checks signature, issuer, audience (= our client id) and expiry with Google's library."""
    try:
        return id_token.verify_oauth2_token(token, _certs_request(), settings.google_client_id)
    except Exception:  # library raises ValueError/GoogleAuthError subclasses; transport errors too
        raise GoogleError("id token rejected") from None
