# Teaching guide

What each part of MindEvidence Lab demonstrates, where to find it, and a question to discuss. The system is an educational
prototype with synthetic data; use it to talk about how such systems are built and where they fail, not as a clinical tool.

Suggested use: 60-90 minutes (demo from `docs/DEMO_SCRIPT.md`, then two or three discussion questions) or one topic per session.

| Batch | Component | Concept demonstrated | Where in the code | Discussion question |
|-------|-----------|----------------------|-------------------|---------------------|
| 01 | Frontend with mock data | Designing an interface before the backend exists; showing different kinds of content with colour **and** icon **and** label; loading/empty/error states; `textContent` instead of HTML | `frontend/js/render/`, `frontend/data/mock-data.js`, `?source=mock` and `?state=` | Why must patient facts, research evidence and model interpretation look different? What could go wrong if they looked the same? |
| 02 | PostgreSQL data model and seed | Relational modelling, constraints as documentation, synthetic data with consistent timelines | `backend/db/models.py`, `alembic/versions/0001-0002`, `db/seed_data/`, `docs/DATA_DICTIONARY.md` | What makes a synthetic case "realistic enough" to teach with, without being real? What would be unsafe about using real records? |
| 03 | FastAPI backend | Layering (routers → services → repositories), one error format, pagination, OpenAPI as a contract | `backend/app/routers/`, `services.py`, `repositories/`, `errors.py`, `docs/API.md` | Why return the same `404` for "does not exist" and "belongs to someone else"? |
| 04 | Google sign-in | OpenID Connect with PKCE, server-side sessions, CSRF, ownership, roles | `app/auth_service.py`, `deps.py`, `google.py`, `docs/GOOGLE_AUTH_SETUP.md`, `docs/API_ACCESS_POLICY.md` | What does the session cookie protect against, and what does the CSRF token protect against? Why is `127.0.0.1` different from `localhost` here? |
| 05 | Document ingestion | Turning PDFs into chunks: extraction, cleaning, chunk size, reproducibility (versioned chunking), quality reports | `app/ingestion/`, `docs/INGESTION.md` | How does chunk size change what retrieval can find? What did the pipeline get wrong (look at the quality report)? |
| 06 | pgvector retrieval | Embeddings, cosine similarity, thresholds, evaluation with Recall@k and MRR, "no evidence" as a valid result | `app/embedding/`, `app/retrieval/`, `app/eval_retrieval.py`, `docs/RETRIEVAL.md` | Why is a similarity threshold needed, and what happens to a good question that scores just below it? |
| 07 | Answers with citations | Prompting with untrusted evidence, structured output, citation validation, quote verification, safety checks, idempotency | `app/llm/`, `app/answers/`, `docs/LLM.md`, `tests/test_answers_api.py` | A quote can be verified and the claim still be wrong. How would you check a claim, and what can software not check? |
| 08 | LangGraph orchestration | Making a pipeline an explicit, typed workflow; deterministic routing; no model call when none is needed; a statistics-only trace | `app/graph/`, `docs/ORCHESTRATION.md`, `docs/orchestration.mmd` | Which decisions should be made by code and which by the model? What are the costs of letting the model decide the route? |
| 09 | Observability and audit | Append-only audit log, correlation ids, privacy by construction (allowed metadata keys), fail-open logging | `app/audit/`, `docs/OBSERVABILITY.md`, the Activity Timeline | What is safe to log about a question, and what is not? How do you debug a failed answer without reading the question? |
| 10 | Integration, diagnostics, evaluation | End-to-end tests with fakes, secret hygiene, reproducible setup, comparing modes honestly | `tests/test_integration_e2e.py`, `test_security_hygiene.py`, `app/diagnostics/`, `app/eval_system.py`, `docs/EVALUATION_REPORT.md`, `docs/SETUP.md` | Which claims does the evaluation support and which does it not (sample size, keyword labels, one small model)? |

## Cross-cutting themes

* **Never invent.** Missing evidence is an answer (the fixed no-evidence message, no model call). Compare the RAG and General
  Knowledge answers to the same question in the demo.
* **Separate who said what.** Patient facts, research findings, model interpretation and general knowledge are different section
  kinds; citations are only allowed on research findings.
* **Untrusted data.** Chunk text, chat text and model output never act as instructions. Try the flagged "possible injection"
  chunk in the tests (`answers_corpus` fixture).
* **Small models are unreliable in specific ways.** Look at the reliability table in the evaluation report: first-try JSON,
  repair attempts, failures. Ask what a user would experience, and what an honest interface does about it.
* **What tests can and cannot show.** Automated tests prove the software around a model; they cannot rate an answer. See
  `docs/KNOWN_LIMITATIONS.md` and the manual-observations table.
* **What was left out on purpose.** E-mail summaries (Gmail) were not implemented; discuss why an optional feature that sends
  personal data outside the system needs explicit consent and more care than the rest.

## Exercises (each 15-30 minutes)

1. Ask the same question in the three modes and write down what differs (sections, citations, evidence, waiting time).
2. Find a question the system should refuse (dose, diagnosis, another patient, a crisis statement) and follow it through the
   timeline: which node stopped it, and was the model called?
3. Open the audit trace of an answer by its correlation id (`docs/OBSERVABILITY.md`) and describe in words what happened.
4. Pick three answers from the live evaluation and fill in the manual-observations table; compare your ratings with a
   classmate's and discuss where you disagree.
5. Read `docs/PROPOSALS.md` and argue for or against one of the two proposals.
