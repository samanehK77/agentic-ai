import json
import re
from datetime import date

import pytest
from sqlalchemy import text

from db.config import SEED_DIR
from db.models import VOCAB
from db.seed import row_counts, seed

PATIENT_IDS = [f"P-{n:03d}" for n in range(1, 11)]
CHILD_TABLES = [
    "patient_history_events", "substance_or_behavior_use", "triggers_and_risk_factors",
    "previous_interventions", "progress_observations",
]
ALL_TABLES = ["patients", *CHILD_TABLES]

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?(\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
URL = re.compile(r"https?://|www\.", re.I)
# Seed text must stay descriptive: no dosing, preparation, self-harm or treatment-advice wording.
FORBIDDEN = ["dose", "dosage", " mg", "inject", "synthesi", "cook", "recipe", "suicid", "self-harm", "overdose",
             "best treatment", "recommended treatment", "should take", "we recommend", "evidence shows", "studies show"]


def rows(conn, sql, **params):
    return conn.execute(text(sql), params).mappings().all()


def test_exactly_ten_synthetic_patients(conn):
    found = [r["patient_id"] for r in rows(conn, "SELECT patient_id FROM patients ORDER BY patient_id")]
    assert found == PATIENT_IDS
    assert all(r["is_synthetic"] for r in rows(conn, "SELECT is_synthetic FROM patients"))


@pytest.mark.parametrize("table", ALL_TABLES)
def test_every_record_is_marked_synthetic(conn, table):
    assert conn.scalar(text(f"SELECT count(*) FROM {table} WHERE is_synthetic IS NOT TRUE")) == 0


@pytest.mark.parametrize("table", CHILD_TABLES)
def test_no_orphan_rows(conn, table):
    orphans = conn.scalar(text(
        f"SELECT count(*) FROM {table} t LEFT JOIN patients p ON p.patient_id = t.patient_id "
        "WHERE p.patient_id IS NULL"))
    assert orphans == 0


def test_foreign_keys_exist_for_every_child_table(conn):
    count = conn.scalar(text(
        "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND confrelid = 'patients'::regclass "
        "AND conrelid::regclass::text = ANY(:tables)"), {"tables": CHILD_TABLES})
    assert count == len(CHILD_TABLES)


def test_every_category_is_covered(conn):
    found = {r["primary_category"] for r in rows(conn, "SELECT primary_category FROM patients")}
    assert found == set(VOCAB["category"])


def test_same_category_patients_differ_in_trajectory(conn):
    """Each category has two patients whose latest progress status differs or whose treatment path differs."""
    latest = {r["patient_id"]: r["use_status"] for r in rows(conn, """
        SELECT DISTINCT ON (patient_id) patient_id, use_status FROM progress_observations
        ORDER BY patient_id, observed_on DESC""")}
    pairs = rows(conn, "SELECT primary_category, array_agg(patient_id ORDER BY patient_id) AS ids "
                       "FROM patients GROUP BY primary_category")
    for pair in pairs:
        assert len(pair["ids"]) >= 2
    contrasts = sum(1 for pair in pairs if len({latest[i] for i in pair["ids"]}) > 1)
    assert contrasts >= 3, "most categories should contain contrasting trajectories"


def test_each_patient_has_required_records(conn):
    for pid in PATIENT_IDS:
        assert conn.scalar(text("SELECT count(*) FROM patient_history_events WHERE patient_id = :p"), {"p": pid}) >= 4, pid
        assert conn.scalar(text("SELECT count(*) FROM triggers_and_risk_factors "
                                "WHERE patient_id = :p AND kind = 'trigger'"), {"p": pid}) >= 1, pid
        assert conn.scalar(text("SELECT count(*) FROM progress_observations WHERE patient_id = :p"), {"p": pid}) >= 1, pid
        assert conn.scalar(text("SELECT count(*) FROM substance_or_behavior_use WHERE patient_id = :p"), {"p": pid}) >= 1, pid


def test_record_ids_are_sequential_per_patient(conn):
    prefixes = {"patient_history_events": ("event_id", "H"), "substance_or_behavior_use": ("use_id", "U"),
                "triggers_and_risk_factors": ("factor_id", "F"), "previous_interventions": ("intervention_id", "I"),
                "progress_observations": ("observation_id", "O")}
    for table, (column, prefix) in prefixes.items():
        for pid in PATIENT_IDS:
            ids = [r[column] for r in rows(conn, f"SELECT {column} FROM {table} WHERE patient_id = :p ORDER BY {column}", p=pid)]
            assert ids == [f"{pid}-{prefix}{n:02d}" for n in range(1, len(ids) + 1)], (table, pid)


def test_timeline_is_chronological_and_consistent(conn):
    today = date.today()
    for pid in PATIENT_IDS:
        patient = rows(conn, "SELECT * FROM patients WHERE patient_id = :p", p=pid)[0]

        events = rows(conn, "SELECT * FROM patient_history_events WHERE patient_id = :p ORDER BY event_id", p=pid)
        dates = [e["event_date"] for e in events]
        assert dates == sorted(dates), f"{pid}: history events are not in date order"
        assert max(dates) <= today
        assert events[0]["event_type"] == "onset", f"{pid}: the first history event should be the onset"

        progress = rows(conn, "SELECT * FROM progress_observations WHERE patient_id = :p ORDER BY observation_id", p=pid)
        observed = [o["observed_on"] for o in progress]
        assert observed == sorted(observed), f"{pid}: progress observations are not in date order"
        assert observed[0] >= patient["intake_date"], f"{pid}: progress before intake"

        uses = rows(conn, "SELECT * FROM substance_or_behavior_use WHERE patient_id = :p", p=pid)
        for use in uses:
            assert use["start_date"] <= patient["intake_date"], f"{pid}: use starts after intake"
        primary = [u for u in uses if u["category"] == patient["primary_category"]]
        assert primary, f"{pid}: no use record in the primary category"
        assert events[0]["event_date"] == primary[0]["start_date"], f"{pid}: onset event and use start differ"

        interventions = rows(conn, "SELECT * FROM previous_interventions WHERE patient_id = :p", p=pid)
        contact_dates = {e["event_date"] for e in events if e["event_type"] == "treatment_contact" and e["date_precision"] == "day"}
        for item in interventions:
            assert item["start_date"] in contact_dates, f"{pid}: {item['intervention_id']} has no matching treatment_contact event"
            if item["end_date"]:
                assert item["end_date"] >= item["start_date"]


def test_latest_progress_matches_latest_use_status(conn):
    allowed = {"abstinent": {"abstinent"}, "reduced": {"reduced", "supervised"},
               "unchanged": {"active"}, "increased": {"active"}, "relapse": {"active"}, "unknown": {"unknown"}}
    for pid in PATIENT_IDS:
        latest = rows(conn, "SELECT use_status FROM progress_observations WHERE patient_id = :p "
                            "ORDER BY observed_on DESC, observation_id DESC LIMIT 1", p=pid)[0]["use_status"]
        category = rows(conn, "SELECT primary_category FROM patients WHERE patient_id = :p", p=pid)[0]["primary_category"]
        status = rows(conn, "SELECT status FROM substance_or_behavior_use WHERE patient_id = :p AND category = :c "
                            "ORDER BY start_date DESC LIMIT 1", p=pid, c=category)[0]["status"]
        assert status in allowed[latest], f"{pid}: latest progress {latest!r} contradicts use status {status!r}"


def test_seed_is_idempotent_and_does_not_touch_unchanged_rows(engine):
    with engine.connect() as connection:
        before_counts = row_counts(engine)
        before_stamps = connection.execute(text("SELECT patient_id, updated_at FROM patients ORDER BY 1")).all()
    again = seed(engine)
    seed(engine)
    with engine.connect() as connection:
        after_stamps = connection.execute(text("SELECT patient_id, updated_at FROM patients ORDER BY 1")).all()
    assert again == before_counts
    assert row_counts(engine) == before_counts
    assert before_stamps == after_stamps
    assert before_counts["patients"] == 10


def _seed_strings():
    for path in sorted(SEED_DIR.glob("P-*.json")):
        yield from _walk(json.loads(path.read_text(encoding="utf-8")), path.name)
    yield from _walk(json.loads((SEED_DIR / "papers.json").read_text(encoding="utf-8")), "papers.json")


def _walk(node, where, key=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, where, k)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, where, key)
    elif isinstance(node, str) and not key.endswith("date") and key != "observed_on":
        yield where, key, node


