from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from db.models import VOCAB, Base
from tests.conftest import alembic_config, recreate_database

TABLES = {
    "patients", "patient_history_events", "substance_or_behavior_use",
    "triggers_and_risk_factors", "previous_interventions", "progress_observations",
    "papers", "chat_sessions", "chat_messages", "users", "auth_sessions",
    "paper_chunks", "ingestion_runs",
}


def test_migrations_apply_from_empty_and_downgrade_cleanly():
    url = recreate_database("test_migration")
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        assert set(inspect(engine).get_table_names()) == set()

        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == TABLES | {"alembic_version"}

        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}

        command.upgrade(config, "head")  # and back up again
        assert TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_no_forbidden_tables(engine):
    names = set(inspect(engine).get_table_names())
    for forbidden in ("sessions", "documents", "logs", "audit_events"):
        assert forbidden not in names


def test_models_match_migration(engine):
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_vocabulary_in_models_matches_check_constraints(engine):
    expected = {
        ("patients", "ck_patients_gender_values"): "gender",
        ("patients", "ck_patients_category_values"): "category",
        ("patients", "ck_patients_motivation_values"): "motivation",
        ("patient_history_events", "ck_patient_history_events_precision_values"): "date_precision",
        ("patient_history_events", "ck_patient_history_events_type_values"): "event_type",
        ("substance_or_behavior_use", "ck_substance_or_behavior_use_pattern_values"): "use_pattern",
        ("substance_or_behavior_use", "ck_substance_or_behavior_use_status_values"): "use_status",
        ("triggers_and_risk_factors", "ck_triggers_and_risk_factors_kind_values"): "factor_kind",
        ("triggers_and_risk_factors", "ck_triggers_and_risk_factors_context_values"): "factor_context",
        ("previous_interventions", "ck_previous_interventions_type_values"): "intervention_type",
        ("previous_interventions", "ck_previous_interventions_status_values"): "completion_status",
        ("progress_observations", "ck_progress_observations_use_status_values"): "progress_status",
        ("papers", "ck_papers_document_type_values"): "document_type",
        ("papers", "ck_papers_ingest_status_values"): "ingest_status",
        ("papers", "ck_papers_metadata_source_values"): "metadata_source",
        ("paper_chunks", "ck_paper_chunks_section_type_values"): "section_type",
        ("ingestion_runs", "ck_ingestion_runs_status_values"): "run_status",
        ("users", "ck_users_role_values"): "user_role",
        ("paper_chunks", "ck_paper_chunks_embedding_status_values"): "embedding_status",
        ("chat_messages", "ck_chat_messages_role_values"): "message_role",
        ("chat_messages", "ck_chat_messages_mode_values"): "chat_mode",
    }
    with engine.connect() as connection:
        for (table, constraint), key in expected.items():
            definition = connection.scalar(text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"), {"name": constraint})
            assert definition, f"{constraint} is missing"
            for value in VOCAB[key]:
                assert f"'{value}'" in definition, f"{value!r} missing from {constraint}"
            assert definition.count("'") == 2 * len(VOCAB[key]), \
                f"{constraint} allows values that are not in VOCAB[{key!r}]"
