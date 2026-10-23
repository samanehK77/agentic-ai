"""Shared FastAPI dependencies and parameter types."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path, Query, Request
from sqlalchemy.orm import Session

PATIENT_ID_PATTERN = r"^P-\d{3}$"

PatientIdPath = Annotated[
    str,
    Path(pattern=PATIENT_ID_PATTERN, description="Synthetic patient id, P-001 to P-010.", examples=["P-001"]),
]


def get_db(request: Request) -> Iterator[Session]:
    """One database session per request, always closed afterwards."""
    with Session(request.app.state.engine) as session:
        yield session


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1 to 100).")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of items to skip.")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


DbSession = Annotated[Session, Depends(get_db)]
PageParams = Annotated[Pagination, Depends(pagination)]
