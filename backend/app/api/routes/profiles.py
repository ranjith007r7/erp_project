"""
Two profile screens.

* Organization profile - the company's own details. Any member can read it;
  only an administrator (core.manage_access) can change it.
* My profile - a person's own HR details. They can change a short list of
  fields themselves, but only after entering a one-time code emailed to their
  login address. HR-controlled fields (code, department, role, salary, joining
  date, status) can never be changed from here.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_permission, user_has_permission
from app.core.database import get_db
from app.models.hr import Employee
from app.models.organization import Organization, OrganizationProfile
from app.models.user import User
from app.schemas.profiles import MyProfileUpdate, OrgProfileUpdate
from app.services import org_actions
from app.services.audit import log_audit_event

org_router = APIRouter(prefix="/api/organizations/profile", tags=["organization-profile"], dependencies=[Depends(get_current_user)])
me_router = APIRouter(prefix="/api/me/profile", tags=["my-profile"], dependencies=[Depends(get_current_user)])

ORG_FIELDS = [
    "legal_name", "industry", "company_size", "founded_on", "description", "website",
    "owner_name", "owner_designation", "owner_email", "owner_phone",
    "company_email", "company_phone", "support_email", "support_phone",
    "address_line1", "address_line2", "city", "state", "postal_code", "country",
    "gstin", "pan", "cin", "registration_number", "fiscal_year_start_month", "currency", "timezone",
]
ORG_DEFAULTS = {"fiscal_year_start_month": 4, "currency": "INR", "timezone": "Asia/Kolkata", "country": "India"}


def _org_out(db: Session, org: Organization, can_edit: bool) -> dict:
    row = db.query(OrganizationProfile).filter(OrganizationProfile.org_id == org.id).first()
    out = {f: (getattr(row, f) if row else None) for f in ORG_FIELDS}
    if not row:
        creator = db.query(User).filter(User.org_id == org.id).order_by(User.created_at.asc()).first()
        if creator:
            out["owner_name"], out["owner_email"] = creator.name, creator.email
    for k, v in ORG_DEFAULTS.items():
        if out.get(k) in (None, ""):
            out[k] = v
    out.update({
        "id": str(org.id), "name": org.name, "subdomain": org.subdomain, "plan": org.plan, "status": org.status,
        "created_at": org.created_at, "updated_at": row.updated_at if row else None, "can_edit": can_edit,
    })
    return out


@org_router.get("")
def get_org_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    org = db.query(Organization).filter(Organization.id == current_user.org_id).one()
    return _org_out(db, org, user_has_permission(db, current_user, "core", "manage_access"))


@org_router.patch("", dependencies=[Depends(require_permission("core", "manage_access"))])
def update_org_profile(payload: OrgProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    org = db.query(Organization).filter(Organization.id == current_user.org_id).with_for_update().one()
    sent = payload.model_dump(exclude_unset=True)
    if "name" in sent:
        if not sent["name"]:
            raise HTTPException(422, "Organization name cannot be empty.")
        org.name = sent.pop("name")
    row = db.query(OrganizationProfile).filter(OrganizationProfile.org_id == org.id).first()
    if not row:
        row = OrganizationProfile(org_id=org.id)
        # keep the owner details the form was showing as defaults, so the first save does not blank them
        creator = db.query(User).filter(User.org_id == org.id).order_by(User.created_at.asc()).first()
        if creator:
            row.owner_name, row.owner_email = creator.name, creator.email
        db.add(row)
    changed = []
    for k, v in sent.items():
        if k in ORG_FIELDS and getattr(row, k) != v:
            setattr(row, k, v)
            changed.append(k)
    row.updated_by, row.updated_at = current_user.id, datetime.utcnow()
    log_audit_event(db, org.id, current_user.id, "update_organization_profile", "Organization", org.id)
    db.commit()
    return _org_out(db, org, True)


# ---------------------------------------------------------------- my profile
EDITABLE = ["name", "phone", "personal_email", "date_of_birth", "gender", "address", "emergency_contact_name", "emergency_contact_phone"]
EMPLOYEE_FIELDS = EDITABLE[1:]


def _employee_for(db: Session, user: User) -> Employee | None:
    # always derived from the signed-in user, never from anything the client sends
    return (db.query(Employee).options(joinedload(Employee.department), joinedload(Employee.position))
            .filter(Employee.org_id == user.org_id, Employee.user_id == user.id).first())


@me_router.get("")
def get_my_profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    org = db.query(Organization).filter(Organization.id == current_user.org_id).one()
    e = _employee_for(db, current_user)
    employee = None
    if e:
        employee = {
            "employee_code": e.employee_code, "name": e.name, "department_name": e.department.name if e.department else None,
            "designation": e.designation or (e.position.title if e.position else None), "employment_type": e.employment_type,
            "joining_date": e.joining_date, "salary": e.salary, "status": e.status,
            "phone": e.phone, "personal_email": e.personal_email, "date_of_birth": e.date_of_birth, "gender": e.gender,
            "address": e.address, "emergency_contact_name": e.emergency_contact_name, "emergency_contact_phone": e.emergency_contact_phone,
        }
    return {
        "user": {"name": current_user.name, "email": current_user.email, "role_name": current_user.role.name if current_user.role else None,
                 "is_admin": user_has_permission(db, current_user, "core", "manage_access")},
        "organization": {"id": str(org.id), "name": org.name},
        "employee": employee,
        "editable_fields": EDITABLE if e else ["name"],
        "otp_sent_to": org_actions.mask_email(current_user.email),
    }


@me_router.post("/request-otp")
def request_profile_otp(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    org = db.query(Organization).filter(Organization.id == current_user.org_id).one()
    org_actions.issue_code(db, current_user, org.name, "profile")
    return {"sent_to": org_actions.mask_email(current_user.email), "expires_minutes": org_actions.settings.ORG_ACTION_CODE_MINUTES}


@me_router.patch("")
def update_my_profile(payload: MyProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sent = payload.model_dump(exclude_unset=True, exclude={"otp"})
    e = _employee_for(db, current_user)
    if not e and any(k in EMPLOYEE_FIELDS for k in sent):
        raise HTTPException(400, "No HR record is linked to your login, so only your name can be changed here. Ask HR to link it.")
    if "name" in sent and not sent["name"]:
        raise HTTPException(422, "Name cannot be empty.")
    # work out what really changes BEFORE spending the one-time code
    current = {"name": current_user.name}
    if e:
        current.update({k: getattr(e, k) for k in EMPLOYEE_FIELDS})
    changes = {k: v for k, v in sent.items() if current.get(k) != v}
    if not changes:
        raise HTTPException(400, "Nothing to change.")
    org_actions.consume_code(db, current_user, "profile", payload.otp)
    for k, v in changes.items():
        if k == "name":
            current_user.name = v
            if e:
                e.name = v
        else:
            setattr(e, k, v)
    log_audit_event(db, current_user.org_id, current_user.id, "update_own_profile:" + ",".join(sorted(changes)), "User", current_user.id)
    db.commit()
    return {"status": "updated", "changed": sorted(changes)}
