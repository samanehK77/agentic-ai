"""One error format for every failure: {"error": {"code", "message", "request_id", "details"?}}.

Responses never contain stack traces, SQL text or the input that failed validation.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.middleware import REQUEST_ID_HEADER

logger = logging.getLogger("mindevidence.api")

HTTP_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """An expected failure with a status code, a stable code and a safe message."""

    def __init__(self, status_code: int, code: str, message: str, details: list[dict] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.headers = headers or {}
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", "Sign in is required.")


def forbidden(message: str = "You do not have permission to do this.") -> ApiError:
    return ApiError(403, "forbidden", message)


def csrf_failed() -> ApiError:
    return ApiError(403, "csrf_failed", "The request could not be verified. Reload the page and try again.")


def service_unavailable(message: str = "The database is not reachable.") -> ApiError:
    return ApiError(503, "service_unavailable", message)


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def error_response(request: Request, status_code: int, code: str, message: str, details: list[dict] | None = None,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id_of(request)}}
    if details:
        body["error"]["details"] = details
    # Set here as well: the outermost server-error layer builds 500 responses outside our middleware.
    return JSONResponse(body, status_code=status_code, headers={**(headers or {}), REQUEST_ID_HEADER: request_id_of(request)})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        details = [{"loc": [str(part) for part in err["loc"]], "msg": err["msg"], "type": err["type"]} for err in exc.errors()]
        return error_response(request, 422, "validation_error", "The request is not valid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        code = HTTP_CODES.get(exc.status_code, "http_error")
        message = {404: "The requested resource was not found.", 405: "This method is not allowed here."}.get(
            exc.status_code, "The request could not be completed.")
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(OperationalError)
    async def handle_database_down(request: Request, exc: OperationalError):
        logger.error("Database unavailable (request %s): %s", request_id_of(request), type(exc.orig).__name__)
        return error_response(request, 503, "service_unavailable", "The database is not reachable.")

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        logger.exception("Unhandled error (request %s)", request_id_of(request))
        return error_response(request, 500, "internal_error", "An unexpected error occurred.")
