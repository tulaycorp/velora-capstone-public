# Setup

## Prerequisites

- Node.js 20.x (npm)
- Python 3.11
- PostgreSQL (or a Neon/Supabase Postgres connection)
- Redis (required for background workers and scheduled sync)

## Environment

Copy the examples and fill in real values. Never commit the filled-in files.

```bash
cp .env.local.example .env.local
cp backend/.env.example backend/.env
```

The backend fails fast at startup if `backend/.env` or `.env.local` is missing or still
contains placeholder values. Use Clerk for auth (`VELORA_AUTH_MODE=auto` enables Clerk
verification when `VELORA_CLERK_JWKS_URL` is set).

## Frontend

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:3000/dashboard`.

`next dev` writes to `.next-dev/`; production builds use `.next/`. Do not run multiple
dev servers from the same checkout — they share `.next-dev/`.

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./.venv/bin/alembic upgrade head
./.venv/bin/uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/health`.

## Full Stack

```bash
./run.sh      # macOS / Linux
run.bat       # Windows
```

The launcher starts Next.js, FastAPI, the Dramatiq workers, the scheduler, and a local
Redis/Valkey broker when the configured broker is unreachable and a local Redis server,
Valkey server, or Docker is available.

## Verification

Frontend:

```bash
npm run lint
npm run build
npm run test:e2e   # isolated mock API + Next.js; needs Google Chrome
```

Backend:

```bash
cd backend
./.venv/bin/pytest
```

The default backend suite runs against a temporary SQLite database. Postgres-only locking
and RLS tests are opt-in via `VELORA_POSTGRES_TEST_URL` pointed at an isolated database.

```bash
cd backend
VELORA_POSTGRES_TEST_URL=postgresql+psycopg://user:password@127.0.0.1:5432/velora_test \
  ./.venv/bin/pytest -q tests/test_postgres_sync_job_lifecycle.py
```
