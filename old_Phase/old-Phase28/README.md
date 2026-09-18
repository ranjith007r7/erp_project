# Base ERP — Phase 1-4 (Core/Platform + CRM + Sales + Finance + Inventory + Procurement)

A customizable, multi-tenant base ERP. Built in phases — see `MANUAL.md`
for the full build log, pipeline explanation, deployment steps, and
troubleshooting guide. Read that before deploying anywhere.

**Live modules:** Dashboard, CRM, Sales, Finance & Accounting, Inventory,
Procurement. **Still to come:** HR & Payroll, Projects & Tasks, Documents &
Workflow Approvals, Reports & Analytics.

## Quickstart (local development)

### Option A — Docker (recommended, fewer moving parts)

```bash
docker-compose up --build
```
This runs Postgres, applies any pending Alembic migrations, and starts the
backend automatically. Backend: http://localhost:8000/docs
You still need to run the frontend separately (see below).

### Option B — Manual (no Docker)

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Make sure Postgres is running locally and matches the DATABASE_URL in .env

alembic upgrade head          # creates/updates the database schema
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Then open http://localhost:3000, click **Create Organization**, and you're in.

## Changing the database schema (important — read this before editing a model)

As of this phase, **the database schema is never created or changed
automatically by the app anymore.** It's managed entirely by Alembic. If
you add or change a model:

```bash
cd backend
alembic revision --autogenerate -m "describe your change here"
# review the generated file in alembic/versions/ before applying it -
# autogenerate is very good, not perfect
alembic upgrade head
```

Then commit the new migration file in `alembic/versions/` along with your
model change — the migration IS part of the code change, not a separate step.

## Project structure

```
backend/
  alembic/       - migration scripts (see above) - this is what creates/changes the database now
  app/
    core/        - config, database connection, security (JWT/password hashing)
    models/      - SQLAlchemy tables (one file per entity)
    schemas/     - Pydantic request/response shapes
    api/routes/  - actual endpoints
    services/    - shared cross-module logic (accounting.py, inventory.py)
    main.py      - app entrypoint, wires everything together
frontend/
  app/           - Next.js pages (App Router)
  lib/api.ts     - the ONLY place that talks to the backend
```
