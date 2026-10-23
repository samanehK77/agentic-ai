# Backend: database (Batch 02)

PostgreSQL schema, migrations, seed data and tests for 10 **synthetic** patient cases.
No API yet (Batch 03). See `docs/DATA_DICTIONARY.md` for every table and field.

## Layout

```
Addiction/
  docker-compose.yml          PostgreSQL (pgvector image)
  .env.example                variable names only; copy to .env
  backend/
    requirements.txt
    alembic.ini, alembic/     migrations
    db/config.py              builds the database URL from environment variables
    db/models.py              SQLAlchemy 2.x models
    db/seed.py                idempotent seed (python -m db.seed)
    db/seed_data/P-001.json ... P-010.json   readable seed content, one file per patient
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
```

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

### 6. Run the tests

```powershell
pytest
```

Tests use a separate database named `<POSTGRES_DB>_test` that they create and drop themselves; your real data is never touched.

### 7. Look at the data (optional)

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
- To undo the migration: `alembic downgrade base`.
- The seed content is fictional. Edit the JSON files in `db/seed_data/` and run `python -m db.seed` again to apply changes; `pytest` re-checks timeline consistency.
