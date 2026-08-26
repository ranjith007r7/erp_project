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
4. Start command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` — **not just `uvicorn ...`.** This is the single most important line in this whole setup: it means every future deploy automatically brings the database schema up to date before the server starts, so a new migration can never silently fail to apply the way one did in a real production incident on this project (see MANUAL.md's account of that below). If you're reading this because you already have a service running with just `uvicorn ...` as the Start Command, go fix it in Render's dashboard right now — Settings → Start Command — this is not optional or "whenever convenient."
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
| `column "..." of relation "..." does not exist` | You added a field to a model whose table already existed from an earlier phase. `Base.metadata.create_all()` only creates brand-new tables — it never alters existing ones | Run a manual `ALTER TABLE ... ADD COLUMN ...` matching the new field(s), on both your local database and Supabase. This will keep happening until Alembic migrations are adopted (see Part 8) — it's expected, not a sign something is broken. |
| An organization created in an earlier phase is missing data a newer phase expects (e.g. default accounts, default settings) | "Seed at signup" only runs for *new* signups — it can't retroactively fix organizations that already existed | This is why `get_account()` self-heals (Part 6). When adding a new "default" anything in a future module, prefer self-healing lookups over signup-only seeding, or you'll hit this exact bug again for every existing organization. |
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

## PART 6 — Phase 3: Finance & Accounting

### What we added

| Piece | What it does |
|---|---|
| `ChartOfAccounts`, `JournalEntry`, `JournalLine`, `Payment` models | Real double-entry bookkeeping — every entry's debits equal its credits |
| `app/services/accounting.py` | The one shared place that knows how to post a balanced Journal Entry — both Sales and Finance call into it, rather than each writing their own copy |
| Signup now seeds 3 default accounts | Cash (1000), Accounts Receivable (1100), Sales Revenue (4000) — so Finance isn't empty the moment an organization exists |
| Sales' `generate_invoice` now auto-posts a Journal Entry | Debit Accounts Receivable, Credit Sales Revenue — in the **same database transaction** as the Invoice itself, so they can never go out of sync |
| `POST /api/finance/payments` | Records money received, marks the Invoice paid, and posts a second Journal Entry (Debit Cash, Credit Accounts Receivable) |
| `/finance` frontend page | Chart of Accounts, a live Journal Entries feed showing every debit/credit line, and a "Record Payment" button on unpaid invoices |

**This is the phase where cross-module automation became real, not just planned.** Generating an Invoice in Sales now silently creates correct accounting entries in Finance — nobody re-types anything, exactly the "single source of truth" behavior described in the ERP Fundamentals document.

### Why the accounting logic lives in its own `services/` folder

Sales needs to post to Finance's accounts when an Invoice is created. Finance needs Sales' `Invoice` model when a Payment is recorded. If each route file tried to import directly from the other, we'd risk a circular import (`sales.py` imports `finance.py` which imports `sales.py`...). Putting the shared logic in `app/services/accounting.py` — which only imports from `app.models.finance`, never from routes — sidesteps that entirely. This is a pattern worth reusing: **whenever two modules need to hand off to each other, put the hand-off logic in its own service file, not inside either module's routes.**

### Full lifecycle test (verified end-to-end, including the books balancing)

```
signup → 3 default accounts seeded automatically (Cash, A/R, Sales Revenue)
→ customer + product + quotation (3 × ₹1,000 = ₹3,000) → accept → order
→ generate invoice
    → Journal Entry #1: Dr Accounts Receivable ₹3,000 / Cr Sales Revenue ₹3,000
→ record payment (₹3,000)
    → Journal Entry #2: Dr Cash ₹3,000 / Cr Accounts Receivable ₹3,000
    → invoice status: unpaid → paid
→ attempted a second payment on the same invoice → correctly rejected
  ("This invoice is already fully paid.")
```

Every journal entry balanced (total debits = total credits) at every step, with zero manual bookkeeping — the backend did all of it from the Sales actions alone.

### A real bug found in your own production deployment (and fixed properly, not patched)

After deploying Phase 3, you hit `"Account 1000 not found for this organization"` when clicking Record Payment. **Root cause:** that organization was created during Phase 1/2 testing, *before* `seed_default_accounts()` existed — signup-time seeding has no way to retroactively add accounts to organizations that already existed. This is a well-known category of bug called a **data migration gap**: new code correctly handles new data going forward, but old data was never backfilled.

**Fix:** `get_account()` in `app/services/accounting.py` is now **self-healing** — if a default account is missing when it's actually needed, it's created on the spot instead of failing. This was verified by deliberately reproducing your exact scenario: seeding an org, then deleting all its accounts to simulate a pre-Phase-3 org, then running Invoice generation and Payment recording against it. Both self-healed correctly with zero manual database work, in the exact order a real user would hit them (Invoice generation healed accounts 1100 + 4000; Record Payment then healed 1000).

This fix also permanently closes this bug category for the future — any account we add as a new "default" in a later phase (e.g. Accounts Payable in Procurement) will self-heal for every organization, old or new, the first time it's actually needed, without anyone ever running a manual migration script.

**What to do:** just redeploy (`git push`) and click Record Payment again on the same invoice — no database fix needed, the code heals it automatically.

### A deliberate simplification, documented so it isn't mistaken for a bug

Recording a payment currently marks an invoice **fully** paid regardless of the amount entered — there's no partial-payment tracking (e.g., paying ₹1,000 of a ₹3,000 invoice and leaving ₹2,000 outstanding) yet. This was a conscious scope cut to keep Phase 3 focused on proving the Sales→Finance hand-off works correctly; partial payments are a reasonable enhancement for a later phase, not a missing fundamental.



---

## PART 8 — Phase 4: Inventory + Procurement

### What we added

| Piece | What it does |
|---|---|
| `ProductCategory`, `Warehouse`, `StockLevel`, `StockMovement` models | Real stock tracking — `StockLevel` is the current count, `StockMovement` is the permanent ledger explaining how it got there (same pattern as Journal Entries in Finance) |
| `Product` extended (not replaced) | `sku`, `category_id`, `reorder_level` added to the same table from Phase 2, exactly as promised back then |
| `Vendor`, `PurchaseOrder`(+items), `GoodsReceipt` models | Procurement's mirror image of Sales — brings stock **in** instead of sending it **out** |
| `app/services/inventory.py` | Same shared-service pattern as accounting.py — `receive_stock()` (Procurement calls this) and `issue_stock()` (Sales calls this), so neither module needs to import the other |
| `get_default_warehouse()` self-heals | Same self-healing pattern from the Finance bug fix — no organization can ever hit a missing-warehouse trap |
| Sales' `generate_invoice` now issues real stock | And **rejects the invoice entirely** if there isn't enough stock — this is the actual point of Inventory existing: Sales can no longer promise something that isn't there |
| `/inventory` and `/procurement` frontend pages | Categories, products with live stock + low-stock warnings, stock movement ledger, vendors, purchase orders, and a "Receive Goods" action |
| Dashboard | Now shows Low Stock and Pending Purchase Order counts, and both modules are live-linked |

### A second real bug, and why it's a different kind than the last one

After adding `sku`, `category_id`, and `reorder_level` to the `Product` model, the very next test run failed with `column "sku" of relation "products" does not exist`.

**This is a different bug category than the Finance self-healing one.** That one was *missing rows* in an existing table (an old organization with zero account rows). This one is a *missing column* — the `products` table itself already existed from Phase 2 testing, and `Base.metadata.create_all()` **only creates tables that don't exist yet — it never alters a table that's already there**, even if the code now says that table should have three more columns.

This was flagged as a known limitation all the way back in Phase 1's `main.py` comment ("this is fine while we're actively building... once the schema stabilizes, we'll switch to Alembic migrations"). This is that moment arriving.

**Immediate fix (already applied locally, and needed once on your Supabase database too):**
```sql
ALTER TABLE products ADD COLUMN IF NOT EXISTS sku VARCHAR;
ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id UUID;
ALTER TABLE products ADD COLUMN IF NOT EXISTS reorder_level INTEGER NOT NULL DEFAULT 0;
```
Run this once in Supabase's SQL Editor before your Phase 4 deploy goes live, or every request touching Products will fail with the same error you'd see locally.

**Why we didn't fix this "properly" with Alembic in the same phase:** introducing real migration tooling correctly - especially generating a *baseline* migration that matches a database that already has real tables in it, without accidentally trying to recreate them - deserves its own careful, dedicated pass, not to be rushed alongside feature work. Patching this specific column gap now, unblocking Phase 4, and scheduling Alembic as the very next piece of work (before Phase 5 feature-building resumes) is the more honest engineering call than pretending to add proper migrations in the same breath as three new modules.

**What this means going forward:** any time we add a column to a table that already existed in a prior phase (not a brand-new table), expect this same error, and apply the same kind of `ALTER TABLE` fix, until Alembic is in place.

### Full lifecycle test (including the two failure modes that matter most)

```
signup → category "Electronics" → product "USB Cable" (SKU, reorder_level=10)
→ stock BEFORE any purchase: empty (no StockLevel row exists yet - correct)
→ vendor → purchase order (50 units) → RECEIVE → stock: 50

→ Test 1: order 100 units (more than the 50 available)
    → generate invoice REJECTED: "Insufficient stock for 'USB Cable':
      50 available, 100 required."
    → stock UNCHANGED at 50 - confirms the rejection has zero side effects,
      nothing partially written

→ Test 2: order 20 units (within the 50 available)
    → generate invoice SUCCEEDS
    → stock correctly drops: 50 → 30
    → movement ledger shows exactly one 'in' of 50 and one 'out' of 20
```

The insufficient-stock rejection leaving stock completely untouched is the important part to notice — it proves the whole operation (stock check, invoice, journal entry) either fully succeeds or fully fails together, never partially.

---

## PART 10 — Alembic Migrations Adopted

As promised, this happened before any Phase 5 feature work. Key points:

- `alembic/env.py` is wired to our real `app.core.config.settings` (never a second, hardcoded DB URL) and to `Base.metadata` (so autogenerate sees every model).
- `Base.metadata.create_all()` was **removed from `main.py`**. The schema is now created/changed **only** by running `alembic upgrade head` — never silently at app startup.
- The baseline migration was generated against a completely empty database (proving a brand-new client deployment works from zero), then applied successfully end-to-end (signup, seeded accounts, everything worked).
- Our existing, already-populated database was `alembic stamp head`'d — marked as being at the baseline **without** re-running `CREATE TABLE` (which would have failed since the tables already existed). **You need to do this exact same `stamp` step once on your Supabase database** before your next deploy — see Part 11's deploy note.
- **Workflow going forward, whenever a model changes:**
  ```bash
  cd backend
  alembic revision --autogenerate -m "describe the change"
  # review the generated file in alembic/versions/ before applying
  alembic upgrade head
  ```
  Commit the new migration file together with the model change — it's part of the same change, not an afterthought.
- Alembic's autogenerate also caught a *second* leftover issue from Phase 4's manual `ALTER TABLE` patch: the `category_id` column existed, but its actual foreign-key **constraint** to `product_categories` never did. The HR migration (Part 11) fixed both in the same pass — a nice proof that autogenerate genuinely diffs against the real database, not just against migration history.

---

## PART 11 — Phase 5: HR & Payroll

### What we added

| Piece | What it does |
|---|---|
| `Department`, `Employee`, `Attendance`, `LeaveRequest` models | Standard HR records. `Employee` is deliberately separate from `User` (`user_id` is optional) — not every employee logs in, and not every logged-in user is an employee. |
| `PayrollRun`, `Payslip` models | One `PayrollRun` per month; `/process` generates a `Payslip` per active employee |
| `POST /api/hr/payroll-runs/{id}/process` | The real action: 10% flat deduction per employee (documented as a placeholder — real tax/PF slabs are a later refinement), **and posts one Journal Entry for the whole run's total** — same commit-together pattern as Sales' invoice generation and Procurement's goods receipt |
| New default account: `5000 Payroll Expense` | Added to the same `DEFAULT_ACCOUNTS` list from Finance — self-healing means every organization, old or new, gets it automatically the first time payroll actually runs, no backfill needed |
| `/hr` frontend page | Departments, employees, leave requests with Approve/Reject, and payroll runs with a Process button showing generated payslips |

### Full lifecycle test (verified end-to-end)

```
department "Engineering" → employees Arjun (₹60,000/mo) and Divya (₹40,000/mo)
→ attendance marked, leave request created and approved
→ payroll run (Aug 2026) created → processed
    → 2 payslips: ₹54,000 net (10% off 60k) and ₹36,000 net (10% off 40k)
    → ONE journal entry: Dr Payroll Expense ₹90,000 / Cr Cash ₹90,000
