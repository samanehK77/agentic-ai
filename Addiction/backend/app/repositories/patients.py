"""All patient database access. The profile and history queries are the reviewed SQL files in db/queries."""
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from db.config import QUERIES_DIR
from db.models import Patient, UseRecord

PROFILE_SQL = (QUERIES_DIR / "patient_profile.sql").read_text(encoding="utf-8")
# The history query ends with ORDER BY; LIMIT/OFFSET are appended so paging keeps that exact order.
HISTORY_SQL = (QUERIES_DIR / "patient_history.sql").read_text(encoding="utf-8").strip().rstrip(";")

_primary_use_subject = (
    select(UseRecord.substance_or_behavior)
    .where(UseRecord.patient_id == Patient.patient_id, UseRecord.category == Patient.primary_category)
    .order_by(UseRecord.start_date, UseRecord.use_id)
    .limit(1)
    .scalar_subquery()
)


def list_patients(db: Session, category: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    base = select(Patient)
    if category:
        base = base.where(Patient.primary_category == category)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    query = (
        select(
            Patient.patient_id, Patient.age_at_intake, Patient.gender, Patient.primary_category,
            _primary_use_subject.label("primary_use_subject"), Patient.intake_date,
            Patient.history_summary, Patient.treatment_summary, Patient.is_synthetic,
        )
        .order_by(Patient.patient_id)
        .limit(limit)
        .offset(offset)
    )
    if category:
        query = query.where(Patient.primary_category == category)
    return [dict(row) for row in db.execute(query).mappings()], total


def patient_exists(db: Session, patient_id: str) -> bool:
    return db.scalar(select(func.count()).select_from(Patient).where(Patient.patient_id == patient_id)) == 1


def get_profile(db: Session, patient_id: str) -> dict | None:
    row = db.execute(text(PROFILE_SQL), {"patient_id": patient_id}).mappings().first()
    if row is None:
        return None
    profile = dict(row)
    profile["primary_use_subject"] = next(
        (u["subject"] for u in profile["use_records"] if u["category"] == profile["primary_category"]), None)
    return profile


def get_history(db: Session, patient_id: str, limit: int, offset: int) -> tuple[list[dict], int]:
    total = db.scalar(text(f"SELECT count(*) FROM ({HISTORY_SQL}) AS counted"), {"patient_id": patient_id})
    rows = db.execute(
        text(f"{HISTORY_SQL} LIMIT :limit OFFSET :offset"),
        {"patient_id": patient_id, "limit": limit, "offset": offset},
    ).mappings()
    return [dict(row) for row in rows], total
