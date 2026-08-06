# Base ERP — Phase 1 (Core/Platform)

A customizable, multi-tenant base ERP. This is **Phase 1 only**: the
Core/Platform layer (Organizations, Users, Roles/Permissions, Audit Log,
Notifications, Custom Fields) plus working signup/login. The 10 business
modules (CRM, Sales, Procurement, Inventory, Finance, HR, Projects,
Documents, Reports, Dashboard) build on top of this in later phases.

See `MANUAL.md` for the full build log, pipeline explanation, deployment
steps, and troubleshooting guide — read that before deploying anywhere.

## Quickstart (local development)

### Option A — Docker (recommended, fewer moving parts)

```bash
docker-compose up --build
```
- Backend: http://localhost:8000/docs
- You still need to run the frontend separately (see below) — Compose only
  runs Postgres + backend in this phase.

### Option B — Manual (no Docker)

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Make sure Postgres is running locally and matches the DATABASE_URL in .env
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

## Project structure

```
backend/
  app/
    core/        - config, database connection, security (JWT/password hashing)
    models/      - SQLAlchemy tables (one file per entity)
    schemas/     - Pydantic request/response shapes
    api/routes/  - actual endpoints
    main.py      - app entrypoint, wires everything together
frontend/
  app/           - Next.js pages (App Router)
  lib/api.ts     - the ONLY place that talks to the backend
```
