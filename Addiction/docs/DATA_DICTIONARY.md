# Data dictionary: synthetic patient database (Batch 02)

All data here is **fictional**. Patient tables hold **patient facts only**: no research claims, citations, or model interpretations. Users, sessions, documents and logs live in separate tables added in later batches.

Every table has `is_synthetic boolean NOT NULL DEFAULT true` with `CHECK (is_synthetic)`, so a non-synthetic row cannot be stored.
Every date column has `CHECK (date <= CURRENT_DATE)`. (`CURRENT_DATE` is not an immutable expression; that is allowed in a CHECK and is documented here on purpose.)
"Unknown" is always written explicitly (`'unknown'` or a sentence such as "Family history: unknown"), never left silently empty.

Record ids are text keys built from the patient id and the position in the seed file, for example `P-001-H03`. A CHECK on each child table makes sure the key prefix matches its patient. That makes seeding deterministic and idempotent.

```mermaid
erDiagram
  patients ||--o{ patient_history_events : has
  patients ||--o{ substance_or_behavior_use : has
  patients ||--o{ triggers_and_risk_factors : has
  patients ||--o{ previous_interventions : has
  patients ||--o{ progress_observations : has
```

All five child tables reference `patients.patient_id` with `ON DELETE CASCADE`.

## patients
One row per synthetic patient.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `patient_id` | text, PK | `P-001` .. `P-010`. CHECK `~ '^P-[0-9]{3}$'`. The only identifier; no names. |
| `age_at_intake` | smallint | Age instead of date of birth. CHECK 18..110 (adults only). |
| `gender` | text | `woman`, `man`, `non_binary`, `other`, `unknown`. |
| `primary_category` | text | `alcohol`, `cannabis`, `opioids`, `stimulants`, `behavioral`. A label for grouping, not a statement about suitable treatment. |
| `intake_date` | date | Date of the case intake. Not in the future. All progress observations are on or after it. |
| `living_situation` | text | Housing and household, or `unknown`. |
| `employment_status` | text | Work or study situation, or `unknown`. |
| `social_context` | text | Relationships and settings that matter for the case. |
| `co_occurring_symptoms` | text | Other reported symptoms (for example sleep difficulty), or "none reported" / "unknown". |
| `motivation_at_intake` | text | `none_expressed`, `ambivalent`, `contemplating`, `preparing`, `engaged`, `unknown`. |
| `background` | text | Short fictional background. |
| `history_summary` | text | One or two sentences summarizing use history. Must agree with the detail tables. |
| `treatment_summary` | text | One or two sentences summarizing past and current contact with services. Must agree with `previous_interventions`. |
| `is_synthetic` | boolean | Always true. |
| `created_at`, `updated_at` | timestamptz | Row timestamps. `updated_at` changes only when the seed content changes. |

## patient_history_events
Dated life and use events: the backbone of each timeline.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `event_id` | text, PK | `P-001-H01`, ... in chronological order. |
| `patient_id` | text, FK | Owner patient. |
| `event_date` | date | When it happened. For `year`/`month` precision the first day of that period is stored. |
| `date_precision` | text | `year`, `month`, `day`: how exact the date is. |
| `event_type` | text | `onset`, `escalation`, `life_event`, `health_event`, `legal_or_work_event`, `help_seeking`, `treatment_contact`, `reduction_attempt`, `relapse`, `recovery_milestone`, `other`. |
| `description` | text | Non-instructional description of the event. |

Seed rules checked by tests: the first event is the `onset` and matches the start of the primary use record; every intervention start date has a matching day-precision `treatment_contact` event.

## substance_or_behavior_use
What the patient uses or does, and how that pattern changed.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `use_id` | text, PK | `P-001-U01`, ... |
| `patient_id` | text, FK | Owner patient. |
| `category` | text | Same values as `patients.primary_category`. |
| `substance_or_behavior` | text | Plain name, for example "Alcohol" or "Online sports betting". |
| `pattern` | text | `daily`, `several_per_week`, `weekends`, `binge_episodic`, `intermittent`, `unknown`. |
| `start_date` | date | When the pattern began. |
| `end_date` | date, nullable | End of the pattern. NULL means ongoing. CHECK `>= start_date`; allowed only when `status` is `abstinent` or `unknown`. |
| `status` | text | `active`, `reduced`, `supervised` (use within a supervised arrangement), `abstinent`, `unknown`. |

