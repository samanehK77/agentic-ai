# MindEvidence Lab: Project Spec

## Purpose
An educational, RAG-based research assistant for psychology students who study addiction treatment. Students explore 10 synthetic patient cases and ask questions that are answered from a small corpus of authorized research documents, with traceable citations. This is a teaching tool, not a clinical one: it does not diagnose, prescribe, or choose individual treatments.

## Users
- Students: sign in with Google, explore cases, ask questions, inspect evidence.
- Instructor (admin): manages the document corpus and reviews activity logs.

## Core features
- Patient explorer and detail view for P-001 to P-010, all clearly labeled synthetic.
- Chat with the selected patient as context.
- Answer modes: General Knowledge, RAG, Both (and an optional Auto mode).
- Evidence inspector: retrieved chunks with document, section, page, and citation ID.
- Activity timeline and audit trail for every question.
- Optional email summaries through Gmail, only with explicit consent.

## Architecture
- Frontend: vanilla HTML, CSS, and JavaScript (ES modules), no frameworks.
- Backend: Python, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic.
- Database: PostgreSQL with pgvector.
- Authentication: Google OAuth 2.0 / OpenID Connect with a backend session cookie.
- Retrieval: PDF ingestion (PyMuPDF), chunks of about 220 tokens (at most 250, counted with the model's own tokenizer), sentence-transformers/all-MiniLM-L6-v2 embeddings, cosine search. Deviation from the original "400-700 tokens": that model truncates its input at 256 word pieces, so longer chunks would silently lose their tail (see `docs/INGESTION.md`).
- LLM: the DeepSeek API, called only from the backend, behind a provider interface.
- Orchestration: a LangGraph workflow with typed state.
- Observability: structured audit events in PostgreSQL, linked by correlation IDs.

## Data
- Patients: 10 fictional adult cases (alcohol, cannabis, opioids, stimulants, behavioral addictions) with consistent timelines. No real people or records.
- Research corpus: WHO mhGAP Guideline (2023), NIDA Principles of Drug Addiction Treatment, WHO mhGAP Intervention Guide v2.0, and a Cochrane review on alcohol use disorder (2025).
- Patient facts, research evidence, and model interpretations are always kept and shown separately.

## Ground rules
- Secrets live only in environment variables, never in frontend code or the repository.
- Citations always point to real retrieved chunks; missing evidence is stated, never invented.
- Retrieved document text is untrusted data and never acts as instructions.
- Test results are reported honestly; the project claims no production readiness or clinical validation.

## Build plan
The project is built in ten batches, each described in its own prompt:
01 Frontend with mock data · 02 PostgreSQL data model and seed · 03 FastAPI backend · 04 Google sign-in · 05 Document ingestion · 06 pgvector retrieval · 07 DeepSeek answers with citations · 08 LangGraph orchestration · 09 Observability, audit, and Gmail reports · 10 Integration and classroom demo.

## Repository layout
frontend/ · backend/ · data/papers/ · docs/
(this file is docs/SPEC.md)

---

## Deviations from the original spec

Appended during Batch 10. The instructor's text above is unchanged; this section records where the built system differs from it.

* **Chunk size.** About 220 tokens (at most 250), not the "400-700 tokens" originally planned. The embedding model
  (`all-MiniLM-L6-v2`) truncates its input at 256 word pieces, so longer chunks would silently lose their tail; chunks are counted
  with the model's own tokenizer (`docs/INGESTION.md`).
* **Five documents, not four.** The corpus holds the four documents named under "Data" plus a fifth review, "Psychosocial
  Interventions for Alcohol Use Disorder: A Review of Efficacy, Mechanisms, and Clinical Implications" (`data/papers/README.md`).
  The PDFs are copyrighted and are not in the repository.
* **Local language model.** The LLM is called only from the backend behind a provider interface, as specified, but the working
  configuration uses a **local Ollama model** (development used `qwen3.5-16k`, 9.7B parameters, 4-bit) instead of the DeepSeek API;
  the DeepSeek API remains supported. Nothing leaves the machine with the local model. Small local models are less reliable
  (invalid JSON, slow answers); the system reports this rather than hiding it.
* **No Auto mode.** The optional "Auto" answer mode was not built; the three modes are General Knowledge, RAG and Both.
* **Gmail summaries not implemented.** "Optional email summaries through Gmail" was deliberately not implemented (it is
  optional). No Gmail scope, token storage or sender exists; sign-in uses only `openid email profile`.
* **Orchestration.** The LangGraph workflow has ten nodes with deterministic routing (no model call for unsupported requests,
  history questions answered from patient facts, or no-evidence cases).
* **Observability.** Audit events are metadata-only and written in their own transactions; `chat_messages.trace` keeps a
  per-message snapshot of the same node trace.
* **Extra components not in the spec.** Operator diagnostics, an administrator audit view, answer feedback, a comparative
  evaluation, a Docker profile and a setup guide (Batch 10).
* **Development setup only.** Plain HTTP on `localhost`, development-only configuration; not production-ready and not clinically
  validated.
