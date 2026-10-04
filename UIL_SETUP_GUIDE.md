# Unified Intelligence Layer: Setup & Operations Guide

Ask questions in plain English ("Which invoices are overdue?") and get an answer grounded in your organization's own data, with the SQL shown. **Free tier only, read-only, tenant-isolated.**

---

## 0. Read this first

| | |
|---|---|
| **Cost** | $0. Google AI Studio free tier (Flash / Flash-Lite models only), no credit card. **Do not enable billing on that Google project**: that leaves the free tier. |
| **Privacy** | Free-tier prompts/responses **may be used by Google to improve its models and read by reviewers.** Use **synthetic data only**. Set `UIL_SEND_ROWS_TO_LLM=false` to keep result rows out of prompts entirely (you then get the verified table without a written summary). |
| **Limits** | Roughly 10-15 requests/minute plus a daily cap, **per Google project** (not per key). Your own AI Studio dashboard shows the real numbers. A question uses 2-5 requests; the page shows the count. |
| **Access** | Per user, through two ticks on the existing permission grid (see section 0b). By default only Admins can use it; everyone else needs a tick, and even then **only sees data from modules they can already open**. Salary and payroll need a second, separate tick. |
| **Writes** | Impossible by design (see section 5). |

---

## 0b. Who can ask about what: the two ticks

Ask Data never shows anyone more than the normal screens would. In **Settings → Roles & Permissions**, the **intelligence** row has two meaningful ticks (the other three are greyed out, since they mean nothing here):

| Tick | What it gives the role |
|---|---|
| **view** | Use Ask Data on the modules the role can **already open**. A role with Inventory can ask about stock; it cannot ask about HR, invoices or CRM. |
| **approve** | **Also** ask about restricted data: **salary and payroll**. Additional, never a substitute: it only works together with HR access. |

| Role holds | Can ask about |
|---|---|
| nothing on `intelligence` | nothing (the page refuses) |
| `intelligence.view` + Inventory | stock, products, warehouses |
| `intelligence.view` + HR | employees, departments, attendance, leave, **not** salary or payroll |
| `intelligence.view` + `approve` + HR | all of the above **plus** salary, payslips, payroll runs |
| `intelligence.view` + `approve` but **no HR** | whatever their other modules allow, **still no** salary or payroll |
| `approve` without `view` | nothing: `view` is what opens the feature |
| **Admin** | everything, automatically |

A data view is open to a role if it holds `view` on **any one** of the modules whose screens already show that data (so an Inventory-only user can still see product names). The full rule table is `ACCESS` in `app/services/intelligence/manifest.py`: one screen to audit.

Things to know:
- **Permissions apply to the next question.** Nothing is cached: ticking or unticking takes effect immediately, with no re-login.
- **A denial is final and quiet.** The user gets a plain message saying what is missing ("needs access to the HR module and the 'approve' permission on Ask Data") and **no rows and no SQL**.
- **Total payroll expense** is a ledger line that Finance users already see on their normal Finance report, so Finance users can ask about it. **Per-person pay** is what is restricted.
- Salary now lives in its **own** view (`employee_pay`), not inside `employees`, because your permissions work per module with no per-field control.

---

## 1. Local setup (no `.env` file: secrets are typed per session)

**How secrets are handled in this project:** nothing sensitive is stored in a file. On Render the values live in the dashboard's environment variables. Locally you type them into the terminal **for that session only**; closing the window clears them. The app reads the same settings either way.

| | Command Prompt | PowerShell |
|---|---|---|
| set | `set NAME=value` (no quotes, no spaces around `=`) | `$env:NAME = "value"` |
| clear | `set NAME=` | `Remove-Item Env:NAME` |

**One window per target.** The production incident came from a variable left set in a window. Name each window so you cannot mix them up: `title LOCAL erp_dev` (Command Prompt). Before any database command, check where you are pointing; this prints only the host and database, never the password:
```
python -c "from app.core.config import settings; from sqlalchemy.engine.url import make_url; u=make_url(settings.DATABASE_URL); print('HOST:', u.host, '| DATABASE:', u.database)"
```

**This release changes pinned dependencies** (`pydantic`, `httpx`, plus `sqlglot` and `google-genai`), because `google-genai` cannot coexist with the old pins:
```
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip check
```

