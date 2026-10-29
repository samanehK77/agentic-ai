"""Small security helpers: random tokens, hashing, signed values and constant-time comparison."""
import base64
import hashlib
import hmac
import json
import secrets
import time


def new_token() -> str:
    """256 bits of randomness, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Only this is stored in the database, never the raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_challenge(verifier: str) -> str:
    """S256 code challenge for a PKCE verifier."""
    return _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def sign(payload: dict, secret: str, lifetime_seconds: int, now: float | None = None) -> str:
    """A tamper-proof value: base64(json).base64(HMAC-SHA256). The payload is readable but cannot be changed."""
    body = dict(payload, exp=int((now if now is not None else time.time()) + lifetime_seconds))
    encoded = _b64(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def unsign(value: str, secret: str, now: float | None = None) -> dict | None:
    """Returns the payload, or None when the value is malformed, tampered with or expired."""
    try:
        encoded, signature = value.split(".", 1)
        expected = _b64(hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature.encode("ascii"), expected.encode("ascii")):
            return None
        payload = json.loads(_unb64(encoded))
        if not isinstance(payload, dict) or payload.get("exp", 0) < (now if now is not None else time.time()):
            return None
        return payload
    except (ValueError, UnicodeError, TypeError):
        return None