The latest progress observation must agree with this status (checked by a test).

## triggers_and_risk_factors
Context around the patient's use.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `factor_id` | text, PK | `P-001-F01`, ... |
| `patient_id` | text, FK | Owner patient. |
| `kind` | text | `trigger`, `risk_factor`, `protective_factor`, `observed_behavior`. |
| `context` | text | `emotional`, `social`, `work`, `financial`, `health`, `environmental`, `unknown`. |
| `description` | text | What the factor is. Unknown items say so explicitly. |

Every patient has at least one `trigger`. These are descriptions of the case, not claims about causes.

## previous_interventions
Contact with services, as it happened.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `intervention_id` | text, PK | `P-001-I01`, ... |
| `patient_id` | text, FK | Owner patient. |
| `intervention_type` | text | `brief_advice`, `outpatient_counseling`, `group_support`, `residential_program`, `medication_supported_program`, `inpatient_stay`, `pain_management_program`, `self_exclusion_or_blocking`, `family_sessions`, `other`. |
| `setting` | text | Where it took place. |
| `start_date` | date | Start. |
| `end_date` | date, nullable | End. CHECK `>= start_date`. |
| `completion_status` | text | `completed`, `dropped_out`, `ongoing`, `not_started`, `unknown`. CHECK: `ongoing` has no end date; `completed`/`dropped_out` have one. |
| `reported_outcome` | text | What happened to the patient (attendance, what they did afterwards). It never states that an approach works or is best. |

## progress_observations
Check-ins after intake.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `observation_id` | text, PK | `P-001-O01`, ... in chronological order. |
| `patient_id` | text, FK | Owner patient. |
| `observed_on` | date | Date of the check-in. On or after `intake_date`. |
| `use_status` | text | `abstinent`, `reduced`, `unchanged`, `increased`, `relapse`, `unknown`. |
| `motivation` | text | Same values as `motivation_at_intake`. |
| `note` | text | Short factual note. |

## Indexes
`(patient_id, event_date)`, `(patient_id, start_date)` (use and interventions), `(patient_id, kind)` (factors), `(patient_id, observed_on)` (progress). Each starts with `patient_id`, so patient lookups are covered.

## Sample queries
- `backend/db/queries/patient_profile.sql`: one patient plus all related records as JSON arrays.
- `backend/db/queries/patient_history.sql`: one patient's chronological history across all tables.

Both take the named parameter `:patient_id`.

## Content rules for the seed files
No names, contact data or links. No substance preparation or dosing, no methods of self-harm. No treatment recommendations or "best treatment" statements. No research findings or citations. A test scans the seed text for emails, phone numbers, links and a list of instructional or advisory words.

---

# Added in Batch 03 (migration 0002)

These tables are **not patient data**. They are separate from the six patient tables above. Nothing in them is a research claim yet.

## papers
Metadata for the research corpus. No document text and no chunks (Batch 05), and no file path is stored.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `paper_id` | text, PK | Stable slug, for example `who-mhgap-guideline-2023`. CHECK `~ '^[a-z0-9][a-z0-9-]*$'`. |
| `title` | text | Title as written in the project's corpus list. Not blank. |
| `document_type` | text | `guideline`, `guide`, `review`, `unknown`. Taken from the title only. |
| `publisher` | text | For example `WHO` or `NIDA`, or the explicit text `unknown`. |
| `publication_year` | text | Four digits or the explicit text `unknown` (CHECK `~ '^(unknown\|[0-9]{4})$'`). Text, so "unknown" is a real value. |
| `source_note` | text | Where the metadata came from and that it was not verified against the document. |
| `ingest_status` | text | `not_ingested` (default), `ingested`, `failed`. Changed by Batch 05. The seed never resets it. |
| `created_at` | timestamptz | Row creation time. |

