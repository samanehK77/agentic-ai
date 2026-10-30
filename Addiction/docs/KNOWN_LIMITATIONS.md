# Known limitations

An honest list. The project is an **educational prototype with synthetic data**: not production-ready, not clinically validated.
Items are grouped by area; the last sections separate what the automated tests prove from what only a person can judge, and
list what is incomplete or skipped.

## What this is not
* Not a clinical tool: it does not diagnose, prescribe or choose treatments, and nothing here supports clinical use.
* Not production-ready: plain HTTP, development-only settings, no TLS, no hardening review, `/docs` open without sign-in,
  rate limiting only on search and answers, no per-day spending cap (relevant only for a remote provider).
* Synthetic data only: users must not type personal information, and real patient data must never be used.

## Language model and answers
* Safety checks are heuristics (keyword and pattern rules): false positives and misses exist; diagnosis statements in model
  output are not detected (only dosing instructions and treatment directives are withheld).
* A **verified quote** shows that quoted words exist in the cited chunk, not that the claim built on them is supported. The
  system never reports a "hallucination rate".
* The classifier is rule-based and **English-only**; non-English questions fall to the default route. A history-style question
  can be routed to retrieval if it contains research cues (observed in the automated evaluation: `q10-history-triggers` ended as
  "no evidence" in RAG and Both mode because it was searched in the documents).
* Small local models are unreliable in ways the pipeline reports rather than hides: invalid JSON (one repair attempt, then
  `502 llm_bad_output`), invalid section kinds on complex questions, quotes that do not occur in the cited chunk, slow answers
  (about 30-100 s per answer on the development machine). Numbers: `docs/EVALUATION_REPORT.md`; they describe one 9.7B, 4-bit
  model only.
* The model name, size and speed are specific to the development machine; the first call after Ollama starts loads the model.
* Follow-up retrieval is a once-only heuristic; a node timeout cannot kill a running worker thread.

## Retrieval and ingestion
* Exact cosine search over about 2,000 chunks; no reranking, no keyword or hybrid search.
* Chunks are about 220 tokens (at most 250) because the embedding model truncates at 256 word pieces (deviation from the
  spec's 400-700 tokens, see `docs/SPEC.md`). Short table and flowchart fragments from the Intervention Guide still rank high
  for some queries; some Cochrane running-header text survives as short chunks; section titles can be noisy.
* The similarity threshold (0.45) rests on a very small sample; relevance labels in the evaluation are keyword patterns.
* PDF extraction heuristics are imperfect (`docs/INGESTION.md`); scanned pages are not OCR'd.
* The research documents are copyrighted and are not in the repository; students can read the chunk text of their own searches
  (bounded per request), administrators can read all chunks.

## Workflow and concurrency
* One server process only: the idempotency lock, OAuth state memory, rate limiters and the audit failure counter are per process.
* A local model serves one question at a time (`LLM_MAX_CONCURRENCY=1`); further questions wait or get a "busy" answer.

## Audit and observability
* Node events are written when a run ends, not live; a running question shows only as "running".
* The append-only trigger can be dropped by the table owner (a separate database role would be needed); there is no retention
  job; event times come from the server clock.

## Frontend
* The patient detail view makes two requests (profile and history).
* `?state=error` is a front-end demo state, it does not exercise the API's own errors.
* Evidence highlighting, the timeline and the admin page were checked in the browser pane with synthetic data; **a full
  browser session with a real Google login was not exercised by the automated work** (needs the owner's Google account).

## Docker and setup
* The default backend image is lightweight and has **no torch**: the API starts but search and RAG answers return 503 inside it
  until the heavier build (`WITH_EMBEDDINGS=true`) is used. The container reaches Ollama through `host.docker.internal`.
* The image is about 0.9 GB even without torch.
* Verified in a clean-room run (see `PROGRESS.md`): clean clone, new virtual environment, separate database, migrations, seed,
  ingestion, embedding, diagnostics, the full test suite, the API on the host and the container profile. **Not verified:** the
  real Google sign-in round trip (needs your OAuth client), downloading the embedding model with `download_model` (the clean room
  copied the files instead), and a heavy (torch) image build.
* Symbolic-link tests are skipped on Windows without the needed permission.

## Automated test results versus manual observations
* **Automated** (about 1,200 tests plus the scripted evaluation): they prove the software around the model: routing, retrieval
  wiring, citation mapping and quote verification rules, no-evidence and safety paths, authentication, CSRF, isolation, audit
  privacy and secret hygiene. They run offline with a fake Google, a fake embedder and a mock model.
* **Live evaluation** (local model): measures reliability and speed of one small model on 14 questions; tiny sample.
* **Manual observations** (faithfulness and helpfulness ratings): a table for a person to fill in; deliberately **not** part of
  any automated figure. Until it is filled in, no claim about answer quality beyond the live figures is made.

## Incomplete or not implemented
* Gmail / e-mail summaries from the original spec (optional): deliberately not implemented; no e-mail is sent.
* The optional "Auto" answer mode of the spec.
* Constrained JSON output and an evidence-only fallback: proposals only (`docs/PROPOSALS.md`).

## Skipped tests
* `test_ingestion_pipeline.py` symbolic-link test: this Windows user may not create symlinks (the check itself is in the code).
* `test_integration_e2e.py::test_live_*`: skipped unless `MINDEVIDENCE_LIVE_TESTS=1`, because it makes real model calls.