1. **Two local databases** (pgAdmin, owner `erp_test`): create `erp_dev`; delete and recreate `erp_pytest_db`.

2. **Run the tests.** The tests create their own throwaway database login, so your `erp_test` login must be a superuser (it is). The settings only need to be *valid*; the tests use their own database:
   ```
   set DATABASE_URL=postgresql://erp_test:erp_test@localhost:5432/erp_dev
   set JWT_SECRET_KEY=<any long random value>
   python -m pytest -q
   ```
   Generate a value with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. For local use a fresh one each session is fine (it only logs your local sessions out). The app refuses placeholder or empty values. Expect everything to pass except, possibly, one known Windows-only concurrency test.

3. **Create the tables and the read-only login** (same window, still pointing at `erp_dev`; run the check above first):
   ```
   alembic upgrade head
   set UIL_DB_PASSWORD=uil_test_password_123
   python scripts/setup_uil_role.py
   ```
   It prints the target and makes you type `erp_dev`. **Why that password:** a login role is shared by the whole local Postgres, and every test run resets `uil_readonly` to this password. Using it locally avoids a mysterious password error after each test run. It is a throwaway for local use only; **production gets its own strong password.**

4. **Get a free Gemini key** from <https://aistudio.google.com> (a Google account with **no billing attached**). Then, in the same window:
   ```
   set GEMINI_API_KEY=<your key>
   set UIL_DATABASE_URL=postgresql://uil_readonly:uil_test_password_123@localhost:5432/erp_dev
   ```

5. **Seed synthetic demo data, then the real-Gemini smoke test:**
   ```
   python scripts/seed_uil_demo_data.py --subdomain acme-demo
   python scripts/uil_smoke_test.py --quick
   ```
   Log in as `admin@acme-demo.example.com` / `DemoPass123!`. The smoke test takes a few minutes because it paces itself for the free tier.

6. **Run the app.** Backend, in the same window:
   ```
   uvicorn app.main:app --port 8000
   ```
   Frontend, in a **second** window (the URL is public, not a secret):
   ```
   cd frontend
   set NEXT_PUBLIC_API_URL=http://localhost:8000
   npm install
   npm run dev
   ```
   Open **Ask Data** from the dashboard.

7. **Try the two ticks.** Create a role with only `intelligence → view` and `inventory → view`, add a user in **password mode** (no email needed), log in as them in a private window, and confirm stock questions work while salary questions are denied. Then tick `hr → view` and `intelligence → approve` and ask again.

---

## 2. Production (Render + Supabase + Vercel): do it in THIS order

1. **Push.** Render runs `alembic upgrade head` on start. This release has **two** UIL migrations: the first creates the `uil` schema and views; the second adds the per-user access control and **drops and recreates every view** (to split salary out of `employees`). If you already ran `setup_uil_role.py` for an earlier release, the migration re-grants to the read-only login itself, so there is no gap. Watch the first deploy log: the dependency upgrade is the part to look at.
2. **Create the login against Supabase.** In a **fresh, dedicated window** (`title PROD supabase`), set `DATABASE_URL` to your *privileged* Supabase string and `UIL_DB_PASSWORD` to a NEW strong password (`set NAME=value` in Command Prompt, `$env:NAME = "value"` in PowerShell), then run `python scripts/setup_uil_role.py`. **Read the printed host and database before typing the name**, and close that window when you are done so nothing lingers.
3. **Set Render environment variables:** `GEMINI_API_KEY`, `UIL_DATABASE_URL`.
4. **Pooler login format (UNVERIFIED).** On Supabase's pooler, a custom role may need the username `uil_readonly.<project-ref>`. If the login check in step 2 fails or the page says it cannot connect, try that form. If neither works, tell the assistant the exact error.
5. **Seed a synthetic demo org** only. Never point this at real client data on the free tier.
6. **Smoke test** from your laptop with the production env vars set.
7. Existing orgs need no backfill: the `intelligence` permission **self-heals** on first use for Admin roles, the same way every module added after launch has.

---

## 3. Changing what the AI can see

`app/services/intelligence/manifest.py` is the single source of truth. To add or change a view:
1. Edit the manifest, 2. add a **new** Alembic migration that creates/alters the matching view (never edit the old one), 3. re-run `scripts/setup_uil_role.py` (it re-asserts grants and removes access to anything dropped).