Seeded from `backend/db/seed_data/papers.json` (4 papers). The fourth is a psychosocial-interventions review, not the Cochrane review named in `docs/SPEC.md`.

## chat_sessions
A conversation about one patient. Named `chat_sessions` so it is never confused with the login session (`auth_sessions`) of Batch 04.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `session_id` | uuid, PK | Generated by the database (`gen_random_uuid()`). |
| `patient_id` | text, FK to `patients` | `ON DELETE RESTRICT`: a patient who has sessions cannot be deleted by accident. |
| `title` | text | 1 to 120 characters after trimming. |
| `owner_id` | uuid, nullable, FK to `users(id)` `ON DELETE RESTRICT` | The user who owns the session (set since Batch 04). `NULL` only for rows created in Batch 03; the API shows those to nobody. Indexed with `created_at`. |
| `created_at` | timestamptz | Creation time. |

## chat_messages
Messages inside a chat session. Nothing writes to this table in Batch 03.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `message_id` | uuid, PK | Generated by the database. |
| `session_id` | uuid, FK to `chat_sessions` | `ON DELETE CASCADE`: messages are removed with their session. |
| `role` | text | `user` or `assistant`. |
| `mode` | text, nullable | `general_knowledge`, `rag`, `both`, or NULL (for example for user messages). |
| `content` | text | Not blank, at most 8000 characters. |
| `created_at` | timestamptz | Used for ordering (`created_at`, then `message_id`). |

Indexes: `chat_sessions (patient_id, created_at)` and `chat_messages (session_id, created_at)`.

## Changes to existing query files
`backend/db/queries/patient_history.sql` now also returns `date_precision` (set for history events, NULL for other rows) so the frontend can format "Sep 2012" correctly.

# Added in Batch 04 (migration 0003)

Sign-in data, not patient data. These tables hold real Google account details of whoever signs in, so they are never part of the seed.

