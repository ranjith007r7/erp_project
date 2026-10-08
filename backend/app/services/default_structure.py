"""
Standard departments, job roles and starting permissions for a new organization.

Why: an empty "Roles by department" page makes every client start from nothing.
The set below is the usual shape of a small/mid-size trading, services or
manufacturing company (what ERP vendors such as Odoo, NetSuite and Zoho ship as
role templates, and what business-function texts list: management, sales &
marketing, purchasing, warehouse/stores, finance & accounts, HR, operations &
delivery, projects, IT, customer support).

Rules
- Defaults are ordinary rows. Rename, delete, re-tick permissions: nothing is locked.
- Seeded ONCE per organization (organizations.defaults_seeded_at). Deleting a
  default later does not bring it back; the admin can use "Restore defaults"
  (restore_defaults), which only ADDS what is missing and never changes a role
  that already has permissions.
- An organization that already built its own departments is left alone by the
  automatic path (it has structure of its own).
- Salaries are left at 0: pay is decided by HR (hr.approve), never guessed here.
- manage_access ("Manage Roles & Permissions") is never given to a default role.

Permission letters: v=view c=create e=edit d=delete a=approve.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.hr import Department, Position
from app.models.organization import Organization
from app.models.role import Permission, Role
from app.services.position_roles import ensure_position_role

ACTION_OF = {"v": "view", "c": "create", "e": "edit", "d": "delete", "a": "approve"}

# department -> [(job title, {module: letters})]
DEFAULT_STRUCTURE: dict[str, list[tuple[str, dict[str, str]]]] = {
    "Management": [
        ("Managing Director", {"dashboard": "v", "crm": "v", "sales": "va", "procurement": "va", "inventory": "v",
                               "finance": "va", "hr": "va", "projects": "va", "documents": "vcea", "reports": "v",
                               "workpage": "vea", "intelligence": "va", "core": "v"}),
        ("General Manager", {"dashboard": "v", "crm": "v", "sales": "va", "procurement": "va", "inventory": "v",
                             "finance": "v", "hr": "v", "projects": "va", "documents": "vcea", "reports": "v",
                             "workpage": "vea", "intelligence": "v"}),
    ],
    "Sales & Marketing": [
        ("Sales Manager", {"dashboard": "v", "crm": "vced", "sales": "vcea", "inventory": "v", "workpage": "vcea",
                           "documents": "vc", "reports": "v", "intelligence": "v"}),
        ("Sales Executive", {"dashboard": "v", "crm": "vce", "sales": "vce", "inventory": "v", "workpage": "vce",
                             "documents": "vc"}),
        ("Marketing Executive", {"dashboard": "v", "crm": "vce", "sales": "v", "documents": "vc", "reports": "v"}),
    ],
    "Procurement": [
        ("Procurement Manager", {"dashboard": "v", "procurement": "vcea", "inventory": "v", "finance": "v",
                                 "workpage": "ve", "documents": "vc", "reports": "v"}),
        ("Purchase Executive", {"dashboard": "v", "procurement": "vce", "inventory": "v", "workpage": "v",
                                "documents": "vc"}),
    ],
    "Warehouse & Inventory": [
        ("Warehouse Manager", {"dashboard": "v", "inventory": "vced", "procurement": "vce", "sales": "v",
                               "workpage": "ve", "documents": "vc", "reports": "v"}),
        ("Store Keeper", {"dashboard": "v", "inventory": "vce", "procurement": "vce", "workpage": "v",
                          "documents": "vc"}),
    ],
    "Finance & Accounts": [
        ("Finance Manager", {"dashboard": "v", "finance": "vcea", "sales": "v", "procurement": "v", "hr": "v",
                             "workpage": "vea", "documents": "vcea", "reports": "v", "intelligence": "v"}),
        ("Accountant", {"dashboard": "v", "finance": "vce", "sales": "v", "procurement": "v", "workpage": "ve",
                        "documents": "vc", "reports": "v"}),
        ("Accounts Executive", {"dashboard": "v", "finance": "vc", "sales": "v", "workpage": "v", "documents": "vc"}),
    ],
    "Human Resources": [
        ("HR Manager", {"dashboard": "v", "hr": "vcea", "documents": "vcea", "reports": "v", "core": "v"}),
        ("HR Executive", {"dashboard": "v", "hr": "vce", "documents": "vc"}),
    ],
    "Operations & Delivery": [
        ("Operations Manager", {"dashboard": "v", "workpage": "vcea", "projects": "vcea", "inventory": "v",
                                "procurement": "v", "sales": "v", "documents": "vc", "reports": "v"}),
        ("Operations Executive", {"dashboard": "v", "workpage": "vce", "projects": "vce", "inventory": "v",
                                  "documents": "vc"}),
        ("Delivery Executive", {"dashboard": "v", "workpage": "ve", "inventory": "v", "documents": "vc"}),
    ],
    "Projects": [
        ("Project Manager", {"dashboard": "v", "projects": "vcea", "workpage": "v", "documents": "vcea", "reports": "v"}),
        ("Team Lead", {"dashboard": "v", "projects": "vce", "documents": "vc"}),
        ("Project Engineer", {"dashboard": "v", "projects": "vce", "documents": "vc"}),
    ],
    "IT & Systems": [
        ("IT Administrator", {"dashboard": "v", "core": "v", "custom_fields": "vced", "documents": "vc", "reports": "v"}),
        ("IT Support Engineer", {"dashboard": "v", "documents": "vc"}),
    ],
    "Customer Support": [
        ("Support Manager", {"dashboard": "v", "crm": "vce", "sales": "v", "workpage": "v", "documents": "vc", "reports": "v"}),
        ("Support Executive", {"dashboard": "v", "crm": "ve", "sales": "v", "workpage": "v", "documents": "vc"}),
    ],
}


def summary() -> list[dict]:
    """The defaults as plain data (used by the docs / Restore-defaults preview)."""
    return [{"department": d, "roles": [{"title": t, "permissions": {m: [ACTION_OF[c] for c in a] for m, a in p.items()}}
                                          for t, p in roles]} for d, roles in DEFAULT_STRUCTURE.items()]


def _apply_permissions(db: Session, role: Role, perms: dict[str, str]) -> int:
    if db.query(Permission.id).filter(Permission.role_id == role.id).first():
        return 0   # somebody already set this role up; leave it exactly as it is
    n = 0
    for module, letters in perms.items():
        for ch in letters:
            db.add(Permission(role_id=role.id, module=module, action=ACTION_OF[ch]))
            n += 1
    return n


def restore_defaults(db: Session, org_id) -> dict:
    """Add every default department / job role / permission set that is missing. Caller commits."""
    made = {"departments": 0, "roles": 0, "permissions": 0}
    for dept_name, roles in DEFAULT_STRUCTURE.items():
        dept = db.query(Department).filter(Department.org_id == org_id, func.lower(Department.name) == dept_name.lower()).first()
        if not dept:
            dept = Department(org_id=org_id, name=dept_name)
            db.add(dept)
            db.flush()
            made["departments"] += 1
        for title, perms in roles:
            pos = db.query(Position).filter(Position.org_id == org_id, Position.department_id == dept.id,
                                            func.lower(Position.title) == title.lower()).first()
            if not pos:
                pos = Position(org_id=org_id, department_id=dept.id, title=title, base_salary=0)
                db.add(pos)
                db.flush()
            had_role = pos.access_role_id is not None
            role = ensure_position_role(db, org_id, pos)
            db.flush()
            if not had_role:
                made["roles"] += 1
            made["permissions"] += _apply_permissions(db, role, perms)
    org = db.get(Organization, org_id)
    if org and not org.defaults_seeded_at:
        org.defaults_seeded_at = datetime.utcnow()
    return made


def seed_on_signup(db: Session, org_id) -> dict:
    return restore_defaults(db, org_id)


def heal_existing_org(db: Session, org_id) -> bool:
    """
    For organizations created before this feature: offer the defaults once, but only
    if the org has no departments of its own. Returns True if it seeded. Caller commits.
    """
    org = db.get(Organization, org_id)
    if not org or org.defaults_seeded_at:
        return False
    if db.query(Department.id).filter(Department.org_id == org_id).first():
        org.defaults_seeded_at = datetime.utcnow()   # has its own structure: nothing to add, never ask again
        return False
    restore_defaults(db, org_id)
    return True
