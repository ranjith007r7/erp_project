# Base ERP — Manual Testing & Debugging Checklist

Two kinds of testing matter here, and they catch different things:

1. **Automated** — catches broken code, security holes in dependencies, regressions. Fast, repeatable, already partly set up (see Part 1).
2. **Manual** — catches "this button doesn't do what a human expects," "this looks wrong on my phone," "this flow is confusing." Nothing automated in this project does this yet (see Part 2 for why, and the real gap that leaves).

Do both. Automated tools won't catch a confusing UI; manual clicking won't catch a SQL injection risk in a dependency you've never heard of.

---

## Part 1 — Automated checks (run these first, they're fast)

### Backend

```bash
cd backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
export DATABASE_URL="postgresql://..."   # your real Supabase connection string
export JWT_SECRET_KEY="..."
python -m pytest -v
```
**What it catches:** business logic bugs, RBAC/permission holes, multi-tenancy leaks (data from one org showing up in another), broken calculations (payroll math, invoice totals, journal entries). 83 tests currently, all passing as of this build.

```bash
pip install pip-audit
pip-audit -r requirements.txt
```
**What it catches:** known security vulnerabilities in the libraries you depend on. Run this every few months even after this project is "done" — new CVEs get discovered in existing library versions all the time.

### Frontend

```bash
cd frontend
npm run build
```
**What it catches:** broken code that would crash in production — syntax errors, missing imports, type mismatches. If this fails, something is genuinely broken; it should never fail on a clean checkout of this project.

```bash
npm run lint
```
**What it catches:** real code-quality issues — the kind of thing that can hide actual bugs (an unescaped character, a missing dependency in a React hook). Set up fresh this session; should show "No ESLint warnings or errors."

```bash
npm audit
```
**What it catches:** known vulnerabilities in frontend dependencies. Same reasoning as `pip-audit` — rerun periodically going forward, not just once.

### What automated tools do NOT check in this project (the real gap)

No browser automation (Playwright/Cypress) exists here. That means nothing automated ever actually clicks a button, fills a form, or looks at a rendered page the way a human does. Everything below in Part 2 is covering for that gap — until real browser automation exists, this manual pass is the only thing standing between "the code compiles" and "the product actually works."

---

## Part 2 — Manual end-to-end testing, step by step

Do this as one continuous session per section, using a real deployed instance (Render + Vercel), not just your local machine — some things (real email delivery, real file uploads) only work with real credentials configured.

### 2.1 — Fresh signup → first login

- [ ] Sign up with a brand-new org (use a throwaway email you control, so you can check the actual verification email).
- [ ] Confirm the success screen and toast appear before redirecting — not an instant silent jump to Dashboard.
- [ ] Log out, try logging back in with the correct password — should work.
- [ ] Try logging in with a wrong password — should show a clear error, not a blank screen or raw JSON.
- [ ] Try signing up again with the same subdomain — should show a clear "already taken" message.

### 2.2 — Email flows (needs real Resend credentials configured)

- [ ] Check your inbox for the verification email — click the link, confirm your account shows as verified.
- [ ] Use "Forgot password," confirm you receive a reset email, follow it through, confirm the new password actually works.
- [ ] From Settings → Roles & Permissions, invite a second real email address as a user — confirm they receive an invite email, can accept it, and set their own password.

### 2.3 — RBAC — the most important thing to get right before a client sees this

- [ ] As Admin, create a new role with only 1–2 permissions (e.g., `sales.view` only).
- [ ] Create a second user with that restricted role.
- [ ] Log in as that user — confirm they genuinely cannot see or act on modules they don't have permission for (not just that the nav link is hidden — try navigating directly to the URL).
- [ ] Try to demote yourself (the only Admin) to a role with no `manage_access` — confirm the app refuses and explains why.
- [ ] Grant `manage_access` to the second user, then have that user try the same self-demotion — confirm it's still blocked correctly.

### 2.4 — Every core module, one full create → use → complete cycle

For each of these, don't just create a record — walk it through its *entire* real lifecycle:

