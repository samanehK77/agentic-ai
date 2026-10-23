"""Deterministic, idempotent seed for the 10 synthetic patients.

Run from backend/ with:   python -m db.seed

Content lives in db/seed_data/P-001.json ... P-010.json (readable, one file per patient).
Record ids are derived from the patient id and the position in each list
(P-001-H01 history, -U use, -F factor, -I intervention, -O observation), so re-running
the seed updates rows in place and never duplicates them.
"""
import json
from datetime import date
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from db.config import SEED_DIR, get_engine
from db.models import (
    Factor, HistoryEvent, Intervention, Patient, ProgressObservation, UseRecord,
)

CHILDREN = [
    # (section in JSON, model, id prefix, id column, field mapping json_key -> column)
    ("history_events", HistoryEvent, "H", "event_id",
     {"date": "event_date", "precision": "date_precision", "type": "event_type", "description": "description"}),
    ("use", UseRecord, "U", "use_id",
     {"category": "category", "subject": "substance_or_behavior", "pattern": "pattern",
      "start_date": "start_date", "end_date": "end_date", "status": "status"}),
    ("factors", Factor, "F", "factor_id",
     {"kind": "kind", "context": "context", "description": "description"}),
    ("interventions", Intervention, "I", "intervention_id",
     {"type": "intervention_type", "setting": "setting", "start_date": "start_date", "end_date": "end_date",
      "completion_status": "completion_status", "reported_outcome": "reported_outcome"}),
    ("progress", ProgressObservation, "O", "observation_id",
     {"observed_on": "observed_on", "use_status": "use_status", "motivation": "motivation", "note": "note"}),
]
DATE_COLUMNS = {"event_date", "start_date", "end_date", "observed_on"}
PATIENT_FIELDS = [
    "age_at_intake", "gender", "primary_category", "intake_date", "living_situation", "employment_status",
    "social_context", "co_occurring_symptoms", "motivation_at_intake", "background", "history_summary",
    "treatment_summary",
]


def load_cases(seed_dir: Path = SEED_DIR) -> list[dict]:
    cases = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(seed_dir.glob("P-*.json"))]
    for case in cases:
        expected = case["patient"]["patient_id"]
        if not expected.startswith("P-"):
            raise ValueError(f"Bad patient id {expected!r}")
    return cases


def _value(column: str, raw):
    if column in DATE_COLUMNS and raw is not None:
        return date.fromisoformat(raw)
    return raw


def seed(engine: Engine, seed_dir: Path = SEED_DIR) -> dict[str, int]:
    """Insert or update every case in one transaction. Returns row counts per table."""
    cases = load_cases(seed_dir)
    with engine.begin() as conn:
        for case in cases:
            pid = case["patient"]["patient_id"]
            row = {"patient_id": pid, "is_synthetic": True}
            row.update({f: _value(f, case["patient"][f]) for f in PATIENT_FIELDS})
            stmt = insert(Patient).values(**row)
            changed = [getattr(Patient, f).is_distinct_from(stmt.excluded[f]) for f in PATIENT_FIELDS]
            update = {f: stmt.excluded[f] for f in PATIENT_FIELDS}
            update["updated_at"] = func.now()
            conn.execute(stmt.on_conflict_do_update(index_elements=["patient_id"], set_=update, where=or_(*changed)))

            for section, model, prefix, id_col, mapping in CHILDREN:
                keys = []
                for position, item in enumerate(case.get(section, []), start=1):
                    key = f"{pid}-{prefix}{position:02d}"
                    keys.append(key)
                    values = {id_col: key, "patient_id": pid, "is_synthetic": True}
                    values.update({col: _value(col, item.get(js)) for js, col in mapping.items()})
                    child = insert(model).values(**values)
                    update_cols = {c: child.excluded[c] for c in values if c not in (id_col, "is_synthetic")}
                    conn.execute(child.on_conflict_do_update(index_elements=[id_col], set_=update_cols))
                # Remove rows that were seeded earlier but are no longer in the file.
                conn.execute(delete(model).where(model.patient_id == pid, getattr(model, id_col).not_in(keys)))
    return row_counts(engine)


def row_counts(engine: Engine) -> dict[str, int]:
    counts = {}
    with engine.connect() as conn:
        for model in (Patient, HistoryEvent, UseRecord, Factor, Intervention, ProgressObservation):
            counts[model.__tablename__] = conn.scalar(select(func.count()).select_from(model))
    return counts


def main() -> None:
    counts = seed(get_engine())
    print("Seed complete. Row counts:")
    for table, count in counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
