"""
Keeps HR job roles (Position, e.g. Finance > Accounts Manager) and RBAC access
roles (Role, the permission bucket) in step, so whatever the admin builds on the
Departments & Roles page shows up in Settings > Roles & Permissions by itself.

Rules
- Every Position has an access role. If none was chosen, one is created (or an
  unused existing role with exactly the same name is adopted), named after the
  title; on a clash the name becomes "<Department> - <Title>".
- 'Admin' is never adopted or renamed: it is the superuser role.
- Self-healing: build_role_tree() repairs any position that has no access role
  (positions made before this feature, or whose role was cleared), so no data
  migration is needed.
- Renaming a position renames its auto-created role only when the role is still
  named after it and nothing else uses it; hand-chosen shared roles are untouched.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.hr import Department, Employee, Position
from app.models.role import Role
from app.models.user import User

RESERVED = {"admin"}


def _name_taken(db: Session, org_id, name: str, exclude_id=None) -> Role | None:
    q = db.query(Role).filter(Role.org_id == org_id, func.lower(Role.name) == name.lower())
    if exclude_id:
        q = q.filter(Role.id != exclude_id)
    return q.first()


def _unique_name(db: Session, org_id, title: str, dept_name: str) -> str:
    candidates = [title, f"{dept_name} - {title}"]
    for c in candidates:
        if c.lower() not in RESERVED and not _name_taken(db, org_id, c):
            return c
    base = candidates[-1]
    n = 2
    while _name_taken(db, org_id, f"{base} ({n})"):
        n += 1
    return f"{base} ({n})"


def ensure_position_role(db: Session, org_id, pos: Position) -> Role:
    """Give `pos` an access role if it has none. Caller commits."""
    if pos.access_role_id:
        return pos.access_role
    dept_name = pos.department.name if pos.department else "Department"
    existing = _name_taken(db, org_id, pos.title)
    in_use = False
    if existing:
        in_use = db.query(Position.id).filter(Position.org_id == org_id, Position.access_role_id == existing.id, Position.id != pos.id).first() is not None
    if existing and existing.name.lower() not in RESERVED and not in_use:
        role = existing  # e.g. a hand-made "Sales Executive" role for the Sales Executive position
    else:
        role = Role(org_id=org_id, name=_unique_name(db, org_id, pos.title, dept_name))
        db.add(role)
        db.flush()
    pos.access_role_id = role.id
    pos.access_role = role
    return role


def rename_position_role(db: Session, org_id, pos: Position, old_title: str) -> None:
    """After a position rename, follow it with its auto-named, unshared role."""
    role = pos.access_role
    if not role or role.name.lower() in RESERVED:
        return
    dept_name = pos.department.name if pos.department else ""
    if role.name not in (old_title, f"{dept_name} - {old_title}"):
        return
    shared = db.query(Position.id).filter(Position.access_role_id == role.id, Position.id != pos.id).first()
    if shared:
        return
    new_name = pos.title if role.name == old_title else f"{dept_name} - {pos.title}"
    if _name_taken(db, org_id, new_name, exclude_id=role.id) or new_name.lower() in RESERVED:
        new_name = _unique_name(db, org_id, pos.title, dept_name)
    role.name = new_name


def build_role_tree(db: Session, org_id) -> dict:
    """Departments -> positions -> access role, plus roles that belong to no position."""
    positions = (db.query(Position).filter(Position.org_id == org_id).order_by(Position.title).all())
    for p in positions:
        if not p.access_role_id:
            ensure_position_role(db, org_id, p)
    db.flush()

    user_counts = dict(db.query(User.role_id, func.count(User.id)).filter(User.org_id == org_id, User.role_id.isnot(None)).group_by(User.role_id).all())
    emp_counts = dict(db.query(Employee.position_id, func.count(Employee.id)).filter(Employee.org_id == org_id, Employee.status == "active", Employee.position_id.isnot(None)).group_by(Employee.position_id).all())

    by_dept: dict = {}
    linked_roles = set()
    for p in positions:
        linked_roles.add(p.access_role_id)
        by_dept.setdefault(p.department_id, []).append({
            "position_id": p.id, "title": p.title, "role_id": p.access_role_id,
            "role_name": p.access_role.name if p.access_role else p.title,
            "user_count": user_counts.get(p.access_role_id, 0),
            "employee_count": emp_counts.get(p.id, 0),
        })
    depts = db.query(Department).filter(Department.org_id == org_id).order_by(Department.name).all()
    others = [r for r in db.query(Role).filter(Role.org_id == org_id).order_by(Role.name).all() if r.id not in linked_roles]
    return {
        "departments": [{"id": d.id, "name": d.name, "positions": by_dept.get(d.id, [])} for d in depts],
        "other_roles": [{"id": r.id, "name": r.name, "user_count": user_counts.get(r.id, 0)} for r in others],
    }