- [ ] **CRM**: Create a Lead → convert it to an Account + Opportunity.
- [ ] **Sales**: Create a Product and Customer → build a Quotation → accept it into a Sales Order → generate an Invoice.
- [ ] **Inventory**: Confirm the Product from Sales shows up with correct stock levels; check a Stock Movement was recorded.
- [ ] **Procurement**: Create a Vendor and Purchase Order → receive it → confirm Inventory stock increased and a real notification fired.
- [ ] **Finance**: Record a payment against the Sales invoice → confirm it shows as paid, and a Journal Entry was created with correct debits/credits.
- [ ] **HR**: Create a Department and Employee → submit a Leave Request → approve it → run Payroll for that employee → process it.
- [ ] **Projects**: Create a Project and Task → log time against it → mark it done.
- [ ] **Documents**: Upload a real file (needs R2 configured) → download it back → confirm it's the same file. Separately, create an Approval Workflow → submit a request → approve it through every step.
- [ ] **Reports**: Check that numbers shown here actually match what you just created across the modules above — this is the easiest place for a silent calculation bug to hide.

### 2.5 — Cross-cutting features

- [ ] **Global Search**: search for something you know exists in 2+ modules — confirm results appear grouped correctly, and clicking one takes you to the right page. Confirm the "See all results" page works for a broad term with many matches.
- [ ] **Bulk actions**: select multiple Leads, bulk-delete them; select multiple Documents, bulk-delete them; select multiple users, bulk-assign a role.
- [ ] **CSV**: export Leads and Employees to CSV, open the files, confirm the data is real and correct. Re-import a CSV with one deliberately bad row (blank name) — confirm the good rows still import and the bad one is reported with the right line number.
- [ ] **Audit Log**: after doing the above, check Settings → Audit Log — confirm your actions (role changes, deletions, payments) show up with your name and a correct timestamp.
- [ ] **Notifications**: confirm the bell icon shows a real unread count, and clicking a notification behaves sensibly.

### 2.6 — Appearance & theme

- [ ] Toggle dark mode on every page you touched above — check specifically for any text that's hard to read or invisible (this has been a real, repeated bug class in this project — worth being thorough here).
- [ ] As Admin, upload a custom background image in Settings → Appearance — confirm it shows up for a *different*, non-admin user in the same org (proves it's genuinely org-wide, not just showing for you).
- [ ] Confirm a restricted-role user can see the background but cannot change or remove it.

### 2.7 — Mobile / responsive

- [ ] Open the app on an actual phone (not just a resized desktop browser window) — check that every page above is usable, not just "doesn't look broken."
- [ ] Try the swipe-to-delete gesture on a CRM lead, and pull-to-refresh on the Dashboard — confirm both actually work on a real touchscreen, not just in theory.

### 2.8 — Error handling / edge cases

- [ ] Submit a form with a required field left blank — confirm you get a clear message, not raw JSON or a silent failure.
- [ ] Try an action you know should be blocked (e.g., a restricted role attempting a bulk delete) — confirm the error is clear, not a crash.
- [ ] Turn off your wifi mid-action (e.g., while submitting a form) — confirm the app shows a reasonable error rather than hanging forever or showing nothing.

---

## Part 3 — A simple bug-tracking habit while you test

As you go through Part 2, keep a running list (a spreadsheet or even a plain text file) with four columns:

| What you did | What you expected | What actually happened | Screenshot? |
|---|---|---|---|

This is genuinely more useful than "I found some bugs" — a specific reproduction step is the difference between a bug getting fixed in one pass versus five rounds of "can you clarify what you mean."

---

## Part 4 — When you're ready to move to demo-prep

Once Part 1 is clean and you've gotten through Part 2 without any blocking issues (small polish issues are fine — genuinely broken flows are not), that's the real signal you're ready. Bring me the bug list from Part 3 if you found anything, and separately, we can move into how to actually present this to a client and how to talk through customization — that's a different kind of conversation and deserves its own focused pass rather than being squeezed in at the end of this one.
