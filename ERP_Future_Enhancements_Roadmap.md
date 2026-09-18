# Base ERP — Future Enhancements Roadmap

A working list of everything genuinely worth considering beyond the current build. Nothing here is required — this base is deliberately built to be shaped per client, and this document exists so that shaping is a decision, not a guess.

**Current state, for context:** all 10 core modules, RBAC (including a tested, closed concurrent-request race condition), dark mode, real gestures, global search, bulk actions, CSV import/export (proven on 2 modules each), 83 automated tests, real file uploads via Cloudflare R2, real email via Resend. Tested thoroughly by the builder and via real HTTP/API calls — **not yet by an independent reviewer, and not yet via automated browser testing.** Worth knowing before real client data goes on this system unsupervised.

---

## Security & Access

| Item | Why it matters | Effort |
|---|---|---|
| **2FA/MFA** | A real, meaningful addition given how much RBAC hardening already exists — closes the "password alone" gap. | Moderate |
| **SSO (Google/Microsoft login)** | Removes password management entirely for orgs that want it. A genuine architecture decision (how login/signup restructure around an identity provider), not a small add. | Large |
| **Session management** | Let a user see and revoke their own active login sessions. Natural extension of the password-reset work already built. | Moderate |
| **IP allowlisting per org** | Common enterprise ask — restrict login to known office/VPN IPs. | Moderate |
| **Password policy configuration** | Currently a fixed 8-character minimum, nothing configurable. Real orgs often want their own complexity/expiry rules. | Small–Moderate |
| **Field-level permissions** | RBAC currently gates at the *module* level (`hr.view`) — a role with HR view access sees every field, including salary. Real enterprises often want to hide specific sensitive fields per role. | Large — a genuine architecture extension |
| **New-device login alerts** | Email a user when their account is used from an unrecognized device/location — a real, standard security signal, cheap to build given email already works. | Small |

## Data & Compliance

| Item | Why it matters | Effort |
|---|---|---|
| **Data export/deletion tools** | A genuine "export everything for this org" or "delete my account" flow — relevant the moment this handles real client data seriously (GDPR-adjacent territory even outside the EU). | Moderate |
| **Configurable data retention** | Auto-archive or purge old records (stale notifications, audit log entries beyond N days) — the Audit Log currently keeps everything forever. | Small–Moderate |
| **PDF export** | Invoices and reports as real downloadable PDFs, not just CSV — the single most commonly expected "professional" output format for an ERP. | Moderate |
| **Multi-currency / configurable locale** | Currency (₹) and formatting are currently hardcoded throughout the frontend. A real blocker for any org operating outside India. | Moderate–Large |
| **Backup/restore tooling** | Supabase has its own backups, but a real point-in-time "restore this org to yesterday" tool inside the app itself is a different, more client-facing guarantee. | Large |

## Integrations

| Item | Why it matters | Effort |
|---|---|---|
| **Real payment gateway (Stripe/Razorpay)** | Actual invoice payment collection, not just recording that a payment happened after the fact. | Moderate–Large |
| **Calendar integration** | Sync leave requests, PO due dates, etc. to Google/Outlook calendar. | Moderate |
| **Accounting software sync** | QuickBooks/Tally export — relevant once Finance is used for real, not just demoed. | Moderate |
| **Public API + webhooks** | Let external tools subscribe to real events (invoice paid, PO received) instead of only the internal notification system. | Moderate–Large |
| **Slack/Teams notifications** | Post to a channel instead of, or alongside, in-app notifications. | Small–Moderate |
| **Zapier/Make.com connector** | A no-code alternative to raw webhooks — meaningfully lowers the bar for a non-technical client to build their own integrations. | Moderate (depends on the webhook work above existing first) |
| **E-signature on Documents approvals** | The generic approval-workflow engine already exists; adding a DocuSign-style signature step is a natural, high-value extension of something already built. | Moderate |

## Reporting & Analytics

