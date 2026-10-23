-- Chronological history of one synthetic patient across all record types.
-- Parameter: :patient_id  (for example 'P-001')
-- date_precision is set for history events only (year, month or day); it is NULL for other rows.
-- Rows on the same date are ordered: history event, use, intervention, progress.
SELECT event_date, date_precision, source, record_id, kind, summary
FROM (
    SELECT h.event_date, 'history' AS source, h.event_id AS record_id, h.event_type AS kind,
           h.description AS summary, h.date_precision, 1 AS source_order
    FROM patient_history_events h WHERE h.patient_id = :patient_id

    UNION ALL
    SELECT u.start_date, 'use', u.use_id, 'use_started',
           u.substance_or_behavior || ' (' || u.pattern || ')', NULL, 2
    FROM substance_or_behavior_use u WHERE u.patient_id = :patient_id

    UNION ALL
    SELECT u.end_date, 'use', u.use_id, 'use_ended',
           u.substance_or_behavior || ' (status: ' || u.status || ')', NULL, 2
    FROM substance_or_behavior_use u WHERE u.patient_id = :patient_id AND u.end_date IS NOT NULL

    UNION ALL
    SELECT i.start_date, 'intervention', i.intervention_id, 'intervention_started',
           i.intervention_type || ' - ' || i.setting, NULL, 3
    FROM previous_interventions i WHERE i.patient_id = :patient_id

    UNION ALL
    SELECT i.end_date, 'intervention', i.intervention_id, 'intervention_ended',
           i.intervention_type || ' (' || i.completion_status || '): ' || i.reported_outcome, NULL, 3
    FROM previous_interventions i WHERE i.patient_id = :patient_id AND i.end_date IS NOT NULL

    UNION ALL
    SELECT o.observed_on, 'progress', o.observation_id, 'observation',
           o.use_status || ' / ' || o.motivation || ': ' || o.note, NULL, 4
    FROM progress_observations o WHERE o.patient_id = :patient_id
) AS timeline
ORDER BY event_date, source_order, record_id, (kind LIKE '%\_ended');