→ attempted to process the SAME run again → correctly rejected
```

### Deploying this update

Same as always, plus the new migration step:
```bash
git add . && git commit -m "Phase 5: HR & Payroll + Alembic migrations" && git push
```
**Before this deploy goes live, run once against your Supabase database** (via its SQL Editor, or `psql`, or by running the Alembic commands with `DATABASE_URL` pointed at Supabase):
1. If this is your first time adopting Alembic on that database: `alembic stamp head` using the *previous* (Phase 4) migration as head — do this BEFORE pulling Phase 5's code, so the baseline is marked without re-running old `CREATE TABLE`s.
2. Then `alembic upgrade head` to apply the new HR tables and the `category_id` foreign key fix.

If you're unsure which state your Supabase database is in, tell me what tables currently exist there and I'll give you the exact commands for your specific situation rather than a generic one.

---

## PART 13 — Phase 6: Projects & Tasks

### What we added

| Piece | What it does |
|---|---|
| `Project`, `Task`, `TimeLog` models | Self-contained module — no Finance/Inventory hand-offs, as planned |
| `client_account_id` on Project | Optionally links to a CRM Account, for services-oriented orgs; internal projects just leave it null |
| `/projects` frontend page | Create projects, add tasks with priority, checkbox to mark done, log hours per task with a running total shown inline |
| Dashboard | Active Projects and Open Tasks tiles, module now live-linked |

### Full lifecycle test (verified end-to-end)

```
signup → project "Website Revamp" → task "Design homepage" (priority: high)
→ log 3.5 hours against the task
→ mark task done
→ all three list endpoints (projects, tasks, time-logs) confirmed correct
```

Straightforward module, deliberately - the "breather" phase between Inventory/Procurement's stock logic and Documents' upcoming approval-workflow engine.

### Deploying this update

Same as Phase 5 — `alembic upgrade head` on Supabase (no `stamp` needed this time, since Supabase should already be at the Phase 5 baseline from your last deploy), then `git push`.

---

## PART 15 — Phase 7: Documents & Workflow Approvals

### What we added

| Piece | What it does |
|---|---|
| `Document` model | File references (title + URL), attachable to any record via `related_type`/`related_id` |
| `ApprovalWorkflow` | A reusable RULE an org defines once (e.g. "Manager then Finance"), stored as JSON steps |
| `ApprovalRequest` + `ApprovalStep` | One real INSTANCE of a rule running against one real record, materialized into ordered, individually-trackable step rows — same audit-trail philosophy as Journal Lines and Stock Movements |
| `POST /approval-requests/{id}/action` | Acts on whichever step is currently pending, **in strict order** — step 2 is structurally impossible to action before step 1 |
| `/documents` frontend page | Define a workflow, submit something for approval, approve/reject step-by-step with the current required role shown |

**This is the first genuinely generic engine in the codebase.** Every other cross-module hand-off (Sales→Finance, Procurement→Inventory, HR→Finance) was a specific function for a specific event. This one is designed so ANY future module can trigger an approval by calling one endpoint with its own `entity_type`/`entity_id` — no new approval logic needs to be written per module.

**Known limitation, by design:** role-checking on who can action a step currently only distinguishes "Admin" (can action anything) from everyone else (must match the exact required role). Real fine-grained enforcement is Phase 11 (RBAC Enforcement) — this phase proves the workflow *mechanics* are correct, which was the actual goal here.

### Full lifecycle test (verified end-to-end)

```
2-step workflow created: Manager → Finance
→ approval request submitted → both steps start "pending"
→ action step 1 (Manager) → approved → request stays "pending" (step 2 still open)
→ action step 2 (Finance) → approved → request auto-completes to "approved"
→ re-actioning an already-approved request → correctly rejected

