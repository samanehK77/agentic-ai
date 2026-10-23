import pytest
from sqlalchemy import text

from db.config import QUERIES_DIR
from tests.test_seed_data import PATIENT_IDS


def run(conn, filename, patient_id):
    sql = (QUERIES_DIR / filename).read_text(encoding="utf-8")
    return conn.execute(text(sql), {"patient_id": patient_id}).mappings().all()


def test_profile_query_returns_the_whole_patient(conn):
    (profile,) = run(conn, "patient_profile.sql", "P-001")
    assert profile["patient_id"] == "P-001"
    assert profile["is_synthetic"] is True
    assert len(profile["interventions"]) == 3
    assert len(profile["progress"]) == 3
    assert {f["kind"] for f in profile["factors"]} >= {"trigger", "protective_factor"}


def test_profile_query_for_unknown_patient_is_empty(conn):
    assert run(conn, "patient_profile.sql", "P-404") == []


@pytest.mark.parametrize("pid", PATIENT_IDS)
def test_history_query_is_chronological_and_complete(conn, pid):
    history = run(conn, "patient_history.sql", pid)
    dates = [row["event_date"] for row in history]
    assert dates == sorted(dates)

    count = lambda sql: conn.scalar(text(sql), {"p": pid})  # noqa: E731
    expected = (
        count("SELECT count(*) FROM patient_history_events WHERE patient_id = :p")
        + count("SELECT count(*) FROM substance_or_behavior_use WHERE patient_id = :p")
        + count("SELECT count(*) FROM substance_or_behavior_use WHERE patient_id = :p AND end_date IS NOT NULL")
        + count("SELECT count(*) FROM previous_interventions WHERE patient_id = :p")
        + count("SELECT count(*) FROM previous_interventions WHERE patient_id = :p AND end_date IS NOT NULL")
        + count("SELECT count(*) FROM progress_observations WHERE patient_id = :p")
    )
    assert len(history) == expected


def test_history_starts_with_the_onset(conn):
    first = run(conn, "patient_history.sql", "P-001")[0]
    assert (first["source"], first["kind"]) == ("history", "onset")
    assert str(first["event_date"]) == "2012-09-01"