def test_seed_files_contain_no_emails_phones_or_urls():
    strings = list(_seed_strings())
    assert strings
    for where, key, value in strings:
        for pattern in (EMAIL, PHONE, URL):
            assert not pattern.search(value), f"{where} [{key}] looks like contact data: {value!r}"


def test_database_text_contains_no_emails_phones_or_urls(conn):
    text_columns = rows(conn, """
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND data_type = 'text' AND table_name <> 'alembic_version'""")
    assert text_columns
    for column in text_columns:
        for row in conn.execute(text(f'SELECT "{column["column_name"]}" FROM {column["table_name"]}')):
            value = row[0] or ""
            for pattern in (EMAIL, PHONE, URL):
                assert not pattern.search(value), (column["table_name"], column["column_name"], value)


def test_seed_text_is_descriptive_not_instructional():
    for where, key, value in _seed_strings():
        lowered = value.lower()
        for word in FORBIDDEN:
            assert word not in lowered, f"{where} [{key}] contains {word!r}: {value!r}"


def test_every_patient_file_matches_its_id():
    files = sorted(p.name for p in SEED_DIR.glob("P-*.json"))
    assert files == [f"{pid}.json" for pid in PATIENT_IDS]
    for path in SEED_DIR.glob("P-*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["patient"]["patient_id"] == path.stem
