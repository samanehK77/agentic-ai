"""Patient schema: six normalized tables of synthetic patient facts.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    "progress_observations",
    "previous_interventions",
    "triggers_and_risk_factors",
    "substance_or_behavior_use",
    "patient_history_events",
    "patients",
]

GENDER = "'woman', 'man', 'non_binary', 'other', 'unknown'"
CATEGORY = "'alcohol', 'cannabis', 'opioids', 'stimulants', 'behavioral'"
MOTIVATION = "'none_expressed', 'ambivalent', 'contemplating', 'preparing', 'engaged', 'unknown'"

COMMON = """
    is_synthetic boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
"""


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE patients (
        patient_id text NOT NULL,
        age_at_intake smallint NOT NULL,
        gender text NOT NULL,
        primary_category text NOT NULL,
        intake_date date NOT NULL,
        living_situation text NOT NULL,
        employment_status text NOT NULL,
        social_context text NOT NULL,
        co_occurring_symptoms text NOT NULL,
        motivation_at_intake text NOT NULL,
        background text NOT NULL,
        history_summary text NOT NULL,
        treatment_summary text NOT NULL,
        is_synthetic boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_patients PRIMARY KEY (patient_id),
        CONSTRAINT ck_patients_id_format CHECK (patient_id ~ '^P-[0-9]{{3}}$'),
        CONSTRAINT ck_patients_adult_age CHECK (age_at_intake BETWEEN 18 AND 110),
        CONSTRAINT ck_patients_gender_values CHECK (gender IN ({GENDER})),
        CONSTRAINT ck_patients_category_values CHECK (primary_category IN ({CATEGORY})),
        CONSTRAINT ck_patients_motivation_values CHECK (motivation_at_intake IN ({MOTIVATION})),
        CONSTRAINT ck_patients_intake_not_future CHECK (intake_date <= CURRENT_DATE),
        CONSTRAINT ck_patients_text_not_blank CHECK (
            length(trim(living_situation)) > 0 AND length(trim(employment_status)) > 0
            AND length(trim(social_context)) > 0 AND length(trim(co_occurring_symptoms)) > 0
            AND length(trim(background)) > 0 AND length(trim(history_summary)) > 0
            AND length(trim(treatment_summary)) > 0),
        CONSTRAINT ck_patients_is_synthetic_true CHECK (is_synthetic)
    )""")

    op.execute(f"""
    CREATE TABLE patient_history_events (
        event_id text NOT NULL,
        patient_id text NOT NULL,
        event_date date NOT NULL,
        date_precision text NOT NULL,
        event_type text NOT NULL,
        description text NOT NULL,
        {COMMON},
        CONSTRAINT pk_patient_history_events PRIMARY KEY (event_id),
        CONSTRAINT fk_patient_history_events_patient_id_patients
            FOREIGN KEY (patient_id) REFERENCES patients (patient_id) ON DELETE CASCADE,
        CONSTRAINT ck_patient_history_events_key_matches_patient CHECK (event_id LIKE patient_id || '-H%'),
        CONSTRAINT ck_patient_history_events_precision_values CHECK (date_precision IN ('year', 'month', 'day')),
        CONSTRAINT ck_patient_history_events_type_values CHECK (event_type IN (
            'onset', 'escalation', 'life_event', 'health_event', 'legal_or_work_event', 'help_seeking',
            'treatment_contact', 'reduction_attempt', 'relapse', 'recovery_milestone', 'other')),
        CONSTRAINT ck_patient_history_events_date_not_future CHECK (event_date <= CURRENT_DATE),
        CONSTRAINT ck_patient_history_events_description_not_blank CHECK (length(trim(description)) > 0),
        CONSTRAINT ck_patient_history_events_is_synthetic_true CHECK (is_synthetic)
    )""")
    op.execute("CREATE INDEX ix_patient_history_events_patient_date ON patient_history_events (patient_id, event_date)")

    op.execute(f"""
    CREATE TABLE substance_or_behavior_use (
        use_id text NOT NULL,
        patient_id text NOT NULL,
        category text NOT NULL,
        substance_or_behavior text NOT NULL,
        pattern text NOT NULL,
        start_date date NOT NULL,
        end_date date,
        status text NOT NULL,
        {COMMON},
        CONSTRAINT pk_substance_or_behavior_use PRIMARY KEY (use_id),
        CONSTRAINT fk_substance_or_behavior_use_patient_id_patients
            FOREIGN KEY (patient_id) REFERENCES patients (patient_id) ON DELETE CASCADE,
        CONSTRAINT ck_substance_or_behavior_use_key_matches_patient CHECK (use_id LIKE patient_id || '-U%'),
        CONSTRAINT ck_substance_or_behavior_use_category_values CHECK (category IN ({CATEGORY})),
        CONSTRAINT ck_substance_or_behavior_use_pattern_values CHECK (pattern IN (
            'daily', 'several_per_week', 'weekends', 'binge_episodic', 'intermittent', 'unknown')),
        CONSTRAINT ck_substance_or_behavior_use_status_values CHECK (status IN (
            'active', 'reduced', 'supervised', 'abstinent', 'unknown')),
        CONSTRAINT ck_substance_or_behavior_use_start_not_future CHECK (start_date <= CURRENT_DATE),
        CONSTRAINT ck_substance_or_behavior_use_end_not_future CHECK (end_date IS NULL OR end_date <= CURRENT_DATE),
        CONSTRAINT ck_substance_or_behavior_use_end_after_start CHECK (end_date IS NULL OR end_date >= start_date),
        CONSTRAINT ck_substance_or_behavior_use_end_needs_abstinent_or_unknown
            CHECK (end_date IS NULL OR status IN ('abstinent', 'unknown')),
        CONSTRAINT ck_substance_or_behavior_use_subject_not_blank CHECK (length(trim(substance_or_behavior)) > 0),
        CONSTRAINT ck_substance_or_behavior_use_is_synthetic_true CHECK (is_synthetic)
    )""")
    op.execute("CREATE INDEX ix_substance_or_behavior_use_patient_start ON substance_or_behavior_use (patient_id, start_date)")

    op.execute(f"""
    CREATE TABLE triggers_and_risk_factors (
        factor_id text NOT NULL,
        patient_id text NOT NULL,
        kind text NOT NULL,
        context text NOT NULL,
        description text NOT NULL,
        {COMMON},
        CONSTRAINT pk_triggers_and_risk_factors PRIMARY KEY (factor_id),
        CONSTRAINT fk_triggers_and_risk_factors_patient_id_patients
            FOREIGN KEY (patient_id) REFERENCES patients (patient_id) ON DELETE CASCADE,
        CONSTRAINT ck_triggers_and_risk_factors_key_matches_patient CHECK (factor_id LIKE patient_id || '-F%'),
        CONSTRAINT ck_triggers_and_risk_factors_kind_values CHECK (kind IN (
            'trigger', 'risk_factor', 'protective_factor', 'observed_behavior')),
        CONSTRAINT ck_triggers_and_risk_factors_context_values CHECK (context IN (
            'emotional', 'social', 'work', 'financial', 'health', 'environmental', 'unknown')),
        CONSTRAINT ck_triggers_and_risk_factors_description_not_blank CHECK (length(trim(description)) > 0),
        CONSTRAINT ck_triggers_and_risk_factors_is_synthetic_true CHECK (is_synthetic)
    )""")
    op.execute("CREATE INDEX ix_triggers_and_risk_factors_patient_kind ON triggers_and_risk_factors (patient_id, kind)")

    op.execute(f"""
    CREATE TABLE previous_interventions (
        intervention_id text NOT NULL,
        patient_id text NOT NULL,
        intervention_type text NOT NULL,
        setting text NOT NULL,
        start_date date NOT NULL,
        end_date date,
        completion_status text NOT NULL,
        reported_outcome text NOT NULL,
        {COMMON},
        CONSTRAINT pk_previous_interventions PRIMARY KEY (intervention_id),
        CONSTRAINT fk_previous_interventions_patient_id_patients
            FOREIGN KEY (patient_id) REFERENCES patients (patient_id) ON DELETE CASCADE,
        CONSTRAINT ck_previous_interventions_key_matches_patient CHECK (intervention_id LIKE patient_id || '-I%'),
        CONSTRAINT ck_previous_interventions_type_values CHECK (intervention_type IN (
            'brief_advice', 'outpatient_counseling', 'group_support', 'residential_program',
            'medication_supported_program', 'inpatient_stay', 'pain_management_program',
            'self_exclusion_or_blocking', 'family_sessions', 'other')),
        CONSTRAINT ck_previous_interventions_status_values CHECK (completion_status IN (
            'completed', 'dropped_out', 'ongoing', 'not_started', 'unknown')),
        CONSTRAINT ck_previous_interventions_start_not_future CHECK (start_date <= CURRENT_DATE),
        CONSTRAINT ck_previous_interventions_end_not_future CHECK (end_date IS NULL OR end_date <= CURRENT_DATE),
        CONSTRAINT ck_previous_interventions_end_after_start CHECK (end_date IS NULL OR end_date >= start_date),
        CONSTRAINT ck_previous_interventions_status_matches_end_date CHECK (
            (completion_status = 'ongoing' AND end_date IS NULL)
            OR (completion_status IN ('completed', 'dropped_out') AND end_date IS NOT NULL)
            OR completion_status IN ('not_started', 'unknown')),
        CONSTRAINT ck_previous_interventions_text_not_blank CHECK (
            length(trim(setting)) > 0 AND length(trim(reported_outcome)) > 0),
        CONSTRAINT ck_previous_interventions_is_synthetic_true CHECK (is_synthetic)
    )""")
    op.execute("CREATE INDEX ix_previous_interventions_patient_start ON previous_interventions (patient_id, start_date)")

    op.execute(f"""
    CREATE TABLE progress_observations (
        observation_id text NOT NULL,
        patient_id text NOT NULL,
        observed_on date NOT NULL,
        use_status text NOT NULL,
        motivation text NOT NULL,
        note text NOT NULL,
        {COMMON},
        CONSTRAINT pk_progress_observations PRIMARY KEY (observation_id),
        CONSTRAINT fk_progress_observations_patient_id_patients
            FOREIGN KEY (patient_id) REFERENCES patients (patient_id) ON DELETE CASCADE,
        CONSTRAINT ck_progress_observations_key_matches_patient CHECK (observation_id LIKE patient_id || '-O%'),
        CONSTRAINT ck_progress_observations_use_status_values CHECK (use_status IN (
            'abstinent', 'reduced', 'unchanged', 'increased', 'relapse', 'unknown')),
        CONSTRAINT ck_progress_observations_motivation_values CHECK (motivation IN ({MOTIVATION})),
        CONSTRAINT ck_progress_observations_observed_not_future CHECK (observed_on <= CURRENT_DATE),
        CONSTRAINT ck_progress_observations_note_not_blank CHECK (length(trim(note)) > 0),
        CONSTRAINT ck_progress_observations_is_synthetic_true CHECK (is_synthetic)
    )""")
    op.execute("CREATE INDEX ix_progress_observations_patient_date ON progress_observations (patient_id, observed_on)")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
