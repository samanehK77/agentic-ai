# Setup guide: from a clean Windows machine to the classroom demo

MindEvidence Lab is an **educational prototype with synthetic data**. This guide gets it running on one Windows machine in
development mode (plain HTTP, everything on `localhost`). It is not a production deployment guide, and nothing in the
project is clinically validated.

Time needed: about 30-45 minutes plus downloads (Python packages, the embedding model of about 91 MB, the PostgreSQL image,
and your Ollama model). Gmail/e-mail reporting from the original spec was deliberately **not implemented**; there is nothing
to set up for it.

Commands are PowerShell, run from the project folder `Addiction` unless a step says otherwise. Run them one at a time.

## 1. Prerequisites

| Tool | Why | Check |
|------|-----|-------|
| Git | clone the repository | `git --version` |
| Python 3.12 or 3.13 (developed and tested with 3.13) | backend, tests, scripts | `python --version` |
| Docker Desktop (running) | PostgreSQL with pgvector (and the optional all-in-container profile) | `docker compose version` |
| Ollama + a model | the language model runs on your machine, nothing is sent out | `ollama list` |
| A Google account and a Google OAuth client | sign-in (see `docs/GOOGLE_AUTH_SETUP.md`) | Google Cloud Console |
| The five research PDFs | the corpus (copyrighted; **not in the repository**) | see step 6 |

**Ollama model.** Development used a model named `qwen3.5-16k` (9.7B parameters, Q4_K_M, 16384-token context; you can see
these facts with `python -m app.diagnostics`). Any chat model works if you set `LLM_MODEL`, but **the answer quality,
reliability and waiting times described in the documents were measured with that one small model only**. The context must be
at least `LLM_CONTEXT_TOKEN_BUDGET + LLM_MAX_OUTPUT_TOKENS` (about 7500 tokens by default), otherwise prompts are silently
truncated; `python -m app.diagnostics` warns about this. To create a model with a larger context in Ollama, put
`PARAMETER num_ctx 16384` in a Modelfile (`FROM` your base model) and run `ollama create <name> -f Modelfile`.

**Google OAuth client.** Follow `docs/GOOGLE_AUTH_SETUP.md`: type *Web application*, authorized JavaScript origin
`http://localhost:8000`, authorized redirect URI `http://localhost:8001/api/auth/google/callback`, and add your own Google account
(and a second one for the isolation test) as **Test users**. Always use the host name `localhost`, never `127.0.0.1`.

## 2. Clone and create the virtual environment