| Item | Why it matters | Effort |
|---|---|---|
| **Real charts** | Reports currently show numbers; actual visual graphs (line/bar) are the natural next step. | Moderate |
| **Custom report builder** | Let an admin define their own saved report rather than picking from fixed types. | Large |
| **Scheduled report emails to specific people** | The weekly digest already exists org-wide (Part 39); per-user subscriptions would be a real but modest refinement. | Small |
| **Trend/forecast views** | "This month vs last month," basic pipeline-based sales forecasting — genuinely useful, moderate lift given the data already exists. | Moderate |

## Collaboration

| Item | Why it matters | Effort |
|---|---|---|
| **Comments/notes on records** | A running discussion thread on an Invoice, Lead, or Employee record. | Moderate |
| **Activity feed per record** | "Who touched this, when" surfaced directly on the record itself — built from the Audit Log that already exists, so genuinely lower-effort than it sounds. | Small–Moderate |
| **@mentions** | Tag a teammate into a comment or approval, triggering a real notification via the system already built. | Small (once Comments exist) |
| **Shared saved views/filters** | Let a team share a saved search/filter, not just personal ones. | Small–Moderate |

## Mobile & Offline

| Item | Why it matters | Effort |
|---|---|---|
| **PWA support** | Installable on a phone home screen, partial offline support. Meaningfully smaller than a native app, and a natural next step given the responsive/dark-mode/gesture work already done. | Moderate |
| **Real push notifications** | Actual device push (not just in-app) — needs PWA groundwork first. | Moderate (after PWA) |
| **Native mobile app** | A much bigger, genuinely separate project (React Native or similar) — not a natural "next phase" of this codebase. | Large, separate project |

## Operations & Reliability

| Item | Why it matters | Effort |
|---|---|---|
| **Automated browser testing (Playwright)** | Every UI claim in this project has been proven via real HTTP requests and compiled-output checks, never actual browser automation clicking through screens. A real, honestly-flagged gap. | Moderate |
| **Error tracking (Sentry or similar)** | Real errors currently only surface in Render's logs — a dedicated service catches and alerts much faster. | Small |
| **Uptime monitoring/alerting** | Get notified if the app goes down, rather than finding out when a client reports it. | Small |
| **Broader API rate limiting** | Only login currently has real rate limiting (Phase 13). Every other endpoint has none — fine for a demo, a real gap before high-traffic production use. | Moderate |
| **Load testing** | Nothing in this project has been tested under real concurrent load beyond the specific RBAC race-condition test — worth doing once real usage is expected. | Moderate |

## Onboarding & UX Polish

| Item | Why it matters | Effort |
|---|---|---|
| **Guided product tour** | Tooltips/walkthrough for a brand-new user's first login. | Moderate |
| **Configurable dashboard** | Let a user rearrange or hide module tiles, not just view the fixed grid. | Moderate |
| **In-app help center** | Searchable docs/FAQ inside the app itself, rather than relying on the demo walkthrough doc. | Moderate |
| **Multi-language / i18n** | Currently English-only. Real blocker for some client bases, irrelevant for others — worth a direct conversation before building. | Large |
| **Bulk field editing** | Change one field (e.g. status, assigned role) across many selected records at once — a natural sibling to the bulk delete/bulk role-assign already built. | Moderate |

## Admin & Configuration (not previously discussed)

| Item | Why it matters | Effort |
|---|---|---|
| **Plan/feature gating** | `Organization.plan` already exists as a field (`trial`/`basic`/`pro`) but nothing in the app actually enforces different features or limits per plan — it's decorative right now. Real monetization needs this wired up. | Moderate–Large |
| **White-labeling (custom domain)** | Org branding currently covers logo/background; a client-facing product would eventually want their own subdomain or custom domain, not just a shared one. | Large |
| **CSV import extended further** | Proven on Leads and Employees — Products, Vendors, and Customers are the natural next candidates, following the exact same pattern. | Small per module (mechanism already proven) |

---

## How to use this document

Nothing here is prioritized by default — priority should follow whatever a specific client actually asks for, not a generic "best practices" order. A reasonable way to use this list in a client conversation: show them the category headers first, let them point at what matters to *their* business, and only then discuss effort/sequencing for those specific items.
