"""Shared response shapes: the list envelope and the standard error body."""
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Every list endpoint returns this envelope."""

    items: list[T]
    total: int = Field(description="Number of items matching the request, before pagination.")
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Patient P-999 was not found."])
    request_id: str = Field(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
    details: list[dict] | None = Field(default=None, description="Validation problems (location, message, type).")


class ErrorResponse(BaseModel):
    error: ErrorBody


ERROR_401 = {401: {"model": ErrorResponse, "description": "Not signed in (code `unauthorized`)."}}
ERROR_403 = {403: {"model": ErrorResponse, "description": "Missing or wrong CSRF token (`csrf_failed`) or wrong role (`forbidden`)."}}
ERROR_422 ={422: {"model": ErrorResponse, "description": "The request is not valid."}}
ERROR_404 = {404: {"model": ErrorResponse, "description": "The requested item does not exist."}}
ERROR_503 = {503: {"model": ErrorResponse, "description": "The database is not reachable."}}
