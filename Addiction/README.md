# MindEvidence Lab

An **educational prototype**: a small research assistant for psychology students who study addiction treatment. Students
explore **10 fictional (synthetic) patient cases** and ask questions that are answered either from general model knowledge, from
a small corpus of research documents with traceable citations, or from both, and they can inspect the evidence, the workflow
and an audit trail for every question.

> **Read this first.** This is a teaching tool built in ten batches as a course project. It uses **synthetic data only**. It
> does **not** diagnose, prescribe or choose treatments. It is **not production-ready** (plain HTTP, development settings, no
> hardening) and has **no clinical validation**; no result in this repository supports any clinical use. Answer quality
> figures describe one small local model on one machine. Optional Gmail summaries from the original spec were deliberately
> **not implemented**: the project sends no e-mail.

## What it does

* Patient explorer and chat with a selected synthetic patient as context.
* Three answer modes: **General Knowledge**, **RAG** (only from retrieved documents) and **Both** (document findings and clearly
  labelled general knowledge kept apart).
* Citations that map to real retrieved chunks, with quote verification; missing evidence is stated, never invented.
* Evidence Inspector, Activity Timeline and an append-only audit log linked by one correlation id per question.
* Google sign-in, per-user sessions, CSRF protection, isolation between users, an admin role.
* Runs against a **local** language model (Ollama); nothing leaves the machine.

## Quick start

Full instructions for a clean Windows machine: **[docs/SETUP.md](docs/SETUP.md)**. In short:

```powershell
docker compose up -d                          # PostgreSQL with pgvector
cd backend; python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-embeddings.txt
python -m app.retrieval.download_model        # embedding model (about 91 MB, once)
cd ..; Copy-Item .env.example .env            # then fill in your own values; never commit .env
.\scripts\dev.ps1 migrate; .\scripts\dev.ps1 seed
# put the five PDFs into data\papers (see docs/SETUP.md), then:
.\scripts\dev.ps1 ingest; .\scripts\dev.ps1 embed; .\scripts\dev.ps1 diagnose
.\scripts\dev.ps1 api       # terminal A: http://localhost:8001
.\scripts\dev.ps1 web       # terminal B: http://localhost:8000
```

Open <http://localhost:8000> (always `localhost`, never `127.0.0.1`). `?source=mock` shows the interface with invented demo data
and needs no sign-in. The classroom demonstration is in **[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)**.

## Documents

| Document | Content |
|----------|---------|
| [docs/SETUP.md](docs/SETUP.md) | clean-machine setup, every environment variable, troubleshooting |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | timed classroom demonstration with checklist and fallbacks |
| [docs/TEACHING_GUIDE.md](docs/TEACHING_GUIDE.md) | what each component demonstrates, with discussion questions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | diagram, data flow of one question, endpoint list |
| [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md) | the three modes compared on the same questions (automated, live, manual) |
| [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | honest list of limits, incomplete features, skipped tests |
| [docs/PROPOSALS.md](docs/PROPOSALS.md) | two ideas that are **not** implemented, with risks |
| [docs/SPEC.md](docs/SPEC.md) | the original specification (with an appended section on deviations) |
| [PROGRESS.md](PROGRESS.md) | batch-by-batch log, decisions and results |
| `docs/API.md`, `API_ACCESS_POLICY.md`, `DATA_DICTIONARY.md`, `LLM.md`, `RETRIEVAL.md`, `INGESTION.md`, `ORCHESTRATION.md`, `OBSERVABILITY.md`, `GOOGLE_AUTH_SETUP.md`, `FRONTEND_INTEGRATION_PLAN.md` | component details |

## Layout

```
Addiction/
  README.md  PROGRESS.md  CLAUDE.md  .env.example  docker-compose.yml  .dockerignore
  scripts/dev.ps1            helper commands (never touches .env)
  frontend/                  vanilla HTML/CSS/ES modules, admin.html, serve.py
  backend/                   FastAPI app (app/), SQLAlchemy models and seed (db/), migrations (alembic/), tests/, eval/, Dockerfile
  data/papers/               the five research PDFs (copyrighted, NOT in the repository)
  docs/                      all documentation
```

## Tests

```powershell
.\scripts\dev.ps1 test          # about 1,200 tests, no model, no network; live tests are skipped unless you enable them
python -m app.diagnostics       # from backend/: health checks without secrets
python -m app.eval_system run   # from backend/: automated comparison of the three modes (scripted model)
```

Automated tests check the software around the model. They say nothing about how good a model's answers are; for that see the
evaluation report and its manual-observations section, and read their limits.

## Data and copyright

The source code is released under the MIT licence (`LICENSE` in the repository root). The licence covers the code and the synthetic patient cases only. Research documents belong to their publishers (WHO, NIDA, Cochrane and others) and are not redistributed here. Patient cases are
fictional. No real person's data may be used with this system.