```powershell
git clone https://github.com/samanehK77/agentic-ai.git
cd agentic-ai\Addiction
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation and call
`.\.venv\Scripts\python.exe` explicitly (the helper script `scripts\dev.ps1` does this for you).

**Embedding packages (separate file, large).** Needed to embed the documents, to search, and to download the tokenizer that
ingestion uses. The API and the test suite start and pass without them (search then answers 503).

```powershell
pip install -r requirements-embeddings.txt
python -m app.retrieval.download_model
```

On Windows the torch wheel from PyPI is the CPU build (about 130 MB). The download step fetches about 91 MB once, verifies the
weights against a pinned checksum, and is the only step that needs the network for the model files.

## 3. Create `.env` from `.env.example`

```powershell
cd ..
Copy-Item .env.example .env
```

Open `.env` in an editor and fill in **your own** values. The file is git-ignored; never commit it and never paste its content
into chat, code or issues. `.env.example` lists the names only.

| Variable | Required? | What it does |
|----------|-----------|--------------|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | required | database account and name (you choose them; Docker creates the database with them) |
| `POSTGRES_PORT` | optional (5432) | host port of the database container (published on 127.0.0.1 only) |
| `DATABASE_URL` | optional | full URL instead of the three variables above; leave empty normally |
| `APP_ENV` | required | must be `development`; the API refuses to start otherwise |
| `SESSION_SECRET` | required | at least 32 random characters; signs the short-lived login-state cookie |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | required for sign-in | from your OAuth client (the secret is shown in the console only once) |
| `GOOGLE_REDIRECT_URI` | required for sign-in | `http://localhost:8001/api/auth/google/callback`, exactly as registered at Google |
| `FRONTEND_URL` | optional (`http://localhost:8000`) | where the API redirects after sign-in |
| `CORS_ORIGINS` | optional (`http://localhost:8000`) | comma-separated allowed browser origins, no wildcard |
| `COOKIE_SECURE` | optional (`false`) | `true` only behind HTTPS (not used in this setup) |
| `ADMIN_EMAILS` | optional | verified e-mails that become administrators at sign-in (admin pages, diagnostics, audit summary) |
| `SESSION_IDLE_MINUTES`, `SESSION_MAX_HOURS` | optional (30, 8) | login session timeouts |
| `LLM_BASE_URL` | required for answers | for Ollama: `http://localhost:11434/v1` (`DEEPSEEK_BASE_URL` also works; `LLM_*` wins) |
| `LLM_MODEL` | required for answers | the Ollama model name, for example `qwen3.5-16k` (`DEEPSEEK_MODEL` also works) |
| `LLM_API_KEY` / `DEEPSEEK_API_KEY` | optional | empty for a local model; a key only for the remote provider |
| `LLM_THINKING` | optional (`disabled`) | `omit` sends no thinking parameter (needed for Ollama) |
| `LLM_REASONING_EFFORT` | optional | `none` switches off reasoning on models that support it (Ollama) |
| `LLM_TIMEOUT_SECONDS` | optional (30) | per model call; a small local model needs minutes, try 300 |
| `LLM_MAX_RETRIES` | optional (2) | repeated attempts after a transient failure |
| `LLM_MAX_OUTPUT_TOKENS`, `LLM_TEMPERATURE` | optional (1500, 0.2) | output limit and temperature |
| `LLM_CONTEXT_TOKEN_BUDGET` | optional (6000) | how many tokens of evidence and history go into the prompt |
| `LLM_MAX_CONCURRENCY`, `LLM_QUEUE_WAIT_SECONDS` | optional (1, 120) | a local model serves one question at a time; others wait or get a "busy" answer |
| `GRAPH_TOTAL_TIMEOUT_SECONDS`, `GRAPH_RETRIEVAL_TIMEOUT_SECONDS` | optional (480, 60) | time limits of the whole workflow and of the search step; the total must exceed `LLM_TIMEOUT_SECONDS` |
| `ANSWER_RATE_LIMIT_PER_MINUTE`, `ANSWER_TOP_K` | optional (10, 5) | answers per user per minute, chunks per answer |
| `RETRIEVAL_MIN_SIMILARITY` | optional (0.45) | similarity threshold; `none` switches it off |
| `RETRIEVAL_RATE_LIMIT_PER_MINUTE`, `RETRIEVAL_WARMUP` | optional (30, `false`) | search rate limit; load the embedding model at start |
| `EMBED_MIN_TOKENS`, `EMBED_BATCH_SIZE`, `EMBEDDING_MODEL_PATH` | optional | embedding job settings and a custom model folder |
| `CHUNK_TARGET_TOKENS`, `CHUNK_MAX_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `LOW_TEXT_MIN_CHARS`, `NEEDS_OCR_RATIO`, `HEADER_FOOTER_RATIO`, `MAX_PDF_MB`, `MAX_PDF_PAGES`, `PAPERS_DIR`, `TOKENIZER_PATH` | optional | ingestion settings (defaults are documented in `docs/INGESTION.md`; changing them re-chunks the documents) |

Minimal working set for the demo: the three `POSTGRES_*` values, `APP_ENV=development`, `SESSION_SECRET`, the three `GOOGLE_*`
values, `ADMIN_EMAILS` (your address), `LLM_BASE_URL`, `LLM_MODEL`, `LLM_THINKING=omit`, `LLM_REASONING_EFFORT=none`,
`LLM_TIMEOUT_SECONDS=300`. (The timeout value is a suggestion for a small local model, not a measured requirement.)

## 4. Start PostgreSQL, migrate, seed

```powershell
docker compose up -d
docker compose ps          # the db service should become "healthy"
cd backend
alembic upgrade head       # creates the tables, enables pgvector
python -m db.seed          # the 10 synthetic patients (safe to run again)
```

The data lives in the Docker volume `mindevidence_pgdata`. **Never run `docker compose down -v` on a project whose data you
want to keep** (`-v` deletes the volume). `docker compose down` (without `-v`) is safe.

## 5. Ollama

Start Ollama and make sure the model exists: `ollama list`. The first question after Ollama starts is slow because the model is
loaded into memory; warm it up before a demo (see `docs/DEMO_SCRIPT.md`).

## 6. Place the five PDFs

The PDFs are copyrighted and are **not in the repository** (`data/papers/*.pdf` is git-ignored). Put exactly these files into
`data\papers\` (details in `data/papers/README.md`):

| # | File name |
|---|-----------|
| 1 | `who-mhgap-guideline-2023.pdf` |
| 2 | `Principles of Drug Addiction Treatment A Research Based Guide.pdf` |
| 3 | `who-mhgap-intervention-guide-v2.pdf` |
| 4 | `Psychosocial Interventions for Alcohol Use Disorder A Review of Efficacy Mechanisms and Clinical Implications.pdf` |
| 5 | `Combined pharmacological and psychosocial interventions for alcohol use disorder (Review).pdf` |

Files with other names are reported as "unregistered" and ignored.

## 7. Ingest and embed

```powershell
cd backend
python -m app.ingestion --dry-run      # preview, writes nothing
python -m app.ingestion                # extracts, cleans and chunks the PDFs (about 2,600 chunks)
python -m app.embedding                # embeds the eligible chunks (CPU, several minutes the first time)
python -m app.diagnostics              # everything should be OK
```

Both jobs are idempotent: running them again only does missing work. After changing a chunking or embedding setting, ingestion
or `python -m app.embedding --force` redo it.

## 8. Start the API and the frontend

Two terminals (or `.\scripts\dev.ps1 api` and `.\scripts\dev.ps1 web`):

```powershell
# terminal A, from backend/ with the virtual environment active
uvicorn app.main:app --host localhost --port 8001
# terminal B
cd frontend
python serve.py
```

Open **http://localhost:8000** (not 127.0.0.1). Do not use `--reload` on Windows: a stale worker can keep serving old code.
Check `http://localhost:8001/api/health` and `http://localhost:8001/docs` (interactive API documentation, development only).

## 9. Sign in and try it

Click "Sign in with Google" with one of your **test users**. Select patient P-001, choose a mode (General Knowledge, RAG or
Both) and ask a question. The Activity timeline shows what happened; administrators (`ADMIN_EMAILS`) also see an "Admin" link.
`http://localhost:8000/?source=mock` shows the interface with invented demo data and no sign-in.

## 10. Run the tests

```powershell
.\scripts\dev.ps1 test           # or: cd backend; pytest -q
```

The suite needs PostgreSQL (it creates its own throw-away `<POSTGRES_DB>_test` databases) and no model, no network, no torch.
Tests marked `live` (real local model, real embedder, real index) are **skipped by default**; run them only on purpose:
`$env:MINDEVIDENCE_LIVE_TESTS = "1"; pytest -q -m live` (they make real model calls).

## 11. Optional: everything in containers

The default workflow keeps the API and the frontend on your machine. An **opt-in** Compose profile runs them in containers too:

```powershell
docker compose --profile app up -d --build
docker compose --profile app run --rm api alembic upgrade head
```

* The image is **lightweight by default** (no torch): the API starts, but search and RAG answers return 503 because embedding a
  query needs torch. Build the heavy image with `$env:WITH_EMBEDDINGS = "true"` before `docker compose ... --build` (CPU torch;
  several hundred MB more).
* `.env`, the PDFs and the model files are never copied into the image: `.env` is passed at run time (`env_file`), `data/` and
  `backend/models/` are mounted.
* The API reaches Ollama on your computer through `host.docker.internal` (`LLM_BASE_URL` is set accordingly).
* All published ports are bound to `127.0.0.1`; the frontend stays on 8000 and the API on 8001, so Google sign-in and CORS
  still use `localhost`. (`API_PORT`, `WEB_PORT`, `POSTGRES_PORT` and `CONTAINER_LLM_BASE_URL` exist only to run a second, separate
  instance, for example a clean-room check; the frontend's `js/config.js` and the Google redirect stay on 8001, so use the defaults for real use.)

## 12. Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| Sign-in loops or "state invalid" | you opened `127.0.0.1` somewhere: use `http://localhost:8000` and `localhost` in `GOOGLE_REDIRECT_URI` and `FRONTEND_URL` |
| Google says "access blocked" | your account is not in the OAuth client's **Test users** |
| API refuses to start | `APP_ENV` is not `development`, `SESSION_SECRET` is shorter than 32 characters, or `GRAPH_TOTAL_TIMEOUT_SECONDS` is not larger than `LLM_TIMEOUT_SECONDS` |
| `database` check fails | Docker Desktop is not running, or `docker compose up -d` was not run, or `POSTGRES_*` do not match the container's first start |
| `migrations` check fails | run `alembic upgrade head` from `backend/` |
| Search and RAG answers return 503 `retrieval_unavailable` | embedding packages or model files missing: step 2 (second part) and `python -m app.diagnostics` |
| `index_incompatible` | the stored embeddings come from another model setting: `python -m app.embedding --force` |
| Answers fail with `llm_unavailable` / `llm_timeout` | Ollama is not running, the model name is wrong, or the model is slow: check `ollama list`, raise `LLM_TIMEOUT_SECONDS`; the first call after a start loads the model (slow) |
| "The model is busy" (503 with a retry hint) | a local model serves one question at a time; wait and try again |
| `diagnostics` warns about the context length | the model's context is smaller than `LLM_CONTEXT_TOKEN_BUDGET + LLM_MAX_OUTPUT_TOKENS`: raise `num_ctx` in the Modelfile or lower the budget |
| `llm_bad_output` (502) | the model returned invalid JSON even after one repair attempt; small local models do this sometimes: ask again |
| Symbolic link test is skipped | Windows needs extra permission (Developer Mode) to create symlinks; the check itself is in the code, only that test is skipped |
| Hugging Face prints symlink or cache warnings while downloading the model | harmless on Windows; the files are copied instead |
| Old behaviour after code changes | a stale server process: stop all `uvicorn` processes and start the API again without `--reload` |
| PowerShell blocks scripts | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

`python -m app.diagnostics` checks most of the above and prints a plain-language hint for each problem. It never prints secrets
and does not call the model (`--deep` makes one tiny model call; use it only on purpose).

## Verification status (clean-room check, 2026-10-30)

The steps above were followed in a fresh clone in a temporary folder, with a separate Compose project, volume and ports and no
`.env` (the same values came from process environment variables), on the development machine (Windows 11, Docker Desktop,
Python 3.13, Ollama with `qwen3.5-16k`):

| Step | Result |
|------|--------|
| clone, new virtual environment, `pip install -r requirements.txt` (about 1 min) and `requirements-embeddings.txt` (about 1 min, CPU torch 2.15) | worked |
| `docker compose up -d db` on another port and volume, `alembic upgrade head`, `python -m db.seed` | worked |
| ingestion (about 6 s, 2,579 chunks) and embedding (about 25 s, 2,002 chunks), identical counts to the original machine | worked |
| `python -m app.diagnostics` | all OK |
| full test suite in the clone | 1,173 passed, 2 skipped (symlink test, live test) |
| API from the clone (`uvicorn`), `/api/health`, `/docs` | worked |
| container profile: image build (about 4 min, image about 0.9 GB, no torch), API and web healthy, container to database, container to Ollama through `host.docker.internal` (admin diagnostics showed the model and its 16384 context) | worked |

**Not verified:** the real Google sign-in round trip (needs your OAuth client and test users); `python -m app.retrieval.download_model`
(the clean room copied the model files instead of downloading them); a heavy image build with `WITH_EMBEDDINGS=true`; the frontend
talking to an API on other ports (`frontend/js/config.js` is fixed to `http://localhost:8001`, so the clean room checked the static
server and the API separately). Findings that changed the docs: the compose profile needs a real `.env` file (`env_file` is
required), the image is larger than first estimated, and the model files must sit in `backend/models/all-MiniLM-L6-v2/` (not directly
in `backend/models/`).

## What this guide cannot guarantee

* The real Google round trip depends on **your** OAuth client and test users; automated tests replace Google with a fake.
* Waiting times and answer quality depend on your hardware and model.
* The project is a development setup: plain HTTP, no production hardening, no clinical validation.