`tests/test_uil_manifest.py` fails if the manifest and the database's real views ever disagree, and fails if any column that looks sensitive (password, token, hash, secret, email, phone, org_id, storage key) is added.

Deliberately **not** exposed: `password_hash`, every `*_token_*` column, emails and phone numbers, audit logs, roles/permissions, notifications, documents/storage keys, report subscriptions.

---

## 4. Troubleshooting

| You see | Meaning / fix |
|---|---|
| `503 ... GEMINI_API_KEY` | Key not set on the server. Checked **before** spending any quota. |
| `503 ... UIL_DATABASE_URL` | Login not configured; run `setup_uil_role.py`. |
| `403 ... intelligence` | Role lacks `intelligence.view`. Grant it in Settings → Roles. |
| "free Gemini quota is exhausted" | You hit the per-minute or daily cap. Wait a minute; it will not recover by retrying faster. |
| "key was rejected" | Wrong/revoked `GEMINI_API_KEY`. Not retried (retrying a bad key only burns quota). |
| "no matching data" | The query ran and found nothing (or an aggregate over nothing). The AI is never asked to guess. |
| "Could not build a safe query" | The model's SQL was rejected twice. Rephrase more specifically; the page shows the rejected SQL and the reason. |
| `permission denied for function current_org` / `can_read` | The role is missing an `EXECUTE` grant. Re-run `setup_uil_role.py`. |
| "You don't have access to that data. It needs …" | The role lacks a module tick or the `approve` tick. The message says which. Fix it in Settings → Roles & Permissions; it applies on the next question. |
| A user sees "Your role has no data modules yet" | They hold `intelligence.view` but no module tick. Give the role the module(s) they should be able to ask about. |

---

## 5. The security model (two independent layers)

**Layer 1: application (`safety.py`).** The AI's SQL is *parsed*, not keyword-matched, and must be exactly one `SELECT` reading only the listed views, using only allow-listed functions. `set_config`, `pg_sleep`, `lo_import`, `generate_series`, `SELECT … INTO`, `FOR UPDATE`, multiple statements and every other write/DDL are rejected by default. What actually runs is regenerated from the validated tree, schema-qualified, with a hard row cap.

**Layer 2: the database itself.** Queries run as `uil_readonly`, which can only `SELECT` the curated views: no write grant, `default_transaction_read_only = on`, no access to `public` (so `users.password_hash` is unreachable, not merely hidden), a statement timeout, and a small connection limit.

**Tenant isolation.** Every view filters on `uil.current_org()`, which reads the organization registered for *this connection's backend PID* in a table only the application login can write. Unlike the common "session setting + row-level security" pattern, that value cannot be changed by a query calling `set_config()`. No registration means **zero rows** (fail closed). No `org_id` column is exposed, so the model cannot even attempt to filter by one.

Both layers are tested independently: the database layer is attacked directly with **no validator in the way** (tests/test_uil_database_layer.py), and the validator is tested separately (tests/test_uil_safety.py).

**Per-user access is enforced in three independent places**, so a bug in one cannot leak data: the prompt (the model is only *told about* views the user may read, so a basic user's prompt never even contains the salary columns), the SQL validator (naming any other view gives a clear denial), and **the database itself**. The database layer is the one that matters most: the user's modules and approval are registered for the connection in a table only the application can write, and every view re-checks them through `uil.can_read()`, so even a query that slipped past the first two gets **zero rows** for data the user may not read. The tests deliberately disable the first two layers and confirm the database still holds.

**Honest limits.**
- The model can still ask a *wrong-but-valid* question, so the SQL is always shown. Written summaries have every number checked against the returned rows; an ungrounded figure discards the prose and shows the table.
- Text stored in your data is sent to the model when summaries are on. The prompt fences it as data, but treat that as mitigation, not a guarantee.
- Access is per **role** (like every permission in this app), not per individual; to give one person access, give their role the tick.
- Access is by **module**, not by individual field: that is why salary had to move into its own view. Anything else you later decide is sensitive should be split the same way.
- Admin is recognised by role **name** (the same rule your global search uses).
- Quota is per Google project. Several users sharing one demo will hit the per-minute cap.
