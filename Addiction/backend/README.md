# Backend: database, API and Google sign-in (Batches 02-04)

PostgreSQL schema, migrations, seed data, a FastAPI API and tests for 10 **synthetic** patient cases.
See `docs/DATA_DICTIONARY.md` (tables), `docs/API.md` (endpoints) and `docs/API_ACCESS_POLICY.md`
(**the API is development-only, plain HTTP, and not production-ready**) and `docs/GOOGLE_AUTH_SETUP.md`.

## Layout

```
Addiction/
  docker-compose.yml          PostgreSQL (pgvector image)
  .env.example                variable names only; copy to .env
  backend/
    requirements.txt
    alembic.ini, alembic/     migrations
    app/                      FastAPI app: main, config, deps, errors, middleware, services,
                              routers/, schemas/, repositories/ (all SQL)
    db/config.py              builds the database URL from environment variables
    db/models.py              SQLAlchemy 2.x models
    db/seed.py                idempotent seed (python -m db.seed)
    db/seed_data/P-001.json ... P-010.json   readable seed content, one file per patient
    db/seed_data/papers.json  research paper metadata (5 papers)
    db/queries/*.sql          patient profile and chronological history
    tests/                    pytest suite
```

## Run it on Windows (PowerShell)

Run the commands one at a time. Docker Desktop must be running.

### 1. Create your `.env` (from the project folder `Addiction`)

```powershell
Copy-Item .env.example .env
```

Open `.env` in an editor and fill in **your own** values (the file is git-ignored, never commit it):

```
POSTGRES_USER=mindevidence
POSTGRES_PASSWORD=<choose a password>
POSTGRES_DB=mindevidence
POSTGRES_PORT=5432
APP_ENV=development
SESSION_SECRET=<at least 32 random characters>
```

`APP_ENV=development` and a `SESSION_SECRET` of at least 32 characters are required: the API refuses to start without them.
The Google sign-in variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, ...) are explained in `docs/GOOGLE_AUTH_SETUP.md`; without them the API starts but sign-in answers 503.
Optionally set `CORS_ORIGINS` (comma-separated, no wildcard); the default allows only `http://localhost:8000`.

Leave `DATABASE_URL` empty unless you want to override the settings above.

### 2. Start the database

```powershell
docker compose up -d
docker compose ps
```

Wait until the service shows `healthy`. The first start downloads the `pgvector/pgvector:pg16` image.

### 3. Create a virtual environment and install packages

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### 4. Create the tables (migrations)

```powershell
alembic upgrade head
```

### 5. Seed the 10 patients

```powershell
python -m db.seed
```

Running it again is safe: rows are updated in place, never duplicated.

### 6. Start the API

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Open <http://localhost:8001/docs> for the interactive documentation. Keep `--host 127.0.0.1`: this is a local plain-HTTP
setup and must not be reachable from other machines. Use the host name `localhost` in the browser (cookies are host-scoped). The frontend (port 8000) shows the
patients from this API; see `docs/API.md` for example requests.

### 7. Run the tests

```powershell
pytest
```

Tests use a separate database named `<POSTGRES_DB>_test` that they create and drop themselves; your real data is never touched.

### 8. Look at the data (optional)

```powershell
docker compose exec db psql -U mindevidence -d mindevidence -c "SELECT patient_id, primary_category, age_at_intake FROM patients ORDER BY patient_id;"
```

Use your own `POSTGRES_USER` and `POSTGRES_DB` if you changed them. The ready-made queries are in `db/queries/` and take the parameter `:patient_id`.

### Reset everything

```powershell
docker compose down -v
```

This deletes the database volume. Start again from step 2.

## Notes
- The database URL uses `127.0.0.1` rather than `localhost`: on Windows `localhost` can resolve to IPv6 and the connection hangs.
- To undo migrations: `alembic downgrade base`. After pulling new migrations run `alembic upgrade head` and `python -m db.seed` again.
- The API port is 8001 because the frontend uses 8000.
- Run `alembic upgrade head` after pulling Batch 04 (migration 0003 adds `users` and `auth_sessions`).
- The seed content is fictional. Edit the JSON files in `db/seed_data/` and run `python -m db.seed` again to apply changes; `pytest` re-checks timeline consistency.
