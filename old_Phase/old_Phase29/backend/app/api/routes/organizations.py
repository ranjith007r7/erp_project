"""
Org-wide branding: a logo/background image an Admin uploads, visible to
every member of that org. Reuses the exact R2 upload/presigned-URL
service already built for Documents (app/services/storage.py) - no
second storage integration for one feature.

Deliberately a different trust model than Documents, though: a logo is
inherently meant to be seen by the whole org, not a private business
record, so upload is gated more simply (core.manage_access, matching
"this is a whole-org setting" the same way other org-wide toggles are
gated) rather than needing per-document ownership checks.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.organization import Organization
from app.services.storage import upload_file, generate_presigned_url
from app.services.audit import log_audit_event

router = APIRouter(prefix="/api/organizations/branding", tags=["organization-branding"], dependencies=[Depends(get_current_user)])


@router.get("")
def get_branding(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Any authenticated org member can fetch this - seeing your own org's
    logo isn't a privileged action, only CHANGING it is. Returns a fresh
    presigned URL every call rather than anything stored, same reasoning
    as Documents' download route: the URL expires, so persisting one
    would just mean it silently stops working later. Harmless for a
    logo specifically, since a browser that's already loaded the image
    keeps showing it regardless of the URL expiring afterward - this
    only matters for the NEXT fetch, not already-rendered content.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org or not org.branding_storage_key:
        return {"url": None}
    url = generate_presigned_url(org.branding_storage_key, expires_in_seconds=600)
    return {"url": url}


@router.post("", dependencies=[Depends(require_permission("core", "manage_access"))])
async def upload_branding(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
    current_user=Depends(get_current_user),
):
    """
    manage_access gated - same tier of gate as other whole-org settings
    (role/permission management), because a branding image is visible
    to and affects every single member's experience, not just the
    uploader's own view of things.
    """
    content = await file.read()
    storage_key = upload_file(org_id, file.filename or "branding", content, file.content_type or "application/octet-stream")

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(404, "Organization not found")

    org.branding_storage_key = storage_key
    log_audit_event(db, org_id, current_user.id, "update_branding", "Organization", org.id)
    db.commit()

    return {"message": "Branding updated."}


@router.delete("", dependencies=[Depends(require_permission("core", "manage_access"))])
def remove_branding(db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(404, "Organization not found")

    org.branding_storage_key = None
    log_audit_event(db, org_id, current_user.id, "remove_branding", "Organization", org.id)
    db.commit()

    return {"message": "Branding removed."}
