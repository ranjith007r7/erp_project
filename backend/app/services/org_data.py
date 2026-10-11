"""
Wipes an organization's data, driven by the database schema itself so that a
module added later is covered without editing this file.

reset_business_data(): removes everything people entered while using the ERP
(CRM, sales, purchasing, stock, finance entries, payroll runs, projects,
documents, notifications...) and KEEPS the organization, its users, roles and
permissions, the HR structure (departments, job roles, employees and their
payroll deduction settings), leave policy, chart of accounts, custom field
definitions, approval workflow definitions, saved report views, warehouses
and the audit log.

delete_organization(): removes everything, including the organization row.
"""
from sqlalchemy import select, delete, or_
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.organization import Organization
import app.models  # noqa: F401  (make sure every model is registered)

# Tables that survive a reset. Everything else that belongs to the organization is cleared.
KEEP_ON_RESET = {
    "organizations", "organization_profiles", "users", "roles", "permissions",
    "departments", "positions", "employees", "employee_payroll_profiles", "leave_types",
    "chart_of_accounts", "custom_fields", "approval_workflows", "report_subscriptions", "saved_reports",
    "warehouses", "audit_log",
}
# Never touched by an organization wipe (global, not per organization).
GLOBAL_TABLES = {"signup_attempts"}


def _org_condition(table, org_id, _seen=()):
    """SQL condition selecting this table's rows for the organization: directly via org_id, or via ANY parent table that has one.

    A child table can point at several parents (a task points at its project AND at a user). Using only one of
    them - which one depended on set ordering - left rows whose other link was empty (e.g. an unassigned task)
    behind, and the parent delete then failed with a foreign-key error. All parent paths are combined with OR.
    """
    if "org_id" in table.c:
        return table.c.org_id == org_id
    conds = []
    for fk in sorted(table.foreign_keys, key=lambda f: (f.parent.name, f.column.table.name)):
        parent = fk.column.table
        if parent is table or parent.name in _seen:
            continue
        cond = _org_condition(parent, org_id, _seen + (table.name,))
        if cond is not None:
            conds.append(fk.parent.in_(select(fk.column).where(cond)))
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else or_(*conds)


def _wipe(db: Session, org_id, keep: set[str]) -> dict[str, int]:
    removed: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):   # children before parents
        if table.name in keep or table.name in GLOBAL_TABLES:
            continue
        if table.name == "organizations":
            continue
        cond = _org_condition(table, org_id)
        if cond is None:
            continue
        n = db.execute(delete(table).where(cond)).rowcount or 0
        if n:
            removed[table.name] = n
    return removed


def reset_business_data(db: Session, org_id) -> dict[str, int]:
    """Caller commits. Returns {table: rows removed}."""
    db.query(Organization).filter(Organization.id == org_id).with_for_update().one()
    removed = _wipe(db, org_id, KEEP_ON_RESET)
    # the organization's own branding image lives in storage; keeping the key keeps the logo
    return removed


def delete_organization(db: Session, org_id) -> dict[str, int]:
    """Caller commits. Removes every row of the organization, then the organization itself."""
    org = db.query(Organization).filter(Organization.id == org_id).with_for_update().one()
    removed = _wipe(db, org_id, keep=set())
    db.execute(delete(Organization).where(Organization.id == org.id))
    return removed
