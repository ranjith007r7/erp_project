# ERP Build Manual — Phase 1 (Core/Platform)

This is the living document for the whole build. Every phase we complete gets
appended here — by the end, this is your single reference for "how did we
build this, how do the pieces connect, and how do I fix it when it breaks."

---

## PART 1 — What We Built in Phase 1

The Core/Platform layer: the foundation every one of the 10 business modules
will sit on top of.

| Piece | What it does |
|---|---|
| `Organization` model | One row per client company (tenant) |
| `User` model | Login accounts, always tied to one organization |
| `Role` + `Permission` models | Per-organization roles (Admin, etc.) and what each role can do |
| `AuditLog` model | Placeholder for "who changed what" — wired in fully once a module needs it |
| `Notification` model | Placeholder for in-app alerts — same as above |
| `CustomField` model | The customization engine — lets a client add their own fields later without new code |
| Signup endpoint | Creates a new Organization + its first Admin user + a default Admin role with full permissions |
| Login endpoint | Checks email/password, returns a JWT "wristband" |
| `/me` endpoint | Proves the JWT works — returns the logged-in user's info |
| Next.js frontend | Home, Signup, Login, and a Dashboard page that calls `/me` and shows placeholder tiles for the 9 remaining modules |

**I tested every part of this myself before handing it to you** — ran a real PostgreSQL database, started the actual backend, and hit every endpoint with real requests (signup → login → protected route), then built and ran the actual frontend against it. Two real bugs got caught and fixed in that process (details in the Troubleshooting section — they're worth reading even though they're already fixed, because you'll recognize them instantly if they ever resurface in a later phase).

---

## PART 2 — How the Pipeline Connects (Local Development)

```
Your browser (localhost:3000)
        │
        │  clicks "Create Organization", fills form, submits
        ▼
Next.js frontend (lib/api.ts → apiRequest)
        │
        │  POST http://localhost:8000/api/auth/signup  (JSON body)
        ▼
FastAPI backend (app/api/routes/auth.py)
        │
        │  validates input shape (app/schemas/auth.py)
        │  hashes the password (app/core/security.py)
        │  creates Organization + Role + Permissions + User rows
        ▼
PostgreSQL (via SQLAlchemy session, app/core/database.py)
        │
        │  rows saved, IDs generated
        ▼
Backend creates a JWT token (app/core/security.py) and sends it back
        │
        ▼
Frontend stores the token in localStorage (lib/api.ts) and redirects to /dashboard
        │
        │  GET http://localhost:8000/api/auth/me   (Authorization: Bearer <token>)
        ▼
Backend decodes the JWT (app/api/deps.py), looks up the user, returns their info
        │
        ▼
Dashboard page renders it
```

Every future module (CRM, Sales, etc.) will follow this **exact same shape** —
a Next.js page, calling a FastAPI route, checking the JWT via the same
`get_current_user` dependency, reading/writing PostgreSQL through SQLAlchemy
models. Once this pattern feels familiar, every subsequent module is just
"the same thing again with different fields."

---

## PART 3 — Deploying Online, for Free (No Card, No Surprise Bills)

**Important — I revised this plan from an earlier conversation** after
checking current terms directly, because a couple of things I'd assumed
had either changed or were riskier than I'd realized:

- Render's free tier **does not support always-on background workers**, and its
  **free PostgreSQL databases are deleted after 30 days** — a real data-loss risk.
- Because of that, **we are not using Celery/Redis at all in this phase.**
  Nothing in Phase 1 needs a background worker. When a later module genuinely
  needs one (e.g., a scheduled payroll run), we'll use free scheduled **GitHub
  Actions** hitting a secured API endpoint instead of paying for an always-on worker.
- **Vercel's free "Hobby" plan is officially for non-commercial use.** It's fine
  while you're building and demoing to prospective clients. The moment this
  ERP has a real, paying client on it, that specific deployment should move to
  Vercel Pro (~$20/month) or a commercially-fine free alternative like
  Cloudflare Pages — a decision for later, not now.

### Step 1 — Push the code to GitHub

```bash
cd erp-base-project
git init
git add .
git commit -m "Phase 1: Core/Platform layer"
```
Create an empty repository on GitHub.com, then follow its "push an existing
repository from the command line" instructions.

### Step 2 — Database: Supabase (free)

1. Go to supabase.com → New Project (no credit card needed).
2. Once created, go to **Project Settings → Database → Connection String**
   and copy the URI (starts with `postgresql://postgres...`).
3. Keep this safe — you'll paste it into Render as `DATABASE_URL` in Step 3.
4. **Know this in advance:** a free Supabase project pauses itself after 7
   days with no activity. Your data is **not deleted** — you just click
   "Restore" in the dashboard to wake it back up. This is an inconvenience,
   not a cost risk.

### Step 3 — Backend: Render (free)

1. Go to render.com → New → Web Service → connect your GitHub repo.
2. Root directory: `backend`
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Instance type: **Free**
6. Add environment variables (Render dashboard → Environment):
   - `DATABASE_URL` → the Supabase connection string from Step 2
   - `JWT_SECRET_KEY` → generate a long random string (e.g. run `openssl rand -hex 32` locally and paste the result — never reuse the placeholder from `.env.example`)
   - `ALLOWED_ORIGINS` → leave as `http://localhost:3000` for now, we'll update it in Step 5
   - `PYTHON_VERSION` → `3.12.10` — **do not skip this.** Render's default Python version changes over time (it's tied to when you created the service, not when we wrote this code), and a too-new default can fail to install `pydantic` before a compatible pre-built package exists for it. This env var is the officially supported way to pin it — a `runtime.txt` file does **not** work on Render (that's a Heroku convention); we've also committed a `backend/.python-version` file as a second safety net, but the environment variable takes priority and is the one to trust.
7. Deploy. First deploy takes a few minutes. Once live, visit
   `https://your-service-name.onrender.com/docs` to confirm it's up.
8. **Know this in advance:** Render's free web services "sleep" after 15
   minutes of no traffic. The next visitor waits ~30-60 seconds for it to
   wake up. This is normal — not a bug, not a cost.

### Step 4 — Frontend: Vercel (free)

1. Go to vercel.com → Add New → Project → import your GitHub repo.
2. Root directory: `frontend`
3. Add environment variable:
   - `NEXT_PUBLIC_API_URL` → your Render URL from Step 3 (e.g. `https://your-service-name.onrender.com`)
4. Deploy. Vercel gives you a URL like `https://your-project.vercel.app`.

### Step 5 — Connect the last wire: CORS

Go back to Render → Environment → update `ALLOWED_ORIGINS` to your real
Vercel URL from Step 4 (e.g. `https://your-project.vercel.app`), then
manually redeploy the backend. **This step is why a fresh deployment often
"can't reach the backend" on the first try** — the backend is still only
trusting `localhost:3000` until you do this.

### Step 6 — CI/CD (already free, already set up)

The `.github/workflows/ci.yml` file we already added runs automatically on
every `git push` — it installs both apps and confirms they build cleanly,
catching broken code **before** you ever manually redeploy. Nothing further
to configure; GitHub Actions minutes are free for this usage level.

---

## PART 4 — Troubleshooting & Error Codes

### Errors I actually hit while building this (and already fixed for you)

**`ValueError: email-validator is not installed`**
Cause: Pydantic's `EmailStr` type needs a separate package that isn't pulled
in automatically. Fix: added `email-validator` to `requirements.txt`. If you
ever add a new field using `EmailStr` in a fresh module and see this again,
you already know exactly why.

**`ValueError: password cannot be longer than 72 bytes` (or similar bcrypt errors)**
Cause: a known incompatibility between `passlib` and newer `bcrypt` releases.
Fix: pinned `bcrypt==4.0.1` alongside `passlib` in `requirements.txt`. If a
future `pip install --upgrade` ever changes this version and it resurfaces,
re-pin it the same way.

### Errors you're likely to hit yourself, and what they mean

| Error | What it actually means | Fix |
|---|---|---|
| `curl: (7) Failed to connect` / browser says "can't reach this page" | The backend or database isn't running | Locally: check `docker-compose up` or `uvicorn` is actually running. On Render: check the service didn't crash — read its logs tab. |
| CORS error in browser console ("blocked by CORS policy") | The frontend's URL isn't in the backend's `ALLOWED_ORIGINS` | Update `ALLOWED_ORIGINS` on Render to match your exact frontend URL (Part 3, Step 5), including `https://` and no trailing slash. |
| `401 Unauthorized` on a page that should be logged in | The JWT is missing, expired, or malformed | Log out and log back in. If it keeps happening, check the browser's localStorage actually has a token (`localStorage.getItem('erp_token')` in devtools console). |
| `422 Unprocessable Entity` | Your request body doesn't match what the backend expects (e.g., a field is too short, or missing) | Read the JSON error body — FastAPI tells you exactly which field failed and why. This is usually a genuinely helpful error, not a bug. |
| `relation "users" does not exist` (or similar "table doesn't exist") | The database tables were never created | Locally, this self-heals on backend startup (`Base.metadata.create_all`). On a fresh Supabase database, just restart the Render service once so startup runs again. |
| Render build fails with `pydantic-core` / `maturin` / `Build failed` errors, mentioning Python 3.14 | Render is using a newer default Python version than our dependencies have pre-built packages for yet | Set the `PYTHON_VERSION` environment variable to `3.12.10` in Render's dashboard (Environment tab), then redeploy with "Clear build cache & deploy." Do **not** use a `runtime.txt` file — Render doesn't read it; it's a Heroku convention. Render supports only `PYTHON_VERSION` (env var) or a `.python-version` file, in that priority order. |
| Render service shows "Deploy failed" | Usually a missing dependency or wrong start command | Check the deploy logs tab on Render — it shows the exact Python traceback, same as running it locally. |
| Vercel build fails with a TypeScript error | Same as `npm run build` failing locally | Run `npm run build` locally first before pushing — that's exactly what Vercel runs, so if it passes locally it will almost certainly pass there too. |
| Everything "was working yesterday" and now nothing responds locally | Totally normal — Postgres (and any background server) doesn't survive a machine/container restart unless you explicitly restart it | Restart Postgres, then restart the backend and frontend, in that order. |

### The golden debugging habit

Whenever something breaks, check things in this order — it matches the
pipeline diagram in Part 2 and will find the problem faster than guessing:
1. Is the database running?
2. Is the backend running, and does its logs/terminal show an error?
3. Does hitting the backend URL directly (e.g. `/health` or `/docs`) work?
4. Only then check the frontend — most "frontend bugs" are actually one of
   the three steps above.

---

## PART 5 — Phase 2: CRM + Sales + Live Dashboard

### What we added

| Piece | What it does |
|---|---|
| `Account`, `Contact`, `Lead`, `Opportunity` models | The CRM funnel: a stranger (Lead) becomes a real company/person (Account/Contact) with an active deal (Opportunity) |
| `Product`, `Customer`, `Quotation`(+items), `SalesOrder`(+items), `Invoice` models | The Sales quote-to-cash chain |
| `POST /api/crm/leads/{id}/convert` | The key CRM action — turns a Lead into an Account + Contact + Opportunity in one transaction |
| `POST /api/sales/quotations/{id}/accept` | Turns an accepted Quotation into a real Sales Order, copying line items across |
| `POST /api/sales/orders/{id}/invoice` | Generates an Invoice from a fulfilled Sales Order |
| `GET /api/dashboard/summary` | Live counts (leads, open opportunities, quotations, orders, unpaid invoices) — powers the Dashboard tiles |
| `get_org_id` dependency (added to `app/api/deps.py`) | Every CRM/Sales route uses this to guarantee one organization's data is never visible to another — the multi-tenancy rule enforced in code |
| `/crm` and `/sales` frontend pages | Full working UI: add leads, convert them, create quotations, accept them into orders, generate invoices — all wired to the real backend |

**A deliberate scope decision:** Sales Order line items reference a lightweight `Product` table (just `name` + `unit_price`) rather than waiting for the full Inventory module. When Inventory is built later, we'll *extend* this same table (add SKU, stock levels, warehouses) rather than create a second, competing table — so nothing in Sales needs to be rewritten.

### Bugs caught by testing before you ever saw this code

**`ResponseValidationError: Input should be a valid string` on every list/create endpoint**
Cause: SQLAlchemy returns UUID objects for id/foreign-key columns, but the response schemas had them typed as plain `str`. Pydantic v2 validates strictly when serializing straight from an ORM object under `from_attributes=True`, and a UUID object fails `str` validation even though it looks like a string. Fix: changed every id/`*_id` field in `schemas/crm.py` and `schemas/sales.py` from `str` to `UUID` — Pydantic still outputs it as a plain string in the actual JSON response, so nothing about the API contract changed, only the internal validation.

**Field name mismatch: `payload.value` vs `payload.opportunity_value`**
A small but real mistake — the `ConvertLeadRequest` schema and the route handler used different field names for the same thing. Caught immediately by actually running the convert-lead flow, not by reading the code. This is exactly why we test end-to-end instead of trusting code that "looks right."

### Full lifecycle test (this is what "working" means here)

We verified the complete chain end-to-end, with real HTTP requests:

```
signup → create Lead → convert Lead
    → creates Account + Contact + Opportunity automatically
→ create Product → create Customer (linked to the new Account)
→ create Quotation (2 × ₹25,000 = ₹50,000 total, calculated by the backend)
→ accept Quotation → creates Sales Order (items + total copied across)
→ generate Invoice from the Sales Order (₹50,000, carried through correctly)
→ dashboard summary correctly shows: 1 lead, 1 open opportunity,
  1 quotation, 1 sales order, 1 unpaid invoice
```

Every number matched expectations at every step — the ₹50,000 total from the Quotation flowed untouched through the Order and into the Invoice, which is the entire point of an ERP (Part 2 of the CRM/Sales story from the fundamentals doc, made real).

### Deploying this update

Nothing about the deployment *process* changes from Part 3 — same Render service, same Vercel project, same Supabase database. Just:
```bash
git add .
git commit -m "Phase 2: CRM + Sales + live dashboard"
git push
```
Render and Vercel both auto-redeploy on push (that's what we set up in Phase 1). The new tables get created automatically the moment the backend restarts and hits `Base.metadata.create_all()` — no manual database step needed.

---

## PART 6 — What's Next

Phase 3 will build **Finance & Accounting**, wiring it to the Sales module we
just built — every Invoice generated in Sales should create a Journal Entry
here, which is the cross-module "hand-off" that makes this an actual ERP
rather than separate apps. **Inventory** will likely come alongside it, since
Sales Orders should start reducing real stock levels once it exists. This
section keeps growing with each phase — nothing above gets deleted, only
added to.
