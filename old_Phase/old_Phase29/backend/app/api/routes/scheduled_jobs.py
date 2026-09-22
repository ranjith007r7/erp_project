"""
Two jobs, both triggered externally by a GitHub Actions scheduled
workflow (.github/workflows/scheduled-jobs.yml), not by any logged-in
user - this is the free alternative to a paid always-on worker or
Render's paid Cron Jobs feature (checked current pricing before building
this: Render's own Cron Jobs start at $1/month minimum, no free tier).

Both loop across EVERY organization in one call, unlike every other
route in this app, which is scoped to one org via the caller's JWT -
there is no JWT here, since nobody is logged in when GitHub's servers
trigger this on a timer.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import verify_cron_secret
from app.models.organization import Organization
from app.models.sales import Invoice
from app.models.user import User
from app.models.role import Role
from app.services.notifications import notify_role
from app.services.reports import sales_summary, finance_summary
from app.services.email import send_email

router = APIRouter(prefix="/api/internal/jobs", tags=["scheduled-jobs"], dependencies=[Depends(verify_cron_secret)])


@router.post("/overdue-invoices")
def check_overdue_invoices(db: Session = Depends(get_db)):
    """
    Runs daily. 'Overdue' is deliberately never written back to
    Invoice.status - both the Dashboard and Finance report filter
    strictly on status == "unpaid" to build their unpaid-invoice counts;
    changing an overdue invoice's status would make it silently vanish
    from both. 'Overdue' stays a derived condition, computed fresh every
    run: due_date has passed AND status is still "unpaid" - matching
    this project's own long-standing "never store what you can
    calculate" principle.

    One notification per ORG, not per invoice - a daily digest, not a
    flood. Intentionally sent again every day an invoice stays overdue
    (no dedup/suppression) - that's correct behavior for something
    called a reminder, not a bug.
    """
    today = date.today()
    overdue = (
        db.query(Invoice)
        .filter(Invoice.status == "unpaid", Invoice.due_date.isnot(None), Invoice.due_date < today)
        .all()
    )

    by_org: dict[str, list[Invoice]] = {}
    for inv in overdue:
        by_org.setdefault(str(inv.org_id), []).append(inv)

    orgs_notified = 0
    for org_id, invoices in by_org.items():
        total = sum(float(inv.amount) for inv in invoices)
        message = (
            f"{len(invoices)} invoice(s) are now overdue, totaling {total:,.2f}. "
            f"Check Finance > Invoices for details."
        )
        notify_role(db, org_id, "Admin", message)
        orgs_notified += 1

    db.commit()
    return {"orgs_with_overdue_invoices": len(by_org), "orgs_notified": orgs_notified, "total_overdue_invoices": len(overdue)}


@router.post("/weekly-digest")
def send_weekly_digest(db: Session = Depends(get_db)):
    """
    Runs weekly. Emails each org's Admin(s) a short summary using the
    SAME reports service the Reports page's live view already calls -
    no separate calculation logic to keep in sync with the dashboard.
    Soft-fails per org (a bad email for one org must not stop every
    other org's digest from sending) - same philosophy as
    notify_user()/notify_role()'s soft-fail.
    """
    orgs = db.query(Organization).all()
    sent_count = 0

    for org in orgs:
        org_id = str(org.id)
        try:
            sales = sales_summary(db, org_id, months=1)
            finance = finance_summary(db, org_id, months=1)
        except Exception:
            continue  # a data issue in one org's numbers must not break every other org's digest

        admins = (
            db.query(User)
            .join(Role, User.role_id == Role.id)
            .filter(User.org_id == org_id, Role.name == "Admin", User.status == "active")
            .all()
        )
        if not admins:
            continue

        body = (
            f"Weekly summary for {org.name}\n\n"
            f"Revenue (this month so far): {finance.get('total_revenue', 0):,.2f}\n"
            f"Net profit (this month so far): {finance.get('net_profit', 0):,.2f}\n"
            f"Top product: {sales.get('top_products', [{}])[0].get('name', 'N/A') if sales.get('top_products') else 'N/A'}\n\n"
            f"Log in to see the full report."
        )
        for admin in admins:
            send_email(to=admin.email, subject=f"Weekly summary — {org.name}", body=body)
        sent_count += 1

    return {"orgs_processed": len(orgs), "digests_sent": sent_count}
