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

## PART 9 — What's Next

**Before Phase 5 feature work resumes, the next task is adopting Alembic migrations properly** — this closes the schema-change bug category for good, the same way self-healing closed the missing-default-row category in Finance. After that, Phase 5 will build **HR & Payroll**, which is largely self-contained (it doesn't hand off to Sales/Procurement the way Finance and Inventory do), making it a good "breather" phase before **Projects & Tasks**, **Documents & Workflow Approvals**, and finally **Reports & Analytics** close out the original module list. This section keeps growing with each phase — nothing above gets deleted, only added to.
