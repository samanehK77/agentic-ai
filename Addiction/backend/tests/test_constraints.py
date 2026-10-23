"""Each rule in the schema is checked by trying to break it."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

PATIENT = dict(
    patient_id="P-099", age_at_intake=30, gender="unknown", primary_category="alcohol", intake_date="2025-01-01",
    living_situation="unknown", employment_status="unknown", social_context="unknown",
    co_occurring_symptoms="unknown", motivation_at_intake="unknown", background="b", history_summary="h",
    treatment_summary="t", is_synthetic=True,
)

INSERT_PATIENT = text("""
    INSERT INTO patients (patient_id, age_at_intake, gender, primary_category, intake_date, living_situation,
        employment_status, social_context, co_occurring_symptoms, motivation_at_intake, background,
        history_summary, treatment_summary, is_synthetic)
    VALUES (:patient_id, :age_at_intake, :gender, :primary_category, :intake_date, :living_situation,
        :employment_status, :social_context, :co_occurring_symptoms, :motivation_at_intake, :background,
        :history_summary, :treatment_summary, :is_synthetic)""")


def must_fail(conn, statement, params):
    with pytest.raises(IntegrityError):
        with conn.begin_nested():
            conn.execute(statement, params)


def test_valid_patient_inserts(conn):
    conn.execute(INSERT_PATIENT, PATIENT)


@pytest.mark.parametrize("change", [
    {"is_synthetic": False},
    {"patient_id": "P-1"},
    {"patient_id": "X-001"},
    {"age_at_intake": 17},
    {"gender": "robot"},
    {"primary_category": "chocolate"},
    {"motivation_at_intake": "very"},
    {"intake_date": "2999-01-01"},
    {"living_situation": "   "},
])
def test_patient_rules(conn, change):
    must_fail(conn, INSERT_PATIENT, {**PATIENT, **change})


def test_patient_requires_known_values_not_null(conn):
    must_fail(conn, INSERT_PATIENT, {**PATIENT, "living_situation": None})


def insert_history(conn, **change):
    values = dict(event_id="P-099-H01", patient_id="P-099", event_date="2020-01-01", date_precision="day",
                  event_type="onset", description="x", is_synthetic=True) | change
    return text("""INSERT INTO patient_history_events (event_id, patient_id, event_date, date_precision, event_type,
        description, is_synthetic) VALUES (:event_id, :patient_id, :event_date, :date_precision, :event_type,
        :description, :is_synthetic)"""), values


@pytest.mark.parametrize("change", [
    {"event_date": "2999-01-01"},
    {"event_type": "miracle"},
    {"date_precision": "decade"},
    {"is_synthetic": False},
    {"description": " "},
    {"event_id": "P-098-H01"},       # key does not belong to this patient
    {"patient_id": "P-404"},         # no such patient (foreign key)
])
def test_history_rules(conn, change):
    conn.execute(INSERT_PATIENT, PATIENT)
    statement, values = insert_history(conn, **change)
    must_fail(conn, statement, values)


def insert_use(**change):
    values = dict(use_id="P-099-U01", patient_id="P-099", category="alcohol", substance_or_behavior="x",
                  pattern="daily", start_date="2020-01-01", end_date=None, status="active", is_synthetic=True) | change
    return text("""INSERT INTO substance_or_behavior_use (use_id, patient_id, category, substance_or_behavior, pattern,
        start_date, end_date, status, is_synthetic) VALUES (:use_id, :patient_id, :category, :substance_or_behavior,
        :pattern, :start_date, :end_date, :status, :is_synthetic)"""), values


@pytest.mark.parametrize("change", [
    {"end_date": "2019-01-01", "status": "abstinent"},   # ends before it starts
    {"start_date": "2999-01-01"},
    {"end_date": "2999-01-01", "status": "abstinent"},
    {"end_date": "2021-01-01", "status": "active"},      # ended but still marked active
    {"pattern": "constantly"},
    {"status": "thriving"},
    {"is_synthetic": False},
])
def test_use_rules(conn, change):
    conn.execute(INSERT_PATIENT, PATIENT)
    statement, values = insert_use(**change)
    must_fail(conn, statement, values)


def insert_intervention(**change):
    values = dict(intervention_id="P-099-I01", patient_id="P-099", intervention_type="other", setting="x",
                  start_date="2020-01-01", end_date="2020-02-01", completion_status="completed",
                  reported_outcome="x", is_synthetic=True) | change
    return text("""INSERT INTO previous_interventions (intervention_id, patient_id, intervention_type, setting,
        start_date, end_date, completion_status, reported_outcome, is_synthetic) VALUES (:intervention_id,
        :patient_id, :intervention_type, :setting, :start_date, :end_date, :completion_status, :reported_outcome,
        :is_synthetic)"""), values


@pytest.mark.parametrize("change", [
    {"end_date": "2019-12-01"},
    {"start_date": "2999-01-01", "end_date": None, "completion_status": "ongoing"},
    {"completion_status": "ongoing"},                       # ongoing but has an end date
    {"end_date": None},                                     # completed without an end date
    {"intervention_type": "magic"},
    {"is_synthetic": False},
])
def test_intervention_rules(conn, change):
    conn.execute(INSERT_PATIENT, PATIENT)
    statement, values = insert_intervention(**change)
    must_fail(conn, statement, values)


def test_progress_and_factor_rules(conn):
    conn.execute(INSERT_PATIENT, PATIENT)
    progress = text("""INSERT INTO progress_observations (observation_id, patient_id, observed_on, use_status,
        motivation, note, is_synthetic) VALUES ('P-099-O01', 'P-099', :d, :s, :m, 'x', :syn)""")
    must_fail(conn, progress, {"d": "2999-01-01", "s": "unchanged", "m": "unknown", "syn": True})
    must_fail(conn, progress, {"d": "2020-01-01", "s": "cured", "m": "unknown", "syn": True})
    must_fail(conn, progress, {"d": "2020-01-01", "s": "unchanged", "m": "unknown", "syn": False})
    factor = text("""INSERT INTO triggers_and_risk_factors (factor_id, patient_id, kind, context, description, is_synthetic)
        VALUES ('P-099-F01', 'P-099', :k, :c, 'x', true)""")
    must_fail(conn, factor, {"k": "diagnosis", "c": "unknown"})
    must_fail(conn, factor, {"k": "trigger", "c": "cosmic"})


def test_deleting_a_patient_removes_its_records(conn):
    conn.execute(INSERT_PATIENT, PATIENT)
    statement, values = insert_history(conn)
    conn.execute(statement, values)
    conn.execute(text("DELETE FROM patients WHERE patient_id = 'P-099'"))
    assert conn.scalar(text("SELECT count(*) FROM patient_history_events WHERE patient_id = 'P-099'")) == 0