Separate test: reject at step 1
→ request immediately flips to "rejected"
→ step 2 never gets touched (confirms rejection stops the chain, doesn't cascade)
```

### Deploying this update

Same as always — `alembic upgrade head` on Supabase, then `git push`.

---

## PART 16 — Phase 8: Reports & Analytics

This is the 10th and last of the original modules from the TL's list. Deliberately last, exactly as the roadmap said — it reads data every other module already produced; there's no new business logic and no new cross-module hand-off to design.

### What we added

| Piece | What it does |
|---|---|
| `SavedReport` model | Stores which report + which filters a user was looking at (e.g. `{"months": 12}`), **never the results themselves** — reopening a saved report re-runs the live query against current data, same "never store what you can calculate" principle used for stock levels and dashboard counts |
| `app/services/reports.py` | One function per report area (`sales_summary`, `finance_summary`, `inventory_summary`, `procurement_summary`, `hr_summary`, `crm_funnel`, `projects_summary`) — all read-only, all computed live by querying the other 9 modules' own tables directly |
| 7 × `GET /api/reports/{module}-summary` | The actual analytics endpoints — revenue trends, top products, P&L, AR aging, stock valuation, vendor spend, headcount/payroll cost, lead-to-win funnel |
| `GET/POST/DELETE /api/reports/saved` | Save, list, and delete named report views |
| `GET /api/reports/export/{report_type}` | Streams any of the 7 report types back as a downloadable CSV |
| `/reports` frontend page | Tabs per module, bar-chart-style visualizations (plain Tailwind, no new npm dependency), a "Save this view" action, and an "Export CSV" button |

**What each report actually shows:**
- **Sales** — monthly revenue trend, top 5 products by revenue, funnel counts (leads → opportunities → quotations → orders → invoices), win rate.
- **Finance** — total revenue/expense/net profit (computed straight from Journal Lines by account type — the same ledger Phase 3 built, never a separate stored total), monthly revenue-vs-expense, and an Accounts Receivable aging breakdown (0–30 / 31–60 / 61–90 / 90+ days) computed from each unpaid invoice's due date.
- **Inventory** — total stock valuation (qty × unit price, live), and every product at or below its reorder level.
- **Procurement** — total spend and order count per vendor, PO status breakdown.
- **HR** — headcount by department, payroll cost by month (from processed Payroll Runs), pending leave requests.
- **CRM** — leads by status, opportunities by pipeline stage, pipeline value by stage, lead→customer conversion rate.
- **Projects** — projects by status, open task count.

### An important, honest note on testing for this phase

Every phase through Phase 7 was verified by actually running a real PostgreSQL database and hitting the API with real HTTP requests before being handed over — that discipline is the single highest-value thing about how this project has been built, and it isn't being abandoned here.

**What's different this time:** this phase was built in a sandboxed session with no network access at all — no `pip install`, no `apt install`, no way to stand up a real Postgres instance or install frontend `node_modules`. So instead of the usual "I ran this and here's the proof" writeup, here's exactly what *was* and *wasn't* verified before this reached you:

- **Was checked:** every backend `.py` file compiles cleanly (`py_compile`, catches syntax errors). Every model/field name referenced in `app/services/reports.py` was cross-checked line-by-line against the actual Phase 1–7 model files (e.g. confirmed `PayrollRun.status == "processed"` is the real value HR's own route uses, not a guess). The Alembic migration was hand-written in the exact structural format Alembic itself generated for Phases 5–7, with the correct `down_revision` pointing at Phase 7's migration. The new/changed TypeScript files were run through the TypeScript compiler in syntax-check mode (real syntax errors would show as `TS1xxx`; only expected "can't find react/next types" noise came back, because `node_modules` isn't installed in this sandbox).
- **Was NOT checked:** nothing here has been run against a real Postgres database, and the frontend has not been through a real `npm run build`. That means there's real risk of exactly the categories of bug found in every past phase — a field name mismatch, a query that's syntactically valid but returns the wrong shape, a Pydantic serialization quirk — slipping through untested this one time.

**What to do about it — same loop that already caught real bugs in Phases 3, 4, and 5:**

```bash
git add . && git commit -m "Phase 8: Reports & Analytics" && git push
# Render redeploys, runs `alembic upgrade head` automatically (Start Command from Phase 5),
# creating the new saved_reports table.
```

Then actually click through `/reports` yourself — flip through all 7 tabs, try Export CSV, try Save this view. If anything throws an error, copy the exact message (browser Console/Network tab if frontend, Render Logs if backend — see Part 12) and bring it back. That's not a fallback plan, it's the same process this whole project has used every single phase — the only difference this time is that your run is the *first* real run instead of the second.

### Deploying this update

Same as always — `alembic upgrade head` runs automatically via Render's Start Command, then `git push`. No manual Supabase step needed (nothing here changes an *existing* table, only adds one new one).

---

## PART 17 — Phase 9: Custom Fields, Made Real

This is the phase the roadmap called the actual core of the "customizable base" pitch. Phase 1 created a `CustomField` model; nothing since then let an admin actually define one or have it show up anywhere. That gap is closed now.

### The two mechanisms

1. **`CustomField`** — extended (not replaced) with `entity_type`, `options`, `is_required`, `is_active`, `display_order`, `created_at`. This is the DEFINITION: "Products have a Batch Number field, it's text, it's required."
2. **`CustomFieldValue`** (new table) — `custom_field_id` / `entity_type` / `entity_id` / `value`. This is ONE actual value on ONE actual record. Deliberately built as its own table using the exact `entity_type`+`entity_id` polymorphic-attachment pattern Phase 7's `ApprovalRequest` and the Documents module already use — not a JSON blob bolted onto `Product`/`Lead`/`Customer` directly. Same reasoning as everywhere else in this codebase: cross-cutting concerns get their own table, not a column added to every table that might need them.

### What we added

| Piece | What it does |
|---|---|
| `app/models/custom_field.py` | `CustomField` extended, `CustomFieldValue` added |
| `app/schemas/custom_field.py` | Definition CRUD schemas + bulk value get/set schemas |
| `app/api/routes/custom_fields.py` | `POST/GET/PATCH/DELETE /api/custom-fields` (definitions), `GET/POST /api/custom-fields/values` (per-record values) |
| `components/CustomFieldsSection.tsx` | The generic frontend piece — knows only `entityType`/`entityId`, renders inputs purely from `field_type` metadata. Zero per-module logic. Drop it anywhere with two props. |
| `/settings/custom-fields` | Admin screen to define/deactivate/delete fields — the actual "customization" UI |
| Inventory (`Product`) + CRM (`Lead`) | The two proof-of-mechanism modules, wired via an expand-per-row "Fields" toggle (neither module has a per-record detail page, so this matches the existing list-based UI rather than inventing a new pattern) |

**Adding a third module later is a two-line change** — one new entry in `ENTITY_OPTIONS` in the settings page, one `<CustomFieldsSection entityType="..." entityId={...} />` at the call site. Nothing in the backend, the component, or the schemas changes. That's the entire point of building it this way.

### Real bugs found by actually testing, not by guessing

1. **`entity_id` typed as plain `str` on the values GET route.** A malformed value flowed straight to the DB layer and crashed with a raw 500 instead of a clean validation error. Fixed by typing it as `UUID` so FastAPI validates it before it ever reaches a query.
2. **A genuine migration hazard, caught before it shipped, not after.** Autogenerate wanted to add `custom_fields.entity_type` as `NOT NULL` directly, with no backfill step. In practice this table has zero rows in every real deployment (the feature never had a route to write through until now) — but writing the migration that way regardless would have been the same category of mistake as the Phase 4 `products.sku` incident. Fixed by hand: add nullable → backfill → tighten to `NOT NULL`, the same shape used any time a column is added to a table that might already have rows.
3. **A second real drift, caught by Alembic itself.** The first version of the model didn't declare `nullable=False` on `is_required`/`is_active`/`display_order`, but the migration set them `NOT NULL` with a server default — a real mismatch between what the model claimed and what the database actually enforced. Caught by running `alembic revision --autogenerate` a second time after applying the first migration and confirming it generated an **empty** migration (proof of zero drift) — it didn't, until the model was fixed to match.
4. **`apiRequest` silently broken on `204` responses.** The `DELETE /api/custom-fields/{id}` route correctly returns `204 No Content` with an empty body. `lib/api.ts`'s `apiRequest` called `res.json()` unconditionally on any successful response — which throws a `SyntaxError` on a genuinely empty body. The error was caught by the calling code's `try/catch`, so it wouldn't have crashed the page, but every successful delete would have shown the user a confusing "error" message for a request that actually succeeded. Found by tracing the real `curl -i` response headers against what `lib/api.ts` actually does with them, not by assuming success always means a JSON body. Fixed in `lib/api.ts` itself (not just the one call site), so every future `204`-returning endpoint is safe automatically.
5. **The "Save Custom Fields" button was invisible — found by the user actually clicking through it, not by anything in this session's testing.** Root cause: `tailwind.config.js`'s `content` glob only scanned `./app/**`, never `./components/**`. `CustomFieldsSection.tsx` was the first file ever placed in `components/` in this project, so this gap existed silently since Phase 1 and simply had nothing to expose it until now. Any Tailwind class used *exclusively* in that file (`bg-slate-700`, `hover:bg-slate-600`, `disabled:opacity-50`) never made it into the compiled CSS — the button wasn't hidden, it was rendering with zero styling: no background, no padding, blending into the page. Fixed by adding `./components/**/*.{js,ts,jsx,tsx,mdx}` to the content glob, then **verified by grepping the actual compiled `.next/static/css/*.css` output** for those exact class selectors post-build, not by assuming the config change worked. **Pattern worth remembering:** any future file placed outside `app/` (a new `components/`, `lib/`, or `hooks/` directory) needs its own entry in this glob, or the same silent-unstyled-element bug will recur.

### How this was tested

Real local PostgreSQL, real Alembic migration (hand-corrected as above), real server, and this exact sequence run with `curl`:

```
define field on Product (text, required) → define field on Product (dropdown) → define field on Lead
→ reject: dropdown with no options
→ reject: duplicate field name on same entity_type
→ create a real Product, create a real Lead
→ GET values for the new Product BEFORE any are set → fields appear, value: null
→ GET with a malformed entity_id → clean 422, not a 500
→ SET two values on the Product → READ BACK → both persisted correctly
→ SET a value on the Lead (different module) → READ BACK → proves the mechanism is genuinely generic
→ reject: writing a Product field's ID against the Lead's entity_id
→ UPSERT: re-save the same field → confirmed it overwrites, doesn't duplicate
→ deactivate a field → confirmed it drops out of the live values list, but its stored value isn't deleted
→ admin listing with include_inactive=true → confirms deactivated fields are still visible for management
```
All 17 steps passed. Frontend: real `npm run build`, clean, all 15 pages including the new `/settings/custom-fields`. Both servers were then booted together and every touched page (`/`, `/login`, `/settings/custom-fields`, `/inventory`, `/crm`) was hit over real HTTP and returned 200 with no server errors in the log.

**One honest limitation of this session's testing:** a real browser click-through (Playwright) was attempted but blocked — the Chromium binary download domain (`cdn.playwright.dev`) isn't on this environment's network allowlist, the same category of restriction that blocked an unrelated `nodesource.com` apt repo earlier in this session. In its place, the actual JSON contract between the backend's real responses (captured live via `curl -i`) and what `CustomFieldsSection.tsx`/`lib/api.ts` do with them was traced by hand, field by field — which is how bug #4 above was actually found. This is a narrower substitute than a real click-through, and worth clicking through yourself once deployed, the same way every past phase has asked you to confirm.

### Deploying this update

```bash
git add . && git commit -m "Phase 9: Custom Fields, made real" && git push
# Render redeploys, runs `alembic upgrade head` automatically, adding
# custom_field_values and extending custom_fields with the new columns.
```

Then: log in, go to Settings (top-right of the Dashboard), define a field on Product or Lead, go to that module, click "Fields" on a record, save a value, refresh the page, confirm it's still there.

---

## PART 18a — Also Fixed: The Custom Fields "Save" Button Was Invisible

Found by the user actually clicking through the app after Phase 9 shipped — not by anything in this session's own testing. `tailwind.config.js`'s `content` glob only scanned `./app/**`, never `./components/**`. `CustomFieldsSection.tsx` was the first file ever placed under `components/` in this project, so this gap existed silently since Phase 1 and had nothing to expose it until now. Any class used *exclusively* in that file (`bg-slate-700`, `hover:bg-slate-600`, `disabled:opacity-50`) never made it into the compiled CSS — the button wasn't hidden by any logic, it was rendering with zero styling: no background, no padding, blending straight into the page.

Fixed by adding `./components/**/*.{js,ts,jsx,tsx,mdx}` to the glob, then **verified by grepping the real compiled `.next/static/css/*.css`** for the exact selectors after a fresh build — not assumed fixed just because the config changed:
```
hover\:bg-slate-600:hover{...background-color:rgb(71 85 105...)}
disabled\:opacity-50:disabled{opacity:.5}
```

**Pattern worth remembering:** any future file placed outside `app/` (a new `hooks/`, `lib/`, or another `components/` subfolder) hits this exact same silent-unstyled-element bug until it's added to the glob too.

---

## PART 19 — Phase 10 (Part 1): Notifications Wired Up + Every `window.prompt`/`confirm` Replaced

Phase 10 (UI/UX Polish) is a wide phase — prompt→modal replacement, Notifications, a design-consistency pass, mobile check, table pagination. Rather than cram all of it into one under-tested pass, it's deliberately split: this part covers the two concrete gaps the roadmap explicitly called out as still-open. The design-consistency/mobile/table pass is a separate, later part.

### Notifications, made real

The `Notification` model has existed since Phase 1 with every column it needed — no migration required this phase (verified: ran `alembic revision --autogenerate` after all the route/service work and got a genuinely **empty** migration back, proof of zero drift, not an assumption).

| Piece | What it does |
|---|---|
| `app/services/notifications.py` | `notify_user()` — one notification, one specific user. `notify_role()` — notify everyone in the org currently holding a named role. Both soft-fail by design: a missing `user_id` or a role name with no matching `Role` row never blocks the real business action, it just means nobody gets alerted this time. |
| `GET /api/notifications`, `GET /api/notifications/unread-count`, `PATCH /api/notifications/{id}/read`, `POST /api/notifications/read-all` | Scoped to the CURRENT user, not just org_id — a notification is inherently personal, unlike every other module's routes. |
| HR's leave-status-update route | Notifies the employee (if `Employee.user_id` is set) the moment their leave is approved or rejected. |
| Documents' approval-request creation and step-action routes | Notifies whoever holds the required role the moment a step becomes actionable (at creation, and again each time a prior step clears) — and notifies the original requester once the whole request resolves, approved or rejected. |
| `components/NotificationBell.tsx` | Bell icon + unread badge + dropdown list, polls every 30s. Placed on Dashboard, HR, and Documents — the two pages that actually generate notifications, plus the main landing page. |

**A real bug found by testing this, not by guessing:** `EmployeeCreate`/`EmployeeOut` never exposed `user_id`, even though the column has existed on the `Employee` model since Phase 5. Same "field exists on the model, no route ever exposed it" pattern as Custom Fields before Phase 9 — it just never mattered until a real feature (leave-approval notifications) needed to actually set it. First test run proved this the hard way: created an employee with `user_id` in the request body, approved their leave, checked unread count — **stayed at 0**. Traced it to the schema silently dropping the field (Pydantic ignores undeclared fields by default), fixed both schemas, reran the exact same test, and got the real result: `unread_count` 0 → 1, correct message, mark-as-read correctly dropping it back to 0.

**Every notification trigger point tested for real, end-to-end:**
```
HR: create employee (now WITH a real user_id) → create leave request → approve
  → unread_count: 0 → 1 → mark read → back to 0

Documents, positive case: workflow requiring role "Admin" (a role that genuinely
exists) → create approval request → unread_count: 0 → 1 (step 1 notification)

Documents, soft-fail case: workflow requiring role "Manager" (does NOT exist in
this org — no user-invite/role-creation route exists yet, a known separate gap)
→ create approval request → request still succeeds (201), no crash,
  unread_count UNCHANGED — soft-fail behaving exactly as designed

Documents, full chain: 2-step workflow, both steps role "Admin"
→ create request: unread 0 → 1 ("needs your approval" — step 1)
→ approve step 1: unread 1 → 2 ("needs your approval" — step 2 now actionable)
→ approve step 2 (final): unread 2 → 3 ("your request was approved" — requester notified)
```

**One honest limitation:** the Documents-side positive test could only use the "Admin" role, since no route exists yet to create additional users or assign them a different role — that's the same RBAC-scaffolding-not-enforced gap the roadmap already lists as open, not something new. The soft-fail path (role genuinely absent) was tested instead of a second real role, and is a legitimate test of the same code path — `notify_role()` doesn't care whether the role is missing because no one created it yet, or because the org happens not to use that name.

### Every `window.prompt()`/`window.confirm()` replaced

| Old | New |
|---|---|
| CRM's Convert Lead — two chained `window.prompt()` calls | A real two-field modal (`components/Modal.tsx`'s `Modal` shell, custom form) |
| Settings/Custom Fields' Delete — `window.confirm()` | `ConfirmModal`, red/"danger" styled |
| Reports' Save View — `window.prompt()` | `PromptModal`, single-field |

`components/Modal.tsx` is one shared implementation (`Modal`, `PromptModal`, `ConfirmModal`) — the actual start of the design-consistency pass, even though the rest of that pass is still ahead.

**A second real bug found while building this, unrelated to the prompt replacement itself:** `apiRequest` in `lib/api.ts` was traced against the Reports Save View flow, and a leftover UI bug was caught mid-build — the `PromptModal` JSX for Reports' save-view flow was written in one pass but never actually got appended to the page before the previous message ended (a genuine "said it was done, wasn't" gap, caught by grepping the file for `PromptModal` usage before claiming it worked, not by assuming the earlier edit succeeded).

### How this was tested

Real local PostgreSQL, real server, all of the sequences above run with `curl` against a live-booted backend. Frontend: real `npm run build`, clean, all 15 pages, sizes increased exactly where expected (crm/hr/documents/reports/settings all grew — matching the modals and bell added, nothing else moved).

### Deploying this update

```bash
git add . && git commit -m "Phase 10 (1/2): Notifications wired up, every window.prompt/confirm replaced" && git push
```
No Alembic step needed — no schema changed. Then click through: approve a leave request and watch the bell update, convert a lead through the new modal, delete a custom field with the new confirm dialog, save a report view through the new modal.

---

## PART 21 — Phase 10 (Part 2): Shared Components, Mobile Check, Table Pagination

The second half of Phase 10. Given the scope (87 hand-rolled button/input class instances found across 13 pages before starting), this was deliberately sequenced rather than attempted as one uncontrolled diff — see the honest coverage note below rather than assuming "design pass" means every pixel got touched.

### Shared component primitives — `components/ui.tsx`

`Button` (variants: primary/secondary/danger/ghost, sizes: sm/md), `Input`, `Select`, `Card`, `PageHeader`. One definition per semantic type instead of the drifting padding/sizing that had accumulated (`px-3 py-1`, `px-3 py-1.5`, `px-4 py-1.5`, `px-4 py-2` all coexisting for what was supposed to be the same "primary action" button).

**A real bug caught before it could spread:** `PageHeader`'s first draft used a plain `<a href>` for the "← Dashboard" link instead of Next.js's `<Link>`. That would have forced a full page reload — losing all client-side state — on every single "back to dashboard" click, on every page that used it. Caught and fixed before the component was rolled out anywhere, not after.

### Coverage — honest, not silently rounded up

| Page | What changed |
|---|---|
| Finance, Procurement, Projects, Sales, Inventory | Header swapped to `PageHeader` (mechanical, exact-string-matched before replacing) |
| CRM | Header swapped to `PageHeader` **+** action buttons migrated to `Button` (Convert, Fields toggle, Add Lead) — the fuller proof-of-pattern page |
| HR, Documents | Header swapped to `PageHeader` using its `actions` slot, to carry the `NotificationBell` that Phase 10 part 1 added |
| Dashboard | Left as its own custom header — it's the landing page, not a "back to X" page, so `PageHeader`'s pattern doesn't fit it |
| Settings/Custom Fields, Reports | **Not migrated.** Both have header structure `PageHeader` doesn't support yet (a subtitle under the title; extra action buttons alongside the back link). Forcing them in would mean either a worse-fitting header or scope-creeping `PageHeader` itself — flagged as a follow-up rather than done badly. |
| Remaining buttons on Finance/Procurement/Projects/Sales/Settings/Reports | Still hand-rolled. Only CRM got the full button migration this pass. |

**A second real bug, self-inflicted and caught by re-viewing the file:** the first attempt at swapping CRM's "Add Lead" button to the new `Button` component left orphaned JSX behind — leftover button text and a stray closing `</button>` tag from the original markup. Caught by viewing the file immediately after the edit rather than trusting the edit succeeded, fixed before it ever reached a build.

### Mobile check

- `app/layout.tsx` now exports an explicit `viewport` config (`width: device-width, initialScale: 1`). Next.js's App Router injects a sensible default automatically, but relying on an implicit default silently holding across framework upgrades is exactly the kind of thing worth making explicit rather than assumed.
- **13 real instances** of `grid-cols-2`/`grid-cols-3` with no responsive breakpoint, found by grep across every page and component — worst offender was Reports, whose three stat-card grids (`grid-cols-3`) would have genuinely overflowed on a phone screen, not just looked cramped. Fixed uniformly to `grid-cols-1 sm:grid-cols-N` across `CustomFieldsSection`, HR, Inventory, Procurement, Settings, and all seven of Reports' grids.
- Checked for hardcoded pixel widths (`w-[...]`, `min-w-[...]`) that could force horizontal scroll on narrow screens — none found.

### Table pagination

`components/Pagination.tsx` — `usePagination(items, pageSize)` hook + `PaginationControls` component, both fully generic (not Inventory-specific; drop them into any list once it crosses the roadmap's ~20-row threshold). Wired into Inventory's Product list at 10 rows/page, the module named in the roadmap as the concrete example.

**Verified against real data, not just read:** created 12 real products via the API (not mocked), confirmed all 12 came back from `GET /api/sales/products`, then ran the exact same slicing logic `usePagination` uses — in Node, against that real 12-item shape — and asserted: page 1 shows exactly 10, page 2 shows exactly 2, an out-of-range page request clamps to the last real page instead of erroring, and an empty list correctly reports `totalPages: 1` (so `PaginationControls`'s `totalPages <= 1` check correctly hides the controls entirely rather than showing "Page 1 of 0"). All four assertions passed.

### How this was tested

Real local PostgreSQL — confirmed **zero schema drift** from this entire phase (an empty `alembic revision --autogenerate` migration, generated and deleted, same discipline as every schema-adjacent phase). Backend and frontend booted together; all 13 pages (not just the migrated ones) hit over real HTTP, all returned 200 with no server-render errors in the Next.js log. Pagination logic verified against genuine API-sourced data and boundary cases in Node, not assumed correct from reading the TSX.

**One honest limitation carried over from Phase 10 part 1, unchanged:** no real browser click-through was possible this session either — the Chromium binary domain remains outside this environment's network allowlist. Verification here is real HTTP responses + real algorithmic proof against real data, which is strong for logic correctness, but it is still not the same as watching pagination controls actually render and respond to a click in a browser. Worth doing that pass yourself once deployed.

### Deploying this update

```bash
git add . && git commit -m "Phase 10 (2/2): shared components, mobile fixes, table pagination" && git push
```
No Alembic step needed — confirmed no schema changed.

---

## PART 23 — Phase 11: RBAC Enforcement

The biggest remaining piece of "customizable base" that was structure without behavior — Roles/Permissions have existed since Phase 1, but until this phase, no route anywhere actually checked one. Any logged-in user could do anything.

### The one scoping decision made up front, flagged rather than hidden

The `Permission` model already anticipates five granular actions per module (`view`, `create`, `edit`, `delete`, `approve`), and signup already seeds all five for a brand-new org's Admin role. Given that, this phase applies the SAME granularity per route rather than collapsing to a simpler two-tier scheme — GET routes require `view`, POST-create routes require `create`, PATCH/status-change routes require `edit`, DELETE routes require `delete`, and the two genuinely approval-shaped actions (Documents' step-action, HR's leave-status-update) require `approve` specifically, since that's a precise semantic fit already built into the model. This isn't a shortcut — it's using the mechanism exactly as it was already designed, just finally wired up.

### What was built

| Piece | What it does |
|---|---|
| `app/api/deps.py`'s `require_permission(module, action)` | A dependency FACTORY — call it with the module/action a route needs, get back the actual check to attach. One function serves all 80 routes instead of 80 bespoke checks. |
| `app/api/routes/roles.py` (new) | `POST/GET /api/core/roles`, `POST/GET/DELETE /api/core/roles/{id}/permissions`, `GET/POST /api/core/users`, `PATCH /api/core/users/{id}/role` — the piece that was missing before this phase and that made RBAC untestable: no way to create a second user with a different role. Gated behind `core` module permissions, same as everything else — Admin already has full `core` access from signup. |
| Every route in every business module | `dependencies=[Depends(require_permission(module, action))]` added directly at the `@router` decorator level — applied to all **80 routes** across CRM, Sales, Finance, Inventory, Procurement, HR, Projects, Documents, Reports, Custom Fields, and Dashboard, via a scripted exact-match pass rather than 80 individual manual edits (lower risk of a typo breaking one route while fixing another). |
| Notifications routes | Deliberately **NOT** gated behind `require_permission` — a notification is already scoped to `current_user.id` specifically (see Phase 10 part 1), so "can you see your own notifications" isn't a business-module permission question the same way "can you see the CRM pipeline" is. Noted as a decision, not an oversight. |

### A real bug caught by reasoning, before it could lock anyone out

Signup's seeded-modules list (`app/api/routes/auth.py`) was written in Phase 1 and never updated when Custom Fields (Phase 9) or Notifications (Phase 10) were added — so any org that signed up before this phase would have an Admin role with **zero** `Permission` rows for `custom_fields`. The moment enforcement went live, every existing admin would have been locked out of a module they're supposed to fully control. Fixed two ways: signup's module list now includes `custom_fields` going forward, AND `require_permission()` self-heals — if a role named "Admin" has genuinely zero permission rows for a module, that's treated as "this module didn't exist yet when the org signed up," and the full permission set is granted and persisted on the spot. Same philosophy as `get_account()`/`get_default_warehouse()`'s self-healing from earlier phases, applied to the same class of problem.

### How this was tested — real, not assumed

Real local PostgreSQL, real server. Confirmed **zero schema drift** (empty autogenerate migration — this phase only touches route decorators and one seeding list, no models changed).

```
Admin (full access from signup): GET /sales/products -> 200, POST -> 201

Admin creates a "Sales Viewer" role, grants it ONLY sales.view
Admin creates a second real user with that role
Log in AS that second user (a real, distinct login — not simulated)

Viewer GET /sales/products         -> 200  (granted)
Viewer POST /sales/products        -> 403  "does not have 'create' access to 'sales'"
Viewer GET /hr/employees           -> 403  "does not have 'view' access to 'hr'" (no hr permission granted at all)
Viewer GET /core/users             -> 403  "does not have 'view' access to 'core'" (can't manage other users)
```

**Self-healing path, verified with properly org-scoped queries** (an early version of this test had an unscoped SQL query that gave a misleading result — caught and redone correctly rather than reported as-is):
```
Deleted a real org's Admin role's custom_fields Permission rows directly (simulating a
  pre-Phase-9 org) -> confirmed 0 rows remain, properly scoped to that one org
Admin hits a custom_fields route -> 200 (self-healed, not 403)
Confirmed the self-heal wrote exactly 5 rows (one per action), not a partial or duplicate set
Called the same route AGAIN -> still exactly 5 rows, not 10 -> self-heal is idempotent,
  doesn't re-insert on every request once the gap is closed
```

**One honest limitation:** the previous phase's manual flagged not being able to fully test the Documents-module role-based notification path because no second-user-with-a-different-role capability existed. That gap is now closed by this phase's own `roles.py` — worth revisiting that test with a real non-Admin approver role now that it's possible, though it wasn't re-run this session since the underlying `notify_role()` mechanism was already proven correct in Phase 10 part 1.

### Deploying this update

```bash
git add . && git commit -m "Phase 11: RBAC enforcement on every route" && git push
```
No Alembic step needed — no schema changed, only route-level dependencies and one seeding list.

**Important operational note:** once this deploys, every EXISTING user in every EXISTING org who isn't the original Admin (i.e., anyone with `role_id = NULL` or a custom role with no permissions granted yet) will start getting 403s on everything. That's the correct, intended behavior — but it means this is the point where you'd actually go create real restricted roles for real team members via the new `/api/core/roles` endpoints, not something to deploy silently and forget.

---

## PART 25 — Phase 12: A Real `pytest` Suite + CI

The second Client-Ready item, and it closes two gaps at once: the "logic that must never silently break" testing the roadmap named, AND the two-org isolation stress test flagged as open since the very first handoff document and never actually done until now.

### A real, honest surprise: the CI workflow didn't exist

The original Phase 1 handoff document describes a GitHub Actions workflow as already set up. It isn't in this codebase — `find . -iname ".github"` came back empty before this phase. Rather than assume it was lost somewhere and quietly recreate it without comment, flagging it here plainly: whatever the actual history, this session is the first time `.github/workflows/ci.yml` has existed in what's been handed forward. It's built now, and it actually runs pytest + a real Postgres service container + a frontend build on every push — not a stub.

### Test infrastructure — three real design decisions

| Decision | Why |
|---|---|
| A dedicated `erp_pytest_db`, never the dev database | Tests should never be able to touch real or manually-tested data, even by accident. |
| Real Alembic migrations in the test fixture, not `Base.metadata.create_all()` | This project's own established rule (Part 7/10) is that `create_all()` can't alter existing tables and hid a real Phase 4 bug. Running the actual migration chain in the test fixture means every test run also re-proves every migration still applies cleanly to a fresh database — `create_all()` would silently skip that entirely. |
| Isolation via a unique org per test (via `signup()`), not per-test transaction rollback | Almost every route in this app calls `db.commit()` directly mid-function — self-healing lookups, multi-step actions, the notification service all commit independently. A wrap-and-rollback pattern would fight that architecture throughout. Every test that needs data creates its own uniquely-subdomained org instead — the same pattern this whole project's manual curl testing has used all along, just automated. |

### What's covered — 16 tests, all passing

| File | What it locks in |
|---|---|
| `test_inventory_stock.py` | Insufficient-stock rejection leaves stock completely untouched (not partially decremented); sufficient stock succeeds and decrements exactly right. |
| `test_finance_journal.py` | Every journal entry balances (debits == credits) across invoice generation AND payment recording; a duplicate payment on an already-paid invoice is rejected, not double-counted. |
| `test_hr_payroll.py` | The exact payroll figures from Phase 5's own manual (₹60,000+₹40,000 gross → ₹54,000+₹36,000 net, ONE ₹90,000 balanced journal entry for the whole run); reprocessing an already-processed run is blocked. |
| `test_multitenancy_isolation.py` | **Closes the standing gap.** Org B cannot see Org A's leads through a list endpoint, cannot fetch Org A's product by direct ID, cannot pay Org A's invoice, and cannot see Org A's users through the RBAC management endpoints. Four separate attack surfaces (list, direct-ID, cross-org write, admin endpoints), not just one. |
| `test_rbac_permissions.py` | A view-only role can view but not create; a role with only `sales.view` has zero access to HR or to role/user management; the Admin role keeps full access; and — as a permanent regression test — the exact self-healing bug found and fixed in Phase 11 (an org's Admin role missing permission rows for a module added in a later phase self-heals to exactly 5 rows, not zero, not duplicated on repeat calls). |

### Proof the suite has real teeth, not vacuous assertions

Rather than trust that green checkmarks mean the tests are actually checking anything, one test's underlying protection was **deliberately disabled** and the suite rerun:
```
sed -i 's/if level.quantity < qty:/if False:  # DELIBERATELY BROKEN/' app/services/inventory.py
pytest tests/test_inventory_stock.py -v
  -> test_insufficient_stock_is_rejected_and_leaves_stock_untouched FAILED
  -> test_sufficient_stock_succeeds_and_decrements_correctly PASSED (unaffected, as expected)
```
The test caught the deliberate break immediately. Reverted, reran the full suite: **16 passed**, confirming both that the fix was correctly restored and that the test itself isn't a false positive.

### One real bug found along the way, in the tests themselves — not the app

The first run of `test_finance_journal.py` and `test_multitenancy_isolation.py` failed with `KeyError: 'id'` on invoice creation. Root cause: those tests created a Product and tried to invoice it immediately, without ever receiving stock via a real Purchase Order first — so the app correctly rejected the invoice for insufficient stock (exactly the behavior `test_inventory_stock.py` proves), and the test's own assumption that `invoice["id"]` would exist was wrong. Fixed by adding the same `stock_product()` helper pattern already used correctly in `test_inventory_stock.py`, not by weakening the assertion or skipping the check.

### How to run this yourself

```bash
cd backend
createdb -O <your_pg_user> erp_pytest_db   # once, locally
pip install -r requirements.txt
DATABASE_URL="postgresql://<user>:<pass>@localhost:5432/erp_pytest_db" \
JWT_SECRET_KEY="test_secret" ALLOWED_ORIGINS="http://localhost:3000" \
pytest -v
```
On every `git push`, `.github/workflows/ci.yml` now does this automatically against a fresh Postgres service container GitHub provisions — no local setup needed to see it run, and a broken change gets caught before it ever reaches Render/Vercel.

### One honest limitation

The CI workflow's YAML was validated for correct syntax and every command in it was verified locally against real Postgres — but it hasn't been proven against GitHub's actual runner infrastructure, since that requires a real repo and a real push, which this environment can't do. Worth confirming it goes green on your first real push rather than assuming it will.

### Deploying this update

```bash
git add . && git commit -m "Phase 12: pytest suite + CI workflow" && git push
```
No Alembic step needed against your real database — this phase only adds tests and CI config, no app schema or route changes.

---

## PART 27 — Phase 11b: The Roles & Permissions Frontend

Phase 11 shipped real RBAC enforcement, but with no UI — the only way to create a role, grant a permission, or create a second user was through Swagger's `/docs`. Flagged correctly as "not fully done" until a real page existed. This closes that.

### `/settings/roles`

Same layout conventions as `/settings/custom-fields` (Card-based sections, the Phase 10 `components/ui.tsx` primitives), now cross-linked from both the Dashboard and Custom Fields settings pages so neither is a dead end.

| Section | What it does |
|---|---|
| Roles | Name + Add button, list below. Creating a role immediately selects it, so the next natural action (granting permissions) is one click away, not a second navigation. |
| Permission matrix | Every module as a row, `view`/`create`/`edit`/`delete`/`approve` as checkbox columns, for whichever role is selected. Checking a box calls `POST /permissions`; unchecking calls `DELETE /permissions/{id}` — the actual permission ID is tracked per checkbox so the delete call is always exact, not a guess. |
| Users | Name/email/password/role-dropdown to create, list below with each user's current role shown and changeable via its own dropdown (`PATCH /users/{id}/role`). |

No new backend work — this consumes `/api/core/roles` and `/api/core/users` exactly as Phase 11 built them.

### How this was tested — the exact loop, against a real server

```
Create role "Sales Viewer" (what the Add button does)         -> 201, real role returned
List roles (what the Roles card renders)                      -> [Admin, Sales Viewer]
Load permissions BEFORE granting anything                     -> [] (matrix shows all unchecked)
Toggle ON sales.view (what clicking a checkbox does)           -> 201, permission created
Reload permissions                                             -> [sales/view] (matrix shows exactly one checked box)
Create user with this role (what the Add User form does)      -> 201, role_name correctly "Sales Viewer"
List users                                                      -> Admin + Viewer User, each with correct role_name
Toggle OFF sales.view (uncheck)                                 -> 204
Reload permissions                                              -> [] again
```
Every step matched exactly what the component code does, verified against the real running API before being called done — not assumed from reading the schemas.

Frontend: real `npm run build`, clean, `/settings/roles` compiled at 3.94 kB. Backend + frontend booted together, `/settings/roles`, `/settings/custom-fields`, and `/dashboard` all hit over real HTTP, all 200, no server-render errors.

### Deploying this update

```bash
git add . && git commit -m "Phase 11b: Roles & Permissions frontend" && git push
```
No Alembic step needed — pure frontend, consuming existing endpoints.

**Your turn:** the real proof this whole system works isn't in this manual — it's creating a restricted "Sales Viewer" role granting only `sales.view` through this new page, creating a second user with it, logging in as them, and confirming you can see Sales but get blocked everywhere else. That's the visual confirmation Phase 11 was missing until now.

---

## PART 29 — Phase 13: Security Hardening

The last item before pure QA/demo-prep. Covers all five things the roadmap named: password reset, email verification, login rate limiting, secrets hygiene, and basic monitoring.

### The one honest constraint shaping this whole phase: no email provider exists

Nothing in this codebase has ever sent a real email — no SMTP, SendGrid, Resend, SES, nothing. Password reset and email verification both fundamentally need an email to arrive somewhere. Rather than skip both features or fake success silently, `app/services/email.py` logs the "sent" email clearly to the server console (visible in Render's Logs tab in production) — genuinely testable end-to-end in dev, honest rather than a silent black hole in production. Swapping in a real provider later is a five-line change in one function; nothing else in the app needs to know or care.

**One deliberate, flagged scope decision:** email verification is fully built (token generated at signup, `/verify-email` endpoint, `email_verified` column) but **not enforced** — login doesn't check it. Enforcing it would lock out every single user the moment this ships, with no real email delivery for them to actually receive a link and unlock themselves. The mechanism is correct and ready; flip on the login check once a real provider is wired in.

### A real secrets-hygiene bug, found on the first read of `config.py`

`JWT_SECRET_KEY` had a weak, well-known **default value baked directly into source code** (`"change-this-to-a-long-random-string-before-deploying"`). If any deployment ever forgot to set the real environment variable, the app would boot successfully and silently sign every JWT with a secret anyone who's ever seen this codebase already knows — a genuine account-takeover vulnerability, not a style nit. Fixed by removing the default entirely and adding a validator that rejects both an empty value and the placeholder text — **the app now refuses to start** rather than run insecurely. Proven both directions:
```
JWT_SECRET_KEY unset  -> ImportError / pydantic ValidationError, app refuses to start
JWT_SECRET_KEY set    -> imports and runs cleanly
```

### Login rate limiting

Five failed attempts locks the account for 15 minutes (both configurable via `.env`) — and the lockout check runs **before** password verification, so a locked account rejects even the *correct* password until the window passes; otherwise "rate limiting" wouldn't actually limit anything.

```
5 wrong passwords -> all 401
6th attempt, CORRECT password -> 429 "Too many failed login attempts. Try again in 14 minute(s)."
Manually expire the lockout window (simulating 15 real minutes passing)
Correct password -> 200, works again
A successful login resets the failed-attempt counter to 0
```

### Password reset

Reset tokens are stored **hashed** (SHA-256, not bcrypt — a token is already 32 bytes of real randomness via `secrets.token_urlsafe`, unlike a human password, so it doesn't need slow salted hashing, just protection if the database ever leaked). `/forgot-password` always returns the identical response whether or not the email exists — proven directly:
```
forgot-password for a REAL registered email -> 200 "If that email has an account..."
forgot-password for a email that has never existed -> 200, IDENTICAL message
```
Full reset flow, tested end-to-end with the real token extracted from server logs (not assumed):
```
request reset -> token logged -> reset with it -> 200
OLD password -> 401 (correctly invalidated)
NEW password -> 200 (works)
reuse the SAME token again -> 400 (single-use enforced, not replayable)
an already-expired token -> 400 (checked separately from single-use)
```

### Basic monitoring

`/health` previously only proved the Python process was alive — a FastAPI process can stay "up" while its database connection is completely dead (wrong credentials after a rotation, Supabase paused after 7 days of inactivity — a real, already-documented free-tier behavior in this project's own manual). It now runs an actual trivial query and reports `{"status": "ok", "database": "ok"}` or `"degraded"`/`"error"` — a dead DB shows up here immediately instead of only being discovered when a real user's request fails.

### Two real bugs found by actually testing, not by guessing

1. **The same NOT-NULL-with-no-backfill migration bug, a third time.** Autogenerate wanted `users.email_verified` and `users.failed_login_attempts` added as `NOT NULL` directly, on a table (`users`) that has real rows in every org ever created — including the user's own real deployed org. This would have hard-failed against any populated database. Fixed with the same nullable → backfill → tighten shape as Phase 4's `products.sku` and Phase 9's `custom_fields.entity_type` — the pattern is now well-established in this codebase, and worth recognizing on sight for the next new column on an old table.
2. **A test-file bug in the NEW pytest suite, caught by literally rerunning it.** The first version of `test_security_hardening.py` used fixed literal email strings (`"lockout-test@test.com"`) instead of unique ones — the very first rerun against the same persistent test database (not even a different run, just running the suite twice) failed with "email already exists," because `email` is globally unique across the whole `users` table. Fixed by giving the new tests the same uuid-suffix discipline `conftest.py`'s `signup()` fixture already used correctly. Reran twice in a row against the same already-populated database afterward to actually prove the fix, not just assume a fresh database happening to pass once meant it was fixed.

### How this was tested

Real local PostgreSQL, real server, every flow above run against genuine HTTP requests with the real token values extracted from actual server log output — not fabricated or assumed. Full pytest suite: **22 passed** (16 from every previous phase, unaffected, plus 6 new security regression tests), run twice in a row against the same persistent database to prove idempotency, not just a lucky first pass.

### Deploying this update

```bash
git add . && git commit -m "Phase 13: security hardening" && git push
```
**Before this deploy goes live, set a real `JWT_SECRET_KEY` in Render's environment variables** — generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. If it's still the placeholder text (or missing), the app will now correctly refuse to start rather than silently running insecurely — which is the point, but it does mean this is a required step before this specific deploy, not an optional one.

---

## PART 31 — A Real Privilege-Escalation Bug, Found Through Actual Use, Not Review

This one matters enough to be direct about: this was **not caught by any of this project's own testing, code review, or the "flag risky decisions" discipline this manual keeps claiming to follow.** It was found by the user actually deploying Phase 11b and clicking through it — building a role, testing what it could and couldn't do, and specifically testing the failure case (demoting themselves) that every prior phase's testing skipped. That's a real gap in how thoroughly Phase 11/11b were verified before being called done, and it's recorded here plainly rather than folded quietly into a routine bugfix entry.

### What was actually wrong

Two related problems, one root cause:

1. **No recovery path if the last Admin loses their role.** Every action that could change who has access — granting/revoking a permission, reassigning a user's role — was permitted purely based on whether the ACTING user's role allowed it, with zero consideration of what state the ORG would be left in afterward. A sole Admin demoting themselves (by accident, or via any role-management route) had no way back in — `/settings/roles` itself requires access to open, so once you're out, you're out, permanently, with no server-side or application-level recovery mechanism.

2. **`core.edit` alone granted full privilege escalation.** Granting/revoking permissions and reassigning a user's role were gated behind the exact same generic `create`/`edit`/`delete` checkboxes used for ordinary business-data edits everywhere else in the app. A role with `view`/`edit`/`approve` across every module — deliberately built to look like a *limited* admin, with `create` and `delete` withheld — could still freely call the role-change endpoint and promote its own holder straight to Admin. The checkbox grid gave no indication that `core`/`edit` was fundamentally different from `sales`/`edit`.

Root cause: the system had no concept of "controlling who has access" as its own kind of capability. It was just another `edit` action on another module, and the UI presented it as one checkbox among sixty with no visual distinction at all.

### The fix

**A new, dedicated capability: `core.manage_access`**, structurally separate from the standard view/create/edit/delete/approve grid — not a sixth column, a completely distinct concept. Only this specific permission now gates: granting or revoking any Permission on any Role, changing any User's role, and creating a user with a role assigned at creation time (closing an otherwise-obvious sidestep — assigning a powerful role at creation is functionally identical to "create, then change role", so it needed the same gate, not the weaker `core.create`).

**A server-side "last admin standing" guard**, implemented as flush → check → commit-or-rollback: the mutation is tentatively applied to the database session (not yet committed), then `org_has_admin_equivalent_user()` checks whether at least one active user org-wide would still hold `manage_access` afterward. If not, the entire operation is rolled back and rejected with a 400 — not a warning, an actual rejection — regardless of which of the three routes was used to try to get there. This closes the exact self-demotion scenario the user tested, and does it at the data-invariant level rather than as a special case bolted onto one specific route, so it can't be bypassed by finding a different route to the same end state.

**Self-healing for the deadlock this fix itself would otherwise create.** Every org that existed before this fix — including, right now, the one this was reported against — has an Admin role with zero rows for this brand-new capability. Enforced strictly with no accommodation, this would have permanently locked every existing Admin out of the very system meant to protect them: nobody could grant `manage_access` to anyone, because granting it now requires already having it. Extended the same self-heal pattern from Phase 11 (originally built for `custom_fields`/`notifications`) specifically for this case — an Admin role transparently receives `manage_access` the moment it's actually needed, no manual intervention required.

**UI**: `manage_access` is not a grid checkbox. It's a separate, prominently-bordered card above the permission matrix, changes color when granted, explains in plain language exactly what it does, and requires an explicit confirmation dialog before granting (revoking goes through the same server-side guard regardless, so the confirmation there is about intent, not safety).

### Verified against a real database, both exact scenarios from the report

```
SCENARIO 1 — the lockout:
Sole Admin, real signup, real manage_access seeded directly (not self-healed)
Attempt to change own role to a powerless role
  -> 400, "This action would leave the organization with no user able to
     manage roles and permissions..."
Confirmed via re-query: role genuinely still "Admin", not just an error shown

SCENARIO 2 — the escalation, recreated EXACTLY from the screenshot:
Role "Secondary_Admin": view+edit+approve on all 12 modules, no create/delete,
  no manage_access (identical configuration to the attached screenshot)
Confirmed this role CAN still edit ordinary business data normally (sales.view -> 200)
Attempt to change own role to Admin using only this configuration
  -> 403, "Your role 'Secondary_Admin' does not have 'manage_access' access to 'core'."
Attempt to grant itself ANY new permission (finance.delete) despite broad 'edit'
  -> 403, same reason
Confirmed via re-query: role genuinely still "Secondary_Admin"

POSITIVE CASE — the guard isn't overly restrictive:
A role holding REAL manage_access legitimately demotes the original Admin
  -> 200, succeeds (another admin-equivalent — themselves — still remains)
That same user, now the SOLE admin-equivalent, tries to revoke their own manage_access
  -> 400, rejected
Confirmed via re-query: permission genuinely still present, not just an error shown

SELF-HEAL — the deadlock this fix could have created for existing orgs:
Simulated a pre-fix org (deleted its Admin's manage_access row directly)
Real Admin hits any manage_access-gated route
  -> succeeds, self-heals, and the row is written back permanently
```
Every one of these was run with real HTTP requests against a real local Postgres database, not asserted from reading the code. 7 new permanent regression tests were added (`tests/test_rbac_privilege_escalation.py`) covering all of the above — full suite now **29 passed**.

### What this means for the org that reported it

Once this deploys, that real org's Admin role will self-heal `manage_access` automatically on first use of any affected route — no manual database work needed. The "Secondary_Admin" role already created during testing will need `manage_access` explicitly granted through the new UI control if it's meant to have real administrative power going forward; as configured in the screenshot, it correctly can no longer escalate itself, which was the point.

### Deploying this update

```bash
git add . && git commit -m "Fix: privilege escalation via core.edit, and last-admin lockout" && git push
```
No Alembic migration needed — this is a permission-data and route-logic change, not a schema change.

---

## PART 33 — Phase 14: Final Regression QA + Seeded Demo Organization + Walkthrough Script

The last item on the entire roadmap.

### Final regression QA

Fresh pytest database, full suite rerun clean: **29 passed** (every test from every phase, unaffected by anything in this final pass). Frontend: fresh `npm run build`, clean, all 16 pages. Both servers booted together, every one of the 15 frontend routes hit over real HTTP — each returned genuine, correctly-rendered HTML (empty states, forms, and cross-links all present and correct), not just a bare 200 status code. Backend `/health` reports `{"status": "ok", "database": "ok"}`.

### `backend/scripts/seed_demo_org.py`

Deliberately calls the **real API endpoints** — the same ones the frontend calls — not direct SQL inserts. This matters: it means every business rule (stock checks, journal-entry balancing, self-healing accounts, RBAC seeding) runs exactly as it would for a real user, so the seeded data is *guaranteed* internally consistent by construction, not just plausible-looking rows placed directly into tables.

Seeds one realistic organization ("Meridian Furnishings," a furniture company) touching every module: 5 products across 2 categories, a vendor with one received and one pending Purchase Order, 3 CRM leads (2 converted, 1 not), a full quote-to-cash cycle with one paid and one deliberately unpaid invoice, 3 employees with one pending and one approved leave request, a processed payroll run, an approval workflow with a request awaiting action, 2 custom fields defined and populated on real records, and a restricted "Sales Viewer" role with a real second login — a working RBAC demo, not just a description of one.

**Run twice in a row against the real server, proving it's genuinely safe to rerun** — each run makes a uniquely-subdomained org (timestamp-based) and never collides with a previous run or touches existing data. Both runs succeeded with zero failures across all 8 modules touched.

**Verified the actual data landed correctly**, not just that the script exited cleanly — logged in as the seeded admin and pulled the real dashboard summary:
```
leads: 3, open_opportunities: 2, quotations: 3, sales_orders: 2,
unpaid_invoices: 1, low_stock_products: 2, pending_purchase_orders: 1,
employees: 3, pending_leave_requests: 1, pending_approvals: 1
```
Every number matches what the script was designed to produce. One genuinely nice surprise, not scripted deliberately: `low_stock_products` came back as **2**, not the 1 that was explicitly designed in — the standing-desk purchase-and-sale sequence (8 received, 5 sold to Konnect Coworking) organically left exactly 3 units against a reorder level of 3, triggering a real low-stock flag as a *consequence* of the sale in the seed sequence, not a second hardcoded scenario. That's an honest, unplanned demonstration of the cross-module automation the whole platform is built on — noted in the walkthrough script as a talking point precisely because it wasn't staged.

### `DEMO_WALKTHROUGH.md`

A written, ordered walkthrough tied to the actual seeded data — no placeholder numbers, every figure in it is what the script above actually produces. Structured as roughly a 10-minute walkthrough: Dashboard → CRM pipeline → Sales quote-to-cash (both a paid and an unpaid ending, shown deliberately) → Inventory's low-stock story (including the organic second low-stock item, explained as it happens) → Procurement → Finance's balanced journal entries → HR/Payroll → Documents' generic approval engine → Custom Fields → Roles & Permissions (with a live login as the restricted Sales Viewer as the actual proof, not just a claim).

Also includes an honest "what this demo does *not* show" section — Projects & Tasks left deliberately unseeded (an empty, ready-to-configure module), email verification/password reset explained plainly as working but not yet connected to a real email provider, and RBAC's deeper protections (multi-tenancy isolation, privilege-escalation guards) noted as already tested rather than something to click through live, since those are better proven by the automated test suite than a live demo.

### Deploying this update

```bash
git add . && git commit -m "Phase 14: final regression QA, demo seed script, walkthrough script" && git push
```
No Alembic migration needed — this phase adds a script and a doc, no schema or route changes.

To seed a demo org against your real deployed instance:
```bash
python3 backend/scripts/seed_demo_org.py --api-url https://your-backend.onrender.com
```

---

## PART 34 — Project Status: Roadmap Complete

Every item on both tracks of `ERP_Remaining_Roadmap_and_Testing_Guide.md` is now done and tested:

**Demo-Ready:** Custom Fields (9), Notifications + prompt/confirm replacement (10a), shared components + mobile + pagination (10b).

**Client-Ready:** RBAC enforcement, backend and frontend (11, 11b) — including a real privilege-escalation and lockout fix found through actual deployed use, not caught in review. Automated testing + CI (12). Security hardening (13). Final regression QA + seeded demo org + walkthrough script (14).

This doesn't mean the system is "finished" in the sense a static website would be — real ERPs are continuously configured and extended, and this manual's own Part 1 said as much on day one. It means every phase originally scoped is complete, tested against a real database with real requests, and documented honestly, including the gaps found along the way and how each was actually closed.

What's genuinely still open, for the record, not because it's owed but because it's true: no real email provider is connected (password reset/verification work, delivery doesn't); Projects & Tasks has no demo data; and the deeper security-model changes from the privilege-escalation fix, while thoroughly tested, have not yet been exercised by a second human other than the person who found the original gap. Worth knowing before the first real client's data goes on this system, not because any of it is broken, but because "tested by the people who built it" and "tested by someone else" are genuinely different bars, and this project has always been honest about which one it's cleared.

---

## PART 35 — Production Incident: Login/Signup Broken After Deploying Phase 13 + Final

Found by the user through actual deployed use, with real evidence (browser console + Render's live logs), not by anything in this project's own testing — worth stating plainly, same as the privilege-escalation incident before it.

### What happened

After deploying the cumulative zip containing Phase 13's security hardening, login (and, less visibly, signup) broke in production. The browser console showed a CORS error; Render's actual backend logs showed the real cause underneath it: `sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedColumn) column users.email_verified does not exist`.

### Root cause, empirically confirmed — not assumed

Two things, both proven against a real local database, not inferred from reading code:

1. **The CORS error was a genuine red herring.** Reproduced directly: a normal successful request carries `access-control-allow-origin`; a request that throws an unhandled 500 carries **no CORS headers at all**, because Starlette's `ServerErrorMiddleware` sits outside `CORSMiddleware` in the stack — its fallback 500 response bypasses CORS header injection entirely. The browser accurately reports "no CORS header present" for a failure that has nothing to do with CORS.

2. **Phase 13's migration (`9f2fa35bb239`, adding `email_verified` and six related columns to `users`) never ran against the real Supabase database.** Reproduced by cleanly migrating a fresh local database only through the revision immediately before it, then hitting login: identical error, identical SQL, identical `sqlalche.me` reference link as the real production log. A related finding the user hadn't yet hit: **signup was equally broken** by the same root cause — the new-user INSERT's post-creation refresh touches those same missing columns.

### Why it didn't run automatically — a real gap in what this project delivered, not a one-off mistake

Two things, both confirmed by reading the actual files:

- **`backend/Dockerfile`'s `CMD`** had always been plain `uvicorn app.main:app ...` — the migration step was never actually added to it, despite every phase since Phase 5 referring to "the Start Command that's been `alembic upgrade head && uvicorn ...` since Phase 5" as an established fact.
- **`MANUAL.md`'s original Phase 1 deployment instructions (Part 3)** — the ones actually followed when the Render service was first created — still specified the Start Command as plain `uvicorn ...`, with no migration prefix. Every later phase's "Deploying this update" section talked about the corrected Start Command as if it were already in place, but none of them ever forced a concrete, mandatory "go update this one field in Render's dashboard right now" instruction — Phase 5's manual literally used the word "whenever convenient."

The honest conclusion: this was never actually fixed at the source, only described as fixed in later documentation that assumed an earlier fix which never happened. **Fixed now**: `Dockerfile`'s `CMD` includes the migration step as a real safety net, and Part 3's original instructions are corrected in place — not just referenced correctly later.

### The fix — verified end-to-end against a real database, not handed back untested

```
Fresh local Postgres, migrated only through the pre-Phase-13 revision (5ba8bc594079)
  -> signup: FAILS (same INSERT-refresh error)
  -> login:  FAILS (identical error to the real production log, confirmed byte-for-byte)

Ran the actual fix: alembic upgrade head
  -> all 7 missing columns confirmed present afterward

Booted the server fresh against this now-fixed database:
  -> signup a new org: 201, succeeds
  -> login with a real browser-matching Origin header: 200, succeeds,
     with the correct access-control-allow-origin header present this time
  -> confirmed zero orphaned/corrupted rows left behind by the earlier
     failed signup attempt - SQLAlchemy's transaction rolled back cleanly
```

### What to actually do

1. **Immediate, one-time:** run `alembic upgrade head` directly against the real Supabase database (Session Pooler connection, port 5432, per this project's established convention) — unblocks login/signup within seconds.
2. **Permanent:** in Render's dashboard, Settings → Start Command, change to `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. This is the one manual action needed — Render dashboard settings aren't part of the deployed codebase and can't be changed from a zip file.

Once both are done, every future `git push` runs migrations automatically before the server starts, and this exact class of incident becomes structurally impossible rather than just documented as something to remember.

---

## PART 36 — Real Email Delivery: Verification, Password Reset, and Enforcement

Closes the last honest gap flagged since Phase 13: password reset and email verification worked, but no real email ever left the server — everything landed in Render's logs, not an inbox.

### Provider choice — verified against current 2026 data, not assumed

**Resend, not SendGrid.** SendGrid killed its free-forever tier in May 2025 — it's now a 60-day trial (100/day) then **$19.95/month minimum**, which directly breaks this project's standing zero-cost constraint. Resend's free tier, confirmed across multiple current sources: **3,000 emails/month, 100/day, forever, no credit card.** Not a close call given the constraint.

One real limitation to know: without verifying a custom domain (a DNS step, not done here), Resend only delivers from its shared `onboarding@resend.dev` address to the *same email address used to create the Resend account*. Fine for now — no domain setup needed to get this working today — and it conveniently makes end-to-end testing simple, since it's your own inbox by construction.

### What changed

| Piece | What it does |
|---|---|
| `app/services/email.py` | Calls Resend's real API when `RESEND_API_KEY` is set; falls back to the original console-log behavior when it isn't — every test, CI run, and local dev session keeps working identically either way, no real key required anywhere except production. |
| `app/core/config.py` | New `RESEND_API_KEY` (optional, empty default — unlike `JWT_SECRET_KEY`, the app must still boot without it) and `FRONTEND_URL` (so emailed links point at your real deployed frontend, not `localhost`). |
| `app/api/routes/auth.py`'s `login` | Now enforces `email_verified` — a real, working reject with a clear message, not just a column nobody checked. |
| `app/api/routes/roles.py`'s `create_user` | Admin-created users (Settings → Users) are marked verified immediately, deliberately — an Admin directly creating a teammate's account is a different trust situation than a stranger's public self-signup; the Admin is vouching for the account, not the inbox. |
| `frontend/app/forgot-password/page.tsx` | New. Email input, always shows the same generic message regardless of whether the email exists (mirrors the backend's existing anti-enumeration behavior). |
| `frontend/app/reset-password/page.tsx` | New. Reads the token from the URL, sets a new password. |
| `frontend/app/verify-email/page.tsx` | New — and a genuine gap caught before shipping, not after: the verification email has always linked to `/verify-email`, but that page never existed. Anyone who clicked a real link would have hit a 404. Built now. |
| `frontend/app/login/page.tsx` | Added a "Forgot password?" link — it linked nowhere before. |
| `backend/scripts/grandfather_existing_users.py` | New, standalone, run once by hand — not folded into `alembic upgrade head`. |

### The self-lockout risk, caught before it shipped, not after

Turning on `email_verified` enforcement unconditionally would have immediately locked out every account that already exists — including the one just recovered from the last incident — since none of them ever had a real link to click. Caught this **before** running the test suite, by reasoning through it, not by the tests failing and then explaining it away: fixed with the grandfather script (a one-time, explicit, separately-run data correction — deliberately *not* bundled into the Alembic chain, so nothing email-related can silently ride along on a routine future deploy) plus marking admin-created users verified at creation.

### Real regression this reasoning also caught, proactively

Enforcing verification at login would have broken nearly the entire pytest suite — every test that creates a second user via `/api/core/users` and logs in as them (RBAC tests, security-hardening tests) would have started failing, since new users default to unverified. Fixed the same way as the production risk (mark admin-created users verified at creation) **before** running the suite, confirmed by then actually running it: **29 passed**, zero regressions.

### How this was tested — and the honest boundary of what I could prove myself

Real local Postgres, real server, every flow below run against genuine HTTP requests:
```
Signup -> verification email logged with the CORRECT FRONTEND_URL (not localhost)
Fresh login attempt before verifying -> 403, clear message
Verify using the real token extracted from the log -> 200
Login again -> 200, succeeds
Grandfather script: 2 unverified users -> updated to 2 verified -> 0 remain
Run the script a SECOND time -> correctly reports "nothing to do" (idempotent)
A previously-blocked pre-existing account -> logs in successfully after grandfathering
Full pytest suite -> 29 passed, zero regressions
Frontend: real npm run build, clean, 21 pages (3 new)
Both servers booted together: hit the EXACT verify-email link extracted from
  a real server log -> 200, real page, not a 404
/forgot-password, /reset-password -> both load; login page shows the new link
```

**What I could not test myself, and told you so before building rather than after:** Resend's API domain isn't reachable from this environment's network — I cannot make a real API call to it, and therefore cannot prove an email actually lands in a real inbox. Everything above proves the code is correct and the console-log fallback path works end-to-end; it does not prove real delivery. That step needs you.

### What you need to do

1. Sign up at resend.com with your real email (the same one you want test emails delivered to, per the no-custom-domain limitation above).
2. Dashboard → API Keys → Create API Key → copy it.
3. Render → Environment Variables → add `RESEND_API_KEY` with that value, and `FRONTEND_URL` set to `https://erp-project-dusky.vercel.app` (your real Vercel URL).
4. Deploy this update.
5. Run `backend/scripts/grandfather_existing_users.py` **once**, the same way you ran the Alembic fix — same `DATABASE_URL`, no `JWT_SECRET_KEY` needed for this particular script.
6. Trigger a real signup or a real "Forgot password?" request using your own email, and check your inbox. Tell me what actually arrived — that's the step only you can verify.

### Deploying this update

```bash
git add . && git commit -m "Real email delivery via Resend, verification enforcement, forgot/reset-password pages" && git push
```
No Alembic migration needed — confirmed zero schema drift. The grandfather script above is separate from this deploy and needs to be run once, by hand, either just before or just after.

---

## PART 37 — Closing a Real Gap: Self-Service Verification Resend

Found by the user thinking through an edge case ahead of time, not from a bug report — a real usability gap that would have hit an actual end user eventually: a link that expired, landed in spam, or was just closed without clicking, and nothing to do about it except ask a developer to manually touch the database.

### The fix

`POST /api/auth/resend-verification` — reuses signup's own token-issuing logic exactly, not a duplicate copy of it. That logic (`_issue_verification_token()`) was pulled out into its own function specifically so both signup and this new route call the identical code path: generate a fresh token, overwrite `verification_token_hash` (which implicitly kills the old one — only one hash can be "current" at a time, so no separate invalidation step is needed), and send it through the same `send_verification_email()` used everywhere else.

Same anti-enumeration discipline as `forgot-password`: a nonexistent email, an already-verified email, and a real pending one all return the byte-identical response.

Rate limited via a new `last_verification_email_sent_at` column and a flat 60-second cooldown — deliberately simpler than login's attempt-counting lockout, since this only needs to stop rapid re-triggering (someone mashing the button, or a script hammering an arbitrary email into the endpoint), not track a security-relevant attempt count. The cooldown response is the same generic message as everything else here — revealing "you're on cooldown" would itself confirm the email exists and is unverified.

Surfaced in two places a real user would actually find it: a persistent amber banner on the Dashboard (shown whenever `email_verified` is false — deliberately not a one-time post-signup message, which is easy to miss or forget) with its own working resend button, and a "Resend verification email" button that appears directly under login's existing unverified-403 error, so nobody's left reading an error message with no next step.

### A real subtlety, caught by testing before it could confuse anyone

Because signup now goes through the *same* shared `_issue_verification_token()` helper, signup itself counts as the first "verification email sent" for cooldown purposes — meaning a resend requested within 60 seconds of signing up is itself inside the cooldown window. First test run hit exactly this: both "old" and "new" tokens came back identical because the resend was silently rate-limited by signup's own timestamp. Not a bug — correct, intended behavior — but confusing enough on first encounter that it's worth documenting explicitly rather than leaving future-me to rediscover it the same way.

### Verified end-to-end, exactly as requested

```
Signup -> original token captured
Immediate resend request -> cooldown correctly blocks it (log entries stay at 1)
Backdate last_verification_email_sent_at by 2 minutes (simulating real time passing)
Resend again -> succeeds, genuinely different token confirmed
OLD token -> 400, dead
NEW token -> 200, "Email verified"

Anti-enumeration, all three real states return the IDENTICAL response:
  a real pending email, a nonexistent email, an already-verified email
  (confirmed via log count that the already-verified case triggers no real send)

Full pytest suite -> 34 passed (5 new, permanent regression tests added),
  zero regressions from the UserOut schema change (email_verified now exposed)
  or from routing signup through the shared helper

Frontend: real npm run build, clean, 21 pages
Both servers booted together: /dashboard and /login both 200
Confirmed the "Resend verification email" text is present in the actual
  compiled JS bundle for both pages, not just assumed from the source
```

**Same honest boundary as before:** everything above proves the mechanism is correct — token rotation, invalidation, rate limiting, anti-enumeration, and that both new UI affordances are actually shipped in the built bundle. It does not and cannot prove a real email lands in a real inbox, since Resend's API isn't reachable from this environment. That verification is still yours to do.

### Migration

One new column: `users.last_verification_email_sent_at`, nullable, no backfill risk (a genuinely new nullable column, not the NOT-NULL-on-a-populated-table mistake from earlier in this project). Confirmed zero drift after applying.

### Deploying this update

```bash
git add . && git commit -m "Self-service verification resend, closing a real edge-case gap" && git push
```
Render's Start Command already runs `alembic upgrade head` automatically now (from the earlier incident fix), so this migration applies itself on deploy — no manual step needed this time, unlike the last two updates.

---

## PART 38 — Invite-by-Email

Replaces the "Admin picks a new teammate's password directly" flow with a real invite: send an email, the invitee sets their own password by clicking a real link — the way onboarding actually works in a real product.

### Design — reusing the pattern already established twice, not a new concept

An invited user is a real row in `users` from the moment they're invited — a third `status` value (`"invited"`, alongside `"active"`/`"disabled"`), not a separate pending-invite table living somewhere else. Two new nullable columns (`invite_token_hash`, `invite_token_expires`) mirror the exact shape already used for email verification and password reset, plus `last_invite_email_sent_at` for its own dedicated resend cooldown — kept separate from the verification-resend cooldown on purpose, since an invited user never goes through the separate verification flow at all (accepting the invite *is* the verification — clicking a real emailed link already proves inbox ownership).

The existing direct-create-with-password endpoint (`POST /api/core/users`) was kept exactly as it was, not replaced — `seed_demo_org.py` and several tests depend on it, and it's still a legitimate way to create an account when you specifically don't want to wait on email (e.g., scripting). On the actual Settings → Users page, invite-by-email is the default, primary tab; direct creation is still there as a secondary option, not removed.

An invited user's `password_hash` is a hash of a random, unguessable placeholder — not a null column. This was a deliberate choice to avoid loosening `password_hash`'s existing `NOT NULL` constraint (a real schema change with its own risk, worth avoiding given this project's migration history) while still making it cryptographically impossible to log in with until `accept-invite` sets a real one.

### Endpoints

| Route | Gate | What it does |
|---|---|---|
| `POST /api/core/invites` | `core.manage_access` (same gate as changing anyone's role — assigning one at invite time is the same sensitive action) | Creates the invited user row, sends a real email with a 7-day link. |
| `POST /api/core/invites/{id}/resend` | `core.manage_access` | Admin-triggered, not self-service — the invitee has no working credentials yet to authenticate a resend request themselves. 60-second cooldown. |
| `POST /api/auth/accept-invite` | Public (no auth possible yet) | Sets the invitee's own password, flips `status` to `"active"` and `email_verified` to `true` together, auto-logs them in — same pattern as signup. |

Login blocks `status == "invited"` accounts with a clear, specific message ("hasn't been activated yet... check your email") rather than the generic wrong-password error — checked *before* password verification, since an invited account's placeholder password would fail that check unconditionally anyway, and a generic failure would leave them with no idea why.

### Verified end-to-end against a real server

```
Send invite -> real email logged with a working accept-invite link
Invitee attempts to log in before accepting -> 403, clear "not activated yet" message
Accept invite, set a real password -> 200, auto-logged-in, status: active, email_verified: true
A FRESH login (not the auto-login token) with their own chosen password -> 200
Reusing the same invite token again -> 400, dead

Resend: immediate attempt -> 429 (cooldown)
Backdate the cooldown -> resend succeeds, genuinely different token issued
OLD token -> 400, dead | NEW token -> works

Full pytest suite -> 41 passed (7 for the invite flow specifically), zero regressions
Frontend: real npm run build, clean, 22 pages (accept-invite new)
Both servers booted together: hit the EXACT accept-invite link extracted from
  a real server log -> 200, real page. Settings/Roles page -> 200.
```

### One process note worth recording

Backend and frontend routes, schemas, email service, migration, and the pytest suite for this feature were already fully built and present on disk when this phase started — this session's actual work was verifying every piece for real rather than trusting that "the code is there" meant "the code works," given this project's history with exactly that gap (Phase 8's untested Reports bug, the Phase 13 migration incident). That verification is what's recorded above — real signup, real invite, real accept flow, real token rotation, a fresh full test suite run, and a real full-stack HTTP check hitting the exact link a real email would contain.

### Deploying this update

```bash
git add . && git commit -m "Invite-by-email flow" && git push
```
One migration (`11388e004306`, three nullable columns) — applies itself automatically via Render's Start Command, no manual step needed.

---

## PART 39 — Recurring/Scheduled Jobs

Nothing in this app has ever run on its own — every action, until now, was triggered by a person clicking something. Closes that gap with two jobs: a daily overdue-invoice reminder and a weekly report digest.

### Mechanism — checked current pricing before choosing it, not assumed

Verified before building: **Render's own Cron Jobs feature is not free** — minimum $1/month per cron service, a genuinely separate paid service type from the free web service tier this project runs on. That rules out the obvious-looking "just use Render's cron" option.

This validates a decision this project's own Phase 1 manual already made and never built on: **GitHub Actions scheduled workflows**, free within generous limits, calling a dedicated backend HTTP endpoint on a timer. No always-on worker, no Redis/Celery (dropped back in Phase 1 for the same free-tier reason), no new paid infrastructure anywhere.

### A genuinely different kind of endpoint

Every route built until now is scoped to one logged-in user's org via their JWT. These two endpoints run triggered by GitHub's servers, with no human logged in, and need to act across *every* org in one call — so they're gated by a new shared secret (`CRON_SECRET`, checked via an `X-Cron-Secret` header) instead of `get_current_user`, living in their own router (`app/api/routes/scheduled_jobs.py`).

### The two jobs

| Job | Schedule | What it does |
|---|---|---|
| `POST /api/internal/jobs/overdue-invoices` | Daily | Finds every unpaid invoice past its due date, across every org, and sends one digest-style notification per org to that org's Admin(s) — reusing `notify_role()` exactly as-is, no new notification logic. |
| `POST /api/internal/jobs/weekly-digest` | Weekly | Pulls real numbers from the *existing* Reports service (`sales_summary`/`finance_summary` — the same functions the Reports page's live view calls) and emails a short summary to each org's Admin(s). |

**A real risk caught before it could ship:** the overdue-invoice job could easily have written `"overdue"` back onto `Invoice.status` — the model's own comment already anticipated that value. Checked first, and both the Dashboard and Finance report filter strictly on `status == "unpaid"` to build their unpaid-invoice counts; doing that would have made every overdue invoice silently vanish from both. Fixed by never writing to invoices at all — "overdue" stays a derived condition (`due_date < today AND status == "unpaid"`), computed fresh every run, matching this project's own long-standing "never store what you can calculate" principle. Verified directly: ran the job against a real overdue invoice and confirmed the Dashboard's and Finance report's unpaid counts were byte-identical before and after.

**A second real bug, caught by checking the actual source instead of trusting my own draft:** the weekly digest's first version read `total_revenue` from `sales_summary`'s output — a key that doesn't exist there at all (it's in `finance_summary`). Every real digest would have silently shown ₹0.00 for revenue, forever, with no error anywhere to reveal it. Caught by reading `reports.py`'s actual return dictionaries before trusting the draft, not by a test failure.

### Verified end-to-end against a real server, real invoices, real numbers

```
No secret header -> 401 | Wrong secret -> 401 | Correct secret, no data -> 200, zero counts

Real signup -> real product -> real stock -> real invoice, backdated 5 days overdue
Notifications before: 0
Run the job -> unread count: 1, message: "1 invoice(s) are now overdue, totaling 2,000.00..."
  (the exact real invoice amount, not a placeholder)

Dashboard's unpaid_invoices count, and Finance report's unpaid_invoice_count:
  BEFORE the job runs: 1  |  AFTER the job runs: 1  (unchanged, confirming no mutation)

Weekly digest, run for real across 19 accumulated test orgs:
  every logged digest showed the CORRECT, real revenue/profit/top-product
  numbers for that specific org, not zeros or placeholders

Full pytest suite -> 46 passed (5 new), zero regressions
```

### What you need to do

1. Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Add it to Render as `CRON_SECRET`.
3. Add the *same* value to GitHub: repo → Settings → Secrets and variables → Actions → New repository secret → `CRON_SECRET`.
4. Add one repo **variable** (not secret, since it's not sensitive): `BACKEND_URL` → your real Render URL, e.g. `https://erp-project-bceo.onrender.com`.
5. Deploy this update.

You can test the whole pipeline immediately without waiting for the schedule: GitHub → your repo → Actions tab → "Scheduled Jobs" workflow → **Run workflow** → pick either job → run it manually once, then check Render's logs for the real result.

### Deploying this update

```bash
git add . && git commit -m "Recurring scheduled jobs: overdue invoice reminders, weekly report digest" && git push

```
No Alembic migration needed — confirmed zero schema drift, this phase only adds routes, settings, and a GitHub Actions workflow file.

---

## PART 40 — Real File Uploads (Cloudflare R2) + Resend Cooldown Countdown

Two items, delivered together: Documents finally accepts a genuine file upload instead of only a pasted URL, and the "Resend verification email" button gets a real countdown — which also fixed a latent bug found while building the countdown.

### File uploads — provider choice verified against current 2026 data, not assumed

**Cloudflare R2, not S3.** R2's free tier is genuinely permanent — 10GB storage, 1M writes/10M reads per month, zero egress fees, forever. S3's free tier expires after 12 months and is smaller (5GB). One real friction point worth knowing: **Cloudflare requires a credit card on file to enable R2, even on the free tier** — you won't be charged unless you exceed the limits, but it's a different signup experience than Resend's zero-payment-info flow.

### Design — private bucket, nothing public, existing flow untouched

Documents can hold real business records (contracts, HR files, invoices) — treated as sensitive by default, matching this project's existing posture elsewhere (hashed tokens, RBAC on every route). The bucket is **private**; every download goes through a fresh presigned URL (10-minute expiry) generated on demand, never stored, since a stored one would just silently stop working later.

The original "paste a URL" flow (`POST /api/documents`) was left **completely untouched** — a new nullable `storage_key` column was added alongside the existing `file_url` (loosened to nullable, the safe direction for a schema change — no backfill needed, existing rows keep their real values). A real Document row has exactly one of the two, never both.

| Piece | What it does |
|---|---|
| `app/services/storage.py` | boto3 S3-compatible client pointed at R2's endpoint. `upload_file()` validates type/size before ever touching the network; `generate_presigned_url()` for downloads. |
| `POST /api/documents/upload` | Real multipart upload, gated by `documents.create` (same as the existing JSON route). |
| `GET /api/documents/{id}/download` | Gated by `documents.view`; the `org_id` filter in the query is the actual access-control boundary, not the storage key's org-scoped prefix. |
| Documents page | "Upload File" / "Paste a Link" toggle, matching the pattern already established for Settings → Users' "Send Invite" / "Set Password Directly." |

### A real bug caught by my own testing, not left for later

Testing with a deliberately malformed `R2_ACCOUNT_ID` crashed with a raw 500 instead of a clean error — `boto3.client()` raised a plain `ValueError` on the malformed endpoint URL, *before any network call even happened*, and the code only caught `botocore.exceptions.ClientError`, which is narrower than that. Fixed by broadening to a bare `except Exception`, matching `email.py`'s already-established pattern for external service calls — re-tested against the exact same failure and confirmed it now returns a clean 502 with a real, diagnosable message.

### A genuinely interesting, honestly-reported finding — not overclaimed

Testing with syntactically-valid-but-fake credentials got back a **real HTTP 403 with correctly-formatted S3 API error XML/JSON**, parsed cleanly by botocore into `"An error occurred (403) when calling the PutObject operation: Forbidden"`. That specific error shape strongly suggests this environment can actually reach Cloudflare's real R2 endpoint — a different, more favorable boundary than Resend's domain, which was flatly blocked at the network level every time. This wasn't chased further: real R2 credentials are sensitive, and asking for them to be pasted into a chat conversation isn't appropriate regardless of what the network boundary turns out to be. Full real-upload verification is still yours to do, same as email.

### Verified end-to-end, everything provable without real credentials

```
Unconfigured storage -> 503, clean, not a crash
Existing JSON "paste a URL" flow -> completely unaffected, file_url set, storage_key null
Disallowed file type (.exe) -> 400, rejected before ever touching storage.py
Oversized file (>10MB) -> 400, rejected before ever touching storage.py
Missing documents.create permission -> 403, same gate as the existing route
Malformed R2 credentials -> 502 with a real, diagnosable message (the bug fix above, re-verified)

Multi-tenancy: Org B attempts to download Org A's real document by ID -> 404
  (not "forbidden" - doesn't even confirm the document exists)
Org A, same document -> correctly passes the ownership check, reaches the storage-config boundary

Full pytest suite -> 52 passed (6 new for uploads), zero regressions
Frontend: real npm run build, clean, 22 pages, /documents grew exactly as expected
```

### Resend cooldown countdown — and a related bug it fixed

**A real latent bug, found while building the requested polish, not the polish itself:** the "Resend verification email" button never had any code path that reset it back to clickable — once clicked, it stayed permanently disabled for the rest of that page session, even long after the real 60-second server-side cooldown had passed. This existed in both places the button appears (the Dashboard's `VerificationBanner` and the login page's inline resend prompt).

Fixed both with a real countdown matching the backend's actual `RESEND_VERIFICATION_COOLDOWN_SECONDS = 60` value: shows "Resend in 47s" ticking down, then automatically returns to clickable at zero — rather than a generic "Sent" message with no indication of when trying again might actually work.

Verified the compiled production bundles for both `login` and `dashboard` genuinely contain the countdown logic, not just the source file.

### Deploying this update

```bash
git add . && git commit -m "Real file uploads via Cloudflare R2, resend-cooldown countdown fix" && git push
```
One migration (`56a6e2322d1a`) — applies itself automatically via Render's Start Command. To actually enable uploads: create an R2 bucket at dash.cloudflare.com, generate an API token, and add `R2_ACCOUNT_ID`/`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`/`R2_BUCKET_NAME` to Render's environment variables — until then, the upload button will show a clear "not configured yet" message rather than fail silently.

