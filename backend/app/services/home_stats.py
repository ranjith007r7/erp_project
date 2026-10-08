"""
Numbers for the analytics home page and the daily / weekly / monthly reports.

Nothing here is stored. Every figure is computed from the live tables for a time
window in the ORGANIZATION'S timezone (Organization Profile; default
Asia/Kolkata), so "today" rolls over at that organization's midnight - this is
what makes the home page "reset every day" without any job or data deletion.

Who sees what
- A card is returned only if the user has `view` on the module it comes from
  (otherwise the key is null and the page hides the card).
- Admins (core.manage_access) see organization-wide work and task numbers.
  Everyone else sees works of their own department or allocated / created by
  them, and only tasks assigned to them.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import user_has_permission
from app.models.crm import Lead
from app.models.finance import Payment
from app.models.hr import Department, Employee
from app.models.organization import OrganizationProfile
from app.models.procurement import PurchaseOrder, Vendor
from app.models.projects import Project, Task
from app.models.sales import Quotation
from app.models.user import User
from app.models.workpage import WorkOrder, WorkPayment
from app.services import workpages as wp

PERIODS = ("today", "week", "month")


def org_tz(db: Session, org_id) -> ZoneInfo:
    name = db.query(OrganizationProfile.timezone).filter(OrganizationProfile.org_id == org_id).scalar()
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Kolkata")


def local_today(tz: ZoneInfo) -> date:
    return datetime.now(timezone.utc).astimezone(tz).date()


def window(period: str, on: date) -> tuple[date, date]:
    """[first day, last day] inclusive."""
    if period == "today":
        return on, on
    if period == "week":
        start = on - timedelta(days=on.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        start = on.replace(day=1)
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, nxt - timedelta(days=1)
    raise ValueError("period must be today, week or month")


def _utc(d: date, tz: ZoneInfo) -> datetime:
    """Local midnight of `d` as naive UTC (how created_at columns are stored)."""
    return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def _can(db, user, module) -> bool:
    return user_has_permission(db, user, module, "view")


def _is_admin(db, user) -> bool:
    return user_has_permission(db, user, "core", "manage_access")


def _money(v) -> float:
    return float(Decimal(v or 0).quantize(Decimal("0.01")))


def _my_employee(db, user):
    return db.query(Employee).filter(Employee.org_id == user.org_id, Employee.user_id == user.id).first()


def _visible_works(db: Session, user: User, org_id):
    q = db.query(WorkOrder).filter(WorkOrder.org_id == org_id)
    if _is_admin(db, user):
        return q
    emp = _my_employee(db, user)
    conds = [WorkOrder.created_by == user.id]
    if emp:
        conds.append(WorkOrder.allocated_employee_id == emp.id)
        if emp.department_id:
            conds.append(WorkOrder.handling_department_id == emp.department_id)
    from sqlalchemy import or_
    return q.filter(or_(*conds))


def _income_rows(db: Session, org_id, lo: datetime, hi: datetime, show_work: bool, show_fin: bool):
    rows = []
    if show_work:
        rows += [(c, Decimal(a)) for a, c in db.query(WorkPayment.amount, WorkPayment.created_at)
                 .filter(WorkPayment.org_id == org_id, WorkPayment.created_at >= lo, WorkPayment.created_at < hi)]
    if show_fin:
        rows += [(c, Decimal(a)) for a, c in db.query(Payment.amount, Payment.created_at)
                 .filter(Payment.org_id == org_id, Payment.created_at >= lo, Payment.created_at < hi)]
    return rows


def compute(db: Session, user: User, period: str = "today", on: date | None = None) -> dict:
    org_id = user.org_id
    tz = org_tz(db, org_id)
    today = local_today(tz)
    on = on or today
    first, last = window(period, on)
    lo, hi = _utc(first, tz), _utc(last + timedelta(days=1), tz)

    can_work, can_fin = _can(db, user, "workpage"), _can(db, user, "finance")
    can_sales, can_proc = _can(db, user, "sales"), _can(db, user, "procurement")
    can_proj, can_crm = _can(db, user, "projects"), _can(db, user, "crm")
    admin = _is_admin(db, user)

    out: dict = {
        "period": period, "from": first, "to": last, "today": today, "timezone": str(tz),
        "scope": "organization" if admin else "mine",
        "generated_at": datetime.now(timezone.utc),
    }

    # ---- income
    income = None
    if can_work or can_fin:
        rows = _income_rows(db, org_id, lo, hi, can_work, can_fin)
        income = {"total": _money(sum((a for _, a in rows), Decimal(0))), "payments": len(rows)}
    out["income"] = income

    # ---- quotes processed
    out["quotes"] = None
    if can_sales:
        qs = db.query(Quotation).filter(Quotation.org_id == org_id, Quotation.created_at >= lo, Quotation.created_at < hi).all()
        out["quotes"] = {"processed": len(qs), "accepted": sum(1 for x in qs if x.status == "accepted"),
                         "value": _money(sum((x.total or 0 for x in qs), Decimal(0)))}

    # ---- PO raised
    out["purchase_orders"] = None
    if can_proc:
        pos = db.query(PurchaseOrder).filter(PurchaseOrder.org_id == org_id, PurchaseOrder.created_at >= lo, PurchaseOrder.created_at < hi).all()
        out["purchase_orders"] = {"raised": len(pos), "value": _money(sum((p.total or 0 for p in pos), Decimal(0))),
                                  "awaiting_approval": db.query(PurchaseOrder).filter(PurchaseOrder.org_id == org_id, PurchaseOrder.approval_status == "pending").count()}

    # ---- works / deals / deliveries
    out["works"] = out["deals"] = out["deliveries"] = None
    out["work_status"] = []
    out["recent_works"] = []
    if can_work:
        base = _visible_works(db, user, org_id)
        allw = base.all()
        in_w = [w for w in allw if w.created_at and lo <= w.created_at < hi]
        delivered = [w for w in allw if w.delivered_on and first <= w.delivered_on <= last]
        closed = [w for w in allw if w.closed_at and lo <= w.closed_at < hi]
        pending = [w for w in allw if w.status != "closed"]
        out["deals"] = {"new": len(in_w), "value": _money(sum((w.quotation_amount for w in in_w), Decimal(0)))}
        out["deliveries"] = {"delivered": len(delivered), "awaiting_delivery": sum(1 for w in allw if w.status in ("po_received",))}
        done_ids = {w.id for w in delivered} | {w.id for w in closed}
        out["works"] = {"assigned": len(in_w), "completed": len(done_ids), "pending": len(pending)}
        counts = {k: 0 for k in wp.STATUSES}
        for w in allw:
            counts[w.status] += 1
        out["work_status"] = [{"key": k, "label": v["label"], "color": v["color"], "count": counts[k]} for k, v in wp.STATUSES.items()]
        for w in sorted(pending, key=lambda x: x.created_at or datetime.min, reverse=True)[:6]:
            r = wp.summary_row(db, w)
            out["recent_works"].append({k: r[k] for k in ("id", "work_number", "client_name", "domain", "status_label", "status_color", "quotation_amount", "handling_department")})

    # ---- leads
    out["leads"] = None
    if can_crm:
        out["leads"] = {"new": db.query(Lead).filter(Lead.org_id == org_id, Lead.created_at >= lo, Lead.created_at < hi).count()} if hasattr(Lead, "created_at") else None

    # ---- tasks & projects
    out["tasks"] = None
    out["priority_tasks"] = []
    out["projects"] = []
    if can_proj:
        tq = db.query(Task, Project.name).join(Project, Project.id == Task.project_id).filter(Project.org_id == org_id)
        if not admin:
            tq = tq.filter(Task.assigned_to == user.id)
        rows = tq.all()
        order = {"high": 0, "medium": 1, "low": 2}
        out["tasks"] = {"todo": sum(1 for t, _ in rows if t.status == "todo"), "in_progress": sum(1 for t, _ in rows if t.status == "in_progress"),
                        "done": sum(1 for t, _ in rows if t.status == "done")}
        open_rows = sorted([r for r in rows if r[0].status != "done"], key=lambda r: (order.get(r[0].priority, 1), r[0].due_date or date.max))
        out["priority_tasks"] = [{"id": t.id, "title": t.title, "project": pn, "priority": t.priority, "status": t.status, "due_date": t.due_date}
                                 for t, pn in open_rows[:6]]
        for p in db.query(Project).filter(Project.org_id == org_id).order_by(Project.name).limit(8):
            tasks = [t for t, pn in db.query(Task, Project.name).join(Project, Project.id == Task.project_id).filter(Task.project_id == p.id)]
            total, done = len(tasks), sum(1 for t in tasks if t.status == "done")
            out["projects"].append({"id": p.id, "name": p.name, "status": p.status, "end_date": p.end_date, "tasks": total, "done": done,
                                    "progress": round(100 * done / total) if total else 0})

    # ---- income trend: 7 local days ending `on` (or the window end if in the past)
    out["income_trend"] = []
    if income is not None:
        end = min(last, today) if period != "today" else on
        days = [end - timedelta(days=i) for i in range(6, -1, -1)]
        rows = _income_rows(db, org_id, _utc(days[0], tz), _utc(days[-1] + timedelta(days=1), tz), can_work, can_fin)
        sums = {d: Decimal(0) for d in days}
        for c, a in rows:
            d = c.replace(tzinfo=timezone.utc).astimezone(tz).date()
            if d in sums:
                sums[d] += a
        out["income_trend"] = [{"date": d, "label": d.strftime("%a"), "amount": _money(v)} for d, v in sums.items()]
    return out
