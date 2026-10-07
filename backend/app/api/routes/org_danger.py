"""
Reset or permanently delete an organization. Admin only, and deliberately hard to do by accident:

  1. the admin re-enters their password and an emailed 6-digit code is sent to their address;
  2. the code is entered (plus the authenticator code when the admin has one);
  3. they type the organization's sub-domain (delete) or the word RESET (reset).

Reset keeps the organization, its users, roles and HR structure and clears the business data.
Delete removes everything; the same email address can then sign up again from scratch.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.security import verify_password
from app.models.organization import Organization
from app.models.role import Permission
from app.models.user import User
from app.services import org_actions, totp
from app.services.audit import log_audit_event
from app.services.email import send_email
from app.services.org_data import delete_organization, reset_business_data
from app.services.storage import delete_org_files

router = APIRouter(prefix="/api/organizations/danger", tags=["organization-danger-zone"],
                   dependencies=[Depends(get_current_user), Depends(require_permission("core", "manage_access"))])


class StatusOut(BaseModel):
    org_name: str
    subdomain: str
    email_hint: str
    totp_enabled: bool


class RequestCodeIn(BaseModel):
    purpose: Literal["reset", "delete"]
    password: str


class ResetIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    confirm_text: str
    totp_code: Optional[str] = None


class DeleteIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    subdomain: str
    totp_code: Optional[str] = None


def _org(db: Session, user: User) -> Organization:
    return db.query(Organization).filter(Organization.id == user.org_id).one()


def _check_totp(db: Session, user: User, code: Optional[str]) -> None:
    if not user.totp_enabled:
        return
    secret = totp.decrypt_secret(user.totp_secret_enc) if user.totp_secret_enc else None
    step = totp.verify_code(secret, code or "", user.totp_last_step) if secret else None
    if step is None:
        raise HTTPException(400, "The authenticator code is missing or not correct.")
    user.totp_last_step = step
    db.flush()   # write now, before the rows it belongs to can be deleted


@router.get("/status", response_model=StatusOut)
def status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    org = _org(db, current_user)
    return StatusOut(org_name=org.name, subdomain=org.subdomain, email_hint=org_actions.mask_email(current_user.email), totp_enabled=current_user.totp_enabled)


@router.post("/request-code", status_code=200)
def request_code(payload: RequestCodeIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(401, "Incorrect password.")
    org = _org(db, current_user)
    org_actions.issue_code(db, current_user, org.name, payload.purpose)
    return {"sent_to": org_actions.mask_email(current_user.email), "expires_minutes": org_actions.settings.ORG_ACTION_CODE_MINUTES}


@router.post("/reset")
def reset(payload: ResetIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.confirm_text.strip() != "RESET":
        raise HTTPException(400, "Type RESET exactly to confirm.")
    org_actions.consume_code(db, current_user, "reset", payload.code)
    _check_totp(db, current_user, payload.totp_code)
    removed = reset_business_data(db, current_user.org_id)
    log_audit_event(db, current_user.org_id, current_user.id, "reset_organization_data", "Organization", current_user.org_id)
    db.commit()
    return {"status": "reset", "rows_removed": sum(removed.values()), "tables": removed}


@router.post("/delete")
def delete(payload: DeleteIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    org = _org(db, current_user)
    if payload.subdomain.strip() != org.subdomain:
        raise HTTPException(400, "The sub-domain you typed does not match this organization.")
    org_actions.consume_code(db, current_user, "delete", payload.code)
    _check_totp(db, current_user, payload.totp_code)

    org_id, org_name, my_email = org.id, org.name, current_user.email
    others = [u.email for u in db.query(User).filter(User.org_id == org_id, User.id != current_user.id, User.status == "active").all()
              if u.role and db.query(Permission).filter(Permission.role_id == u.role_id, Permission.module == "core", Permission.action == "manage_access").first()][:10]
    removed = delete_organization(db, org_id)
    db.commit()                      # point of no return
    delete_org_files(str(org_id))    # best effort; the database is already clean

    send_email(my_email, f"{org_name} has been permanently deleted",
               f"The organization {org_name} and all of its data were permanently deleted at your request. This cannot be undone.\n\n"
               f"You can create a new organization with this email address at any time.")
    for e in others:
        send_email(e, f"{org_name} has been permanently deleted",
                   f"An administrator permanently deleted the organization {org_name}. All data and logins for it are gone.")
    return {"status": "deleted", "rows_removed": sum(removed.values())}
