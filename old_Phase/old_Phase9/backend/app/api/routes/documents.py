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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.models.documents import Document, ApprovalWorkflow, ApprovalRequest, ApprovalStep
from app.schemas.documents import (
    DocumentCreate, DocumentOut,
    ApprovalWorkflowCreate, ApprovalWorkflowOut,
    ApprovalRequestCreate, ApprovalRequestOut,
    ApprovalActionRequest,
)

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(get_current_user)])


# ---------------- Documents ----------------
@router.post("", response_model=DocumentOut, status_code=201)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id),
                     current_user=Depends(get_current_user)):
    doc = Document(org_id=org_id, uploaded_by=current_user.id, **payload.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Document).filter(Document.org_id == org_id).order_by(Document.created_at.desc()).all()


# ---------------- Approval Workflows (the reusable rules) ----------------
@router.post("/workflows", response_model=ApprovalWorkflowOut, status_code=201)
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


@router.get("/workflows", response_model=list[ApprovalWorkflowOut])
def list_workflows(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(ApprovalWorkflow).filter(ApprovalWorkflow.org_id == org_id).all()


# ---------------- Approval Requests (instances of a rule) ----------------
@router.post("/approval-requests", response_model=ApprovalRequestOut, status_code=201)
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
    return request


@router.get("/approval-requests", response_model=list[ApprovalRequestOut])
def list_approval_requests(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(ApprovalRequest)
        .join(ApprovalWorkflow, ApprovalWorkflow.id == ApprovalRequest.workflow_id)
        .options(joinedload(ApprovalRequest.steps))
        .filter(ApprovalWorkflow.org_id == org_id)
        .order_by(ApprovalRequest.created_at.desc())
        .all()
    )


@router.post("/approval-requests/{request_id}/action", response_model=ApprovalRequestOut)
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
    else:
        current_step.status = "approved"
        remaining = [s for s in request.steps if s.step_order > current_step.step_order]
        if not remaining:
            request.status = "approved"
        # else: request stays "pending" - the next step is now the new
        # "first pending step" the next call to this endpoint will find.

    db.commit()
    db.refresh(request)
    return request
