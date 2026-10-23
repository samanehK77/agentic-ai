-- Full profile of one synthetic patient: the patient row plus all related records as JSON arrays.
-- Parameter: :patient_id  (for example 'P-001')
SELECT
    p.patient_id,
    p.age_at_intake,
    p.gender,
    p.primary_category,
    p.intake_date,
    p.living_situation,
    p.employment_status,
    p.social_context,
    p.co_occurring_symptoms,
    p.motivation_at_intake,
    p.background,
    p.history_summary,
    p.treatment_summary,
    p.is_synthetic,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'id', u.use_id, 'category', u.category, 'subject', u.substance_or_behavior,
                   'pattern', u.pattern, 'start_date', u.start_date, 'end_date', u.end_date, 'status', u.status)
               ORDER BY u.start_date, u.use_id)
        FROM substance_or_behavior_use u WHERE u.patient_id = p.patient_id), '[]'::jsonb) AS use_records,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'id', f.factor_id, 'kind', f.kind, 'context', f.context, 'description', f.description)
               ORDER BY f.kind, f.factor_id)
        FROM triggers_and_risk_factors f WHERE f.patient_id = p.patient_id), '[]'::jsonb) AS factors,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'id', i.intervention_id, 'type', i.intervention_type, 'setting', i.setting,
                   'start_date', i.start_date, 'end_date', i.end_date,
                   'completion_status', i.completion_status, 'reported_outcome', i.reported_outcome)
               ORDER BY i.start_date, i.intervention_id)
        FROM previous_interventions i WHERE i.patient_id = p.patient_id), '[]'::jsonb) AS interventions,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'id', o.observation_id, 'observed_on', o.observed_on, 'use_status', o.use_status,
                   'motivation', o.motivation, 'note', o.note)
               ORDER BY o.observed_on, o.observation_id)
        FROM progress_observations o WHERE o.patient_id = p.patient_id), '[]'::jsonb) AS progress
FROM patients p
WHERE p.patient_id = :patient_id;
