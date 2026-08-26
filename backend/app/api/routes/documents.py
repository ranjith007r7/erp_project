"""
Documents module routes. The interesting part is the approval engine:
- ApprovalWorkflow: a reusable RULE ("Expenses over X need Manager then Finance")
- ApprovalRequest: one INSTANCE of that rule running against one real record
- ApprovalStep: each stage of that instance, actioned in strict order

Any future module (Procurement, HR, Sales) can trigger a request against
an existing workflow by calling POST /approval-requests with its own
entity_type/entity_id - it does NOT need its own approval logic.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.documents import Document, ApprovalWorkflow, ApprovalRequest, ApprovalStep
from app.services.notifications import notify_role, notify_user
from app.services.storage import upload_file, generate_presigned_url
from app.services.audit import log_audit_event
from app.schemas.documents import (
    DocumentCreate, DocumentOut, DocumentDownloadOut,
    ApprovalWorkflowCreate, ApprovalWorkflowOut,
    ApprovalRequestCreate, ApprovalRequestOut,
    ApprovalActionRequest,
)

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(get_current_user)])


# ---------------- Documents ----------------
@router.post("", response_model=DocumentOut, status_code=201, dependencies=[Depends(require_permission("documents", "create"))])
def create_document(payload: DocumentCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id),
                     current_user=Depends(get_current_user)):
    doc = Document(org_id=org_id, uploaded_by=current_user.id, **payload.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("", response_model=list[DocumentOut], dependencies=[Depends(require_permission("documents", "view"))])
def list_documents(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Document).filter(Document.org_id == org_id).order_by(Document.created_at.desc()).all()


@router.post("/upload", response_model=DocumentOut, status_code=201, dependencies=[Depends(require_permission("documents", "create"))])
async def upload_document(
    title: str = Form(...),
    related_type: str | None = Form(None),
    related_id: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
    current_user=Depends(get_current_user),
):
    """
    A genuinely different creation path from POST /api/documents above -
    that one takes a JSON body with a caller-provided file_url; this one
    takes a real multipart file, uploads it to R2, and stores the
    resulting storage_key instead. file_url stays null for documents
    created this way - see the Document model's docstring on why one
    real Document has exactly one of the two, never both.
    """
    content = await file.read()
    storage_key = upload_file(org_id, file.filename or "upload", content, file.content_type or "application/octet-stream")

    doc = Document(
        org_id=org_id,
        title=title,
        storage_key=storage_key,
        uploaded_by=current_user.id,
        related_type=related_type,
        related_id=related_id or None,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}/download", response_model=DocumentDownloadOut, dependencies=[Depends(require_permission("documents", "view"))])
def get_document_download_url(document_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Generates a FRESH presigned URL on every call rather than returning
    anything stored - presigned URLs expire (10 minutes here) by design,
    so persisting one would just mean it silently stops working later.
    The org_id filter below is the actual access control: even a valid,
    guessed document_id from another org returns 404, not someone else's
    file - the storage key's org-scoped prefix is a convenience for
    humans browsing the bucket directly, not the real security boundary.
    """
    doc = db.query(Document).filter(Document.id == document_id, Document.org_id == org_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.storage_key:
        raise HTTPException(400, "This document has no uploaded file - it was created with an external file_url instead.")

    url = generate_presigned_url(doc.storage_key, expires_in_seconds=600)
    return DocumentDownloadOut(url=url, expires_in_seconds=600)


# ---------------- Approval Workflows (the reusable rules) ----------------
@router.post("/workflows", response_model=ApprovalWorkflowOut, status_code=201, dependencies=[Depends(require_permission("documents", "create"))])
def create_workflow(payload: ApprovalWorkflowCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    workflow = ApprovalWorkflow(
        org_id=org_id,
        name=payload.name,
        module=payload.module,
        steps_config=[s.model_dump() for s in payload.steps],
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


@router.get("/workflows", response_model=list[ApprovalWorkflowOut], dependencies=[Depends(require_permission("documents", "view"))])
def list_workflows(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(ApprovalWorkflow).filter(ApprovalWorkflow.org_id == org_id).all()


# ---------------- Approval Requests (instances of a rule) ----------------
@router.post("/approval-requests", response_model=ApprovalRequestOut, status_code=201, dependencies=[Depends(require_permission("documents", "create"))])
def create_approval_request(payload: ApprovalRequestCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id),
                             current_user=Depends(get_current_user)):
    workflow = db.query(ApprovalWorkflow).filter(
        ApprovalWorkflow.id == payload.workflow_id, ApprovalWorkflow.org_id == org_id
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Approval workflow not found")

    request = ApprovalRequest(
        workflow_id=workflow.id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        requested_by=current_user.id,
    )
    # Materialize one ApprovalStep row per step in the workflow's rule -
    # this is what turns a generic JSON rule into trackable, auditable
    # per-step records.
    for i, step in enumerate(workflow.steps_config, start=1):
        request.steps.append(ApprovalStep(step_order=i, role_required=step["role"]))

    db.add(request)
    db.commit()
    db.refresh(request)

    # Step 1 is actionable the moment the request exists — notify whoever
    # holds that role. Soft-fail (see notify_role's docstring): a
    # workflow's role_required string isn't guaranteed to match a real
    # Role row yet, since RBAC enforcement is still Phase 11.
    first_step = min(request.steps, key=lambda s: s.step_order)
    notify_role(db, org_id, first_step.role_required, f"A {payload.entity_type} needs your approval.")
    db.commit()

    return request


@router.get("/approval-requests", response_model=list[ApprovalRequestOut], dependencies=[Depends(require_permission("documents", "view"))])
def list_approval_requests(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(ApprovalRequest)
        .join(ApprovalWorkflow, ApprovalWorkflow.id == ApprovalRequest.workflow_id)
        .options(joinedload(ApprovalRequest.steps))
        .filter(ApprovalWorkflow.org_id == org_id)
        .order_by(ApprovalRequest.created_at.desc())
        .all()
    )


@router.post("/approval-requests/{request_id}/action", response_model=ApprovalRequestOut, dependencies=[Depends(require_permission("documents", "approve"))])
def action_approval_step(request_id: str, payload: ApprovalActionRequest, db: Session = Depends(get_db),
                          org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    Acts on whichever step is currently pending, IN ORDER - step 2 can
    never be actioned before step 1. Full role-based restriction (only
    letting a 'Finance' user action a 'Finance' step) is a Phase 11 (RBAC
    Enforcement) concern - for now, Admins can action any step, which is
    enough to demo the workflow mechanics correctly.
    """
    request = (
        db.query(ApprovalRequest)
        .join(ApprovalWorkflow, ApprovalWorkflow.id == ApprovalRequest.workflow_id)
        .options(joinedload(ApprovalRequest.steps))
        .filter(ApprovalRequest.id == request_id, ApprovalWorkflow.org_id == org_id)
        .first()
    )
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail=f"This request is already {request.status}.")

    pending_steps = sorted([s for s in request.steps if s.status == "pending"], key=lambda s: s.step_order)
    if not pending_steps:
        raise HTTPException(status_code=400, detail="No pending step to act on.")
    current_step = pending_steps[0]

    role_name = current_user.role.name if current_user.role else None
    if role_name != "Admin" and role_name != current_step.role_required:
        raise HTTPException(
            status_code=403,
            detail=f"This step requires role '{current_step.role_required}'.",
        )

    current_step.approver_id = current_user.id
    current_step.acted_at = datetime.utcnow()

    if payload.decision == "reject":
        current_step.status = "rejected"
        request.status = "rejected"
        notify_user(db, org_id, request.requested_by, f"Your {request.entity_type} approval request was rejected.")
    else:
        current_step.status = "approved"
        remaining = [s for s in request.steps if s.step_order > current_step.step_order]
        if not remaining:
            request.status = "approved"
            notify_user(db, org_id, request.requested_by, f"Your {request.entity_type} approval request was approved.")
        else:
            # Next step just became actionable — notify whoever holds
            # THAT role, same as the very first step at creation time.
            next_step = min(remaining, key=lambda s: s.step_order)
            notify_role(db, org_id, next_step.role_required, f"A {request.entity_type} needs your approval.")

    log_audit_event(db, org_id, current_user.id, f"approval_{payload.decision}", "ApprovalRequest", request.id)
    db.commit()
    db.refresh(request)
    return request
