"""
Searches across every module in one call. The real design decision here,
not a shortcut: results are filtered by the CALLER's actual role
permissions per module, not just their org. A role holding only
sales.view must never see HR employees surface through search, even
though direct navigation to /hr would correctly 403 them - skipping this
check would be a real security regression, exactly the kind of thing
RBAC enforcement exists to prevent, just reached through a different
door (search) instead of the front one (the module's own route).

Each entity type is only queried if the caller's role actually holds
<module>.view for it - reuses the same Permission table every other
permission check in this app reads from, just checked inline here since
one endpoint needs to conditionally check MANY modules, not gate itself
behind a single fixed module/action the way require_permission() does.
"""
from sqlalchemy.orm import Session

from app.models.role import Permission, Role
from app.models.crm import Lead, Account
from app.models.sales import Customer, Product
from app.models.hr import Employee
from app.models.procurement import Vendor
from app.models.documents import Document

RESULTS_PER_TYPE = 5
ADMIN_ROLE_NAME = "Admin"


def _has_view_permission(db: Session, role_id, module: str) -> bool:
    if not role_id:
        return False
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        return False
    # Admin always sees everything in search, full stop - checked by role
    # name directly rather than requiring a real Permission row to exist
    # first. require_permission()'s self-heal (deps.py) only fires when a
    # route actually goes through that dependency - a read-only search
    # bypasses that path entirely, so an Admin whose org never happened
    # to visit a documents-gated route first would otherwise see zero
    # documents in search results despite being Admin. Search shouldn't
    # have the side effect of writing self-heal permission rows just to
    # answer "can this Admin see this", so it checks the role name
    # directly instead.
    if role.name == ADMIN_ROLE_NAME:
        return True
    return db.query(Permission).filter(
        Permission.role_id == role_id, Permission.module == module, Permission.action == "view"
    ).first() is not None


def global_search(db: Session, org_id: str, role_id, query: str, limit_per_type: int = RESULTS_PER_TYPE) -> list[dict]:
    like = f"%{query}%"
    results: list[dict] = []

    if _has_view_permission(db, role_id, "crm"):
        for lead in db.query(Lead).filter(
            Lead.org_id == org_id,
            (Lead.name.ilike(like)) | (Lead.company_name.ilike(like)) | (Lead.email.ilike(like)),
        ).limit(limit_per_type).all():
            results.append({"type": "lead", "module": "crm", "id": str(lead.id), "title": lead.name, "subtitle": lead.company_name})

        for account in db.query(Account).filter(Account.org_id == org_id, Account.name.ilike(like)).limit(limit_per_type).all():
            results.append({"type": "account", "module": "crm", "id": str(account.id), "title": account.name, "subtitle": account.industry})

    if _has_view_permission(db, role_id, "sales"):
        for customer in db.query(Customer).filter(Customer.org_id == org_id, Customer.name.ilike(like)).limit(limit_per_type).all():
            results.append({"type": "customer", "module": "sales", "id": str(customer.id), "title": customer.name, "subtitle": customer.gst_number})

        for product in db.query(Product).filter(
            Product.org_id == org_id, (Product.name.ilike(like)) | (Product.sku.ilike(like)),
        ).limit(limit_per_type).all():
            results.append({"type": "product", "module": "sales", "id": str(product.id), "title": product.name, "subtitle": product.sku})

    if _has_view_permission(db, role_id, "hr"):
        for emp in db.query(Employee).filter(Employee.org_id == org_id, Employee.name.ilike(like)).limit(limit_per_type).all():
            results.append({"type": "employee", "module": "hr", "id": str(emp.id), "title": emp.name, "subtitle": emp.designation})

    if _has_view_permission(db, role_id, "procurement"):
        for vendor in db.query(Vendor).filter(Vendor.org_id == org_id, Vendor.name.ilike(like)).limit(limit_per_type).all():
            results.append({"type": "vendor", "module": "procurement", "id": str(vendor.id), "title": vendor.name, "subtitle": vendor.contact})

    if _has_view_permission(db, role_id, "documents"):
        for doc in db.query(Document).filter(Document.org_id == org_id, Document.title.ilike(like)).limit(limit_per_type).all():
            results.append({"type": "document", "module": "documents", "id": str(doc.id), "title": doc.title, "subtitle": doc.related_type})

    return results
