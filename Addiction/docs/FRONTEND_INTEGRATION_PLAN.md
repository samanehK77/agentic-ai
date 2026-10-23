# Frontend integration plan (for Batch 03)

Maps every field in `frontend/data/mock-data.js` to a database table and column and to the future API endpoint. Nothing here is built yet: no API exists in Batch 02 and the frontend is unchanged.

The UI only talks to `frontend/js/api.js`, so Batch 03 replaces the function bodies with `fetch()` calls and a small adapter that reshapes API JSON into the shapes below.

## Endpoints used by `api.js`

| `api.js` function | Future endpoint | Source |
|-------------------|-----------------|--------|
| `listPatients()` | `GET /api/patients` | `patients` (+ one row of `substance_or_behavior_use` for the label) |
| `getPatient(id)` | `GET /api/patients/{patient_id}` | `patients` + all five child tables (same data as `patient_profile.sql`) |
| `getChunk(citationId)` | `GET /api/chunks/{citation_id}` | Document tables (Batch 05/06), not this batch |
| `askQuestion(...)` | `POST /api/patients/{patient_id}/questions` | RAG + LLM (Batches 06-08), not this batch |

## Patient fields (`PATIENTS[]`)

| Mock field | Table.column | Notes |
|------------|--------------|-------|
| `id` | `patients.patient_id` | Same ids `P-001` .. `P-010`. |
| `age` | `patients.age_at_intake` | Age at intake, not current age. |
| `sex` ("Male"/"Female") | `patients.gender` | Values become `man`, `woman`, `non_binary`, `other`, `unknown`. The adapter maps them to display labels; the field is renamed `gender`. |
| `category` ("Alcohol", "Behavioral: gambling") | `patients.primary_category` + `substance_or_behavior_use.substance_or_behavior` | The adapter builds the label, for example `behavioral` + "Online sports betting". |
| `summary` | `patients.history_summary` | |
| `treatment_summary` | `patients.treatment_summary` | |
| `background` | `patients.background` | |
| `behaviors[]` | `triggers_and_risk_factors.description` where `kind = 'observed_behavior'` | |
| `history[].period` | `patient_history_events.event_date` + `date_precision` | Adapter formats by precision (year, month, day). |
| `history[].event` | `patient_history_events.description` | Ordered by `event_date`. |
| `triggers[]` | `triggers_and_risk_factors.description` where `kind = 'trigger'` | |
| `previous_interventions[].name` | `previous_interventions.intervention_type` + `setting` | Adapter builds a readable name. |
| `previous_interventions[].period` | `previous_interventions.start_date` / `end_date` | `end_date` NULL means "ongoing". |
| `previous_interventions[].outcome` | `previous_interventions.reported_outcome` | |
| `progress.status` | latest `progress_observations.use_status` + `motivation` | Adapter builds a label. |
| `progress.note` | latest `progress_observations.note` | Latest = highest `observed_on`. |

New fields the API can offer that the mock lacks: `living_situation`, `employment_status`, `social_context`, `co_occurring_symptoms`, `motivation_at_intake`, `intake_date`, `protective_factor` items, and full progress history. The UI can show them later; no change is required for the first integration.

**The seed supersedes the mock text.** Names, ages, wording and some details differ (for example P-004's background). After Batch 03 the database is the source of truth and the mock patient text will be removed.

## Not from this database

| Mock item | Where it comes from later |
|-----------|---------------------------|
| `CHUNKS[]` (`citation_id`, `document`, `section`, `page`, `text`, `score`) | Document and chunk tables (Batch 05) and retrieval (Batch 06). The chunk fields already match. |
| `REPLIES`, reply `citations` | LLM answers with citations (Batch 07). |
| `TIMELINE_STEPS`, timeline events | Audit events (Batch 09). |
| `MODES` | Static configuration shared by frontend and backend. |
| `SYNTHETIC_NOTICE` | Stays a frontend constant. |

## Rules to keep
- Patient facts, research evidence and model interpretations stay in separate tables and separate UI blocks.
- Every patient response includes `is_synthetic: true` so the UI can keep showing the synthetic labels.
