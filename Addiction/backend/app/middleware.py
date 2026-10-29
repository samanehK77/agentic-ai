"""Request-id middleware (prepares the correlation ids used for audit logging in Batch 09)."""
import re
import uuid

from starlette.datastructures import MutableHeaders

REQUEST_ID_HEADER = "X-Request-ID"
# Only letters, digits and dashes, at most 64 characters; anything else is replaced.
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


def safe_request_id(value: str | None) -> str:
    if value and SAFE_REQUEST_ID.fullmatch(value):
        return value
    return str(uuid.uuid4())


class RequestIdMiddleware:
    """Pure ASGI middleware: stores the id on the request and adds it to every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope["headers"]:
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = safe_request_id(incoming)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class NoStoreAuthMiddleware:
    """Adds Cache-Control: no-store to every /api/auth response (redirects and errors included)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/auth"):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_no_store)
