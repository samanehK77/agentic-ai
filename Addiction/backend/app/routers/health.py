from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import services
from app.deps import DbSession
from app.schemas.common import ERROR_503

router = APIRouter(prefix="/api", tags=["health"])


class HealthOut(BaseModel):
    status: str = Field(examples=["ok"])
    database: str = Field(examples=["ok"])


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Health check",
    description="Returns 200 when the API is running and the database answers; 503 otherwise. No internal details are returned.",
    responses=ERROR_503,
)
def health(db: DbSession) -> HealthOut:
    services.check_database(db)
    return HealthOut(status="ok", database="ok")