## users
One row per Google account. Identity is `google_sub` (Google's stable subject id), never the email, which can change.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `id` | uuid, PK | Generated by the database. |
| `google_sub` | text, unique, not blank | Google's `sub` claim. The identity key. |
| `email` | text | Updated at every login; not unique and not an identity. |
| `email_verified` | boolean | Always true for stored users (unverified emails are rejected at login). |
| `display_name` | text, nullable | Google profile name; shown in the UI with `textContent`. |
| `role` | text | `student` (default) or `admin`; recomputed at each login from `ADMIN_EMAILS`. |
| `created_at`, `updated_at`, `last_login_at` | timestamptz | Bookkeeping. |

## auth_sessions
Login sessions (distinct from `chat_sessions`).

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `id` | uuid, PK | Generated by the database. |
| `user_id` | uuid, FK to `users` | `ON DELETE CASCADE`: deleting a user ends their logins. |
| `token_hash` | text, unique | SHA-256 hex of the random cookie token. The raw token is never stored. |
| `csrf_token` | text | Random per session; returned by `GET /api/auth/me`. |
| `created_at`, `last_seen_at` | timestamptz | `last_seen_at` drives the idle timeout (updated at most once a minute). |
| `expires_at` | timestamptz | Absolute lifetime (`SESSION_MAX_HOURS`). |
| `revoked_at` | timestamptz, nullable | Set by logout. Expired sessions are deleted lazily; revoked ones a day later, at the user's next login. |

Index `ix_auth_sessions_user_id`. Google's access, refresh and ID tokens are not stored anywhere.

# Added in Batch 05 (migration 0004)

Document ingestion state. No vector column or extension exists yet (Batches 06 and 07).

## papers (new columns)
| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `file_name` | text, nullable | Bare PDF file name inside `data/papers/` (no `/` or `\\`). **Internal only: never returned by the API.** |
| `content_sha256` | text, nullable | SHA-256 of the PDF (64 hex characters). Used to detect changed files. Not returned by the API. |
| `page_count` | integer, nullable | Pages in the PDF (> 0). |
| `chunking_version` | text, nullable | Pipeline version, tokenizer revision and chunking parameters; a change triggers re-chunking. |
| `ingested_at` | timestamptz, nullable | When the stored state was last written. |
| `doi` | text, nullable | DOI as printed in the document, or null. |
| `metadata_source` | text, default `project_list` | `project_list` (from the project's own list) or `document_text` (printed in the document). |
| `low_text_pages` | integer[], default `{}` | 1-based numbers of pages skipped for having fewer than 50 non-space characters. |
| `ingest_note` | text, nullable | Short safe reason for `failed` / `needs_ocr` (no paths, no stack traces). |

`ingest_status` is now one of `not_ingested`, `ingested`, `failed`, `needs_ocr` (the last one was added in Batch 05).

## paper_chunks
One row per chunk of text. `ON DELETE CASCADE` from `papers`.

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `chunk_id` | text, PK | `<paper_id>-c<ordinal:04d>`, for example `who-mhgap-guideline-2023-c0042`; stable across runs on the same input. |
| `paper_id` | text, FK to `papers` | The document. |
| `ordinal` | integer | 1-based position in the document; unique per paper (unique index). |
| `text` | text | The cleaned chunk text, not blank. Copyrighted: shown to administrators only. |
| `token_count` | integer | Tokens counted with the all-MiniLM-L6-v2 tokenizer, including [CLS] and [SEP]; at most the configured maximum (250). |
| `page_start`, `page_end` | integer | Page range the text comes from (1-based, end >= start). |
| `section_title` | text, nullable | From the PDF outline or a heading heuristic; null when unknown, never invented. |
| `section_type` | text | `body`, `table_or_figure`, `references` or `front_matter` (heuristic). |
| `text_sha256` | text | SHA-256 of `text`. |
| `possible_injection` | boolean | Heuristic marker for instruction-like phrases; for review only, not a security control. |
| `created_at` | timestamptz | Insert time. |

Indexes: `ix_paper_chunks_paper_id`, and the unique `ix_paper_chunks_paper_ordinal` on `(paper_id, ordinal)`.

## ingestion_runs
Statistics about each ingestion run (never document text).

| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `run_id` | uuid, PK | Generated by the database. |
| `started_at`, `finished_at` | timestamptz | Start and end of the run. |
| `status` | text | `running`, `completed`, `completed_with_errors` or `failed`. |
| `config` | jsonb | Chunking parameters and the tokenizer revision. |
| `results` | jsonb | Per document: status, action, pages, low-text page count, chunk count. |

Dry runs write no row.

# Added in Batch 06 (migration 0005)

Embeddings for semantic search (see `docs/RETRIEVAL.md`). The migration creates the `vector` extension (pgvector) and adds columns to `paper_chunks`. **No ANN index** (HNSW / ivfflat) exists: exact search is used.

## paper_chunks (new columns)
| Column | Type | Purpose / rules |
|--------|------|-----------------|
| `embedding` | vector(384), nullable | L2-normalized embedding of `text` (all-MiniLM-L6-v2). Present only when `embedding_status = 'embedded'`. |
| `embedding_fingerprint` | text, nullable | Model name + exact revision + dimension + normalization, e.g. `sentence-transformers/all-MiniLM-L6-v2@1110a243...|dim=384|l2norm`. Vectors with different fingerprints must never be compared. |
| `embedded_at` | timestamptz, nullable | When the vector was stored. |
| `embedding_status` | text, default `pending` | `pending` (new or changed chunk), `embedded` or `skipped` (not eligible: references, front matter, or fewer than `EMBED_MIN_TOKENS` tokens; the reason is derived from `section_type` and `token_count`). Indexed. |

A CHECK constraint makes the columns consistent: `embedding IS NOT NULL` exactly when `embedding_status = 'embedded'` and `embedding_fingerprint IS NOT NULL`. Chunks written by ingestion (Batch 05) get the default `pending`; replacing a document's chunks deletes the old vectors with the old rows.

