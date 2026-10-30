from typing import Annotated

from fastapi import APIRouter, Query

from app import services
from app.deps import Audit, CurrentUser, DbSession, PageParams, PatientIdPath
from app.schemas.common import ERROR_404, ERROR_422, Page
from app.schemas.patients import Category, HistoryItem, PatientProfile, PatientSummary

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get(
    "",
    response_model=Page[PatientSummary],
    summary="List synthetic patients",
    description="Paginated list of the fictional patient cases, ordered by patient id. Optionally filter by category.",
    responses=ERROR_422,
)
def list_patients(
    db: DbSession,
    page: PageParams,
    category: Annotated[Category | None, Query(description="Only patients with this primary category.")] = None,
) -> Page[PatientSummary]:
    items, total = services.list_patients(db, category, page.limit, page.offset)
    return Page[PatientSummary](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/{patient_id}",
    response_model=PatientProfile,
    summary="Get a patient profile",
    description="Full synthetic profile: patient facts, use records, triggers and risk factors, previous interventions "
                "and progress observations. `is_synthetic` is always true.",
    responses={**ERROR_404, **ERROR_422},
)
def get_patient(patient_id: PatientIdPath, db: DbSession, user: CurrentUser, ctx: Audit) -> PatientProfile:
    return PatientProfile(**services.get_patient_profile(db, patient_id, user, ctx))


@router.get(
    "/{patient_id}/history",
    response_model=Page[HistoryItem],
    summary="Get a patient's chronological history",
    description="History events, use periods, interventions and progress observations merged into one timeline, "
                "oldest first. Rows on the same date are ordered history, use, intervention, progress.",
    responses={**ERROR_404, **ERROR_422},
)
def get_patient_history(patient_id: PatientIdPath, db: DbSession, page: PageParams) -> Page[HistoryItem]:
    items, total = services.get_patient_history(db, patient_id, page.limit, page.offset)
    return Page[HistoryItem](items=items, total=total, limit=page.limit, offset=page.offset)
