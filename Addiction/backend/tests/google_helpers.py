"""Helpers that fake Google in tests: a local RSA key signs real JWTs, so google-auth's own verification runs.

Nothing here talks to Google or the network.
"""
import json
import time
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt, jwt

from app import security
from app.auth_service import OAUTH_COOKIE

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
KID = "test-key-1"


def _make_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return private_pem, cert.public_bytes(serialization.Encoding.PEM).decode()


PRIVATE_PEM, CERT_PEM = _make_key()
OTHER_PRIVATE_PEM, _ = _make_key()  # a key Google "does not publish": tokens signed with it must be rejected


def make_id_token(nonce: str | None, sub: str = "google-sub-1", email: str = "student@example.test", **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": sub, "email": email,
        "email_verified": True, "name": "Test Student", "nonce": nonce, "iat": now, "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {key: value for key, value in claims.items() if value is not None}
    pem = claims.pop("_signing_key", PRIVATE_PEM)
    return jwt.encode(crypt.RSASigner.from_string(pem, KID), claims).decode()


class FakeCertsRequest:
    """Stands in for the HTTP transport that downloads Google's public certificates."""

    class _Response:
        status = 200
        headers: dict = {}

        def __init__(self, data: bytes):
            self.data = data

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        return self._Response(json.dumps({KID: CERT_PEM}).encode())


def oauth_cookie(secret: str, state: str, nonce: str, verifier: str = "v" * 64, lifetime: int = 600) -> str:
    """A login-state cookie value exactly as /api/auth/google/login would have issued it."""
    return security.sign({"s": state, "n": nonce, "v": verifier}, secret, lifetime)


__all__ = ["CLIENT_ID", "OAUTH_COOKIE", "FakeCertsRequest", "make_id_token", "oauth_cookie"]
