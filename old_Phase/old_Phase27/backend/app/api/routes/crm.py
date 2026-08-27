"""
CRM module routes. Every route here follows the same shape:
1. Require a logged-in user (get_current_user)
2. Scope every query to that user's organization (get_org_id)
3. Never let one org see or touch another org's rows - this is the
   multi-tenancy rule enforced in code, on every single query.
"""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.crm import Account, Contact, Lead, Opportunity
from app.services.audit import log_audit_event
from app.schemas.crm import (
    AccountCreate, AccountOut,
    ContactCreate, ContactOut,
    LeadCreate, LeadOut, LeadStatusUpdate, ConvertLeadRequest,
    OpportunityCreate, OpportunityOut, OpportunityStageUpdate,
    BulkDeleteRequest,
)

router = APIRouter(prefix="/api/crm", tags=["crm"], dependencies=[Depends(get_current_user)])


# ---------------- Accounts ----------------
@router.post("/accounts", response_model=AccountOut, status_code=201, dependencies=[Depends(require_permission("crm", "create"))])
def create_account(payload: AccountCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    account = Account(org_id=org_id, **payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/accounts", response_model=list[AccountOut], dependencies=[Depends(require_permission("crm", "view"))])
def list_accounts(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Account).filter(Account.org_id == org_id).order_by(Account.created_at.desc()).all()


# ---------------- Contacts ----------------
@router.post("/contacts", response_model=ContactOut, status_code=201, dependencies=[Depends(require_permission("crm", "create"))])
def create_contact(payload: ContactCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    contact = Contact(org_id=org_id, **payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/contacts", response_model=list[ContactOut], dependencies=[Depends(require_permission("crm", "view"))])
def list_contacts(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Contact).filter(Contact.org_id == org_id).all()


# ---------------- Leads ----------------
@router.post("/leads", response_model=LeadOut, status_code=201, dependencies=[Depends(require_permission("crm", "create"))])
def create_lead(payload: LeadCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    lead = Lead(org_id=org_id, **payload.model_dump())
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/leads", response_model=list[LeadOut], dependencies=[Depends(require_permission("crm", "view"))])
def list_leads(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Lead).filter(Lead.org_id == org_id).order_by(Lead.created_at.desc()).all()


@router.delete("/leads/{lead_id}", status_code=204, dependencies=[Depends(require_permission("crm", "delete"))])
def delete_lead(lead_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    The first real DELETE this whole module has ever had - every prior
    route here only creates or status-updates. Leads are a genuinely
    safe entity to hard-delete (a contact record, not a financial/audit
    document like an Invoice or Journal Entry), unlike Customers, which
    real Invoices and Payments can reference - deleting one of those
    would risk orphaning real financial data, which is why bulk delete
    was deliberately scoped to Leads only, not extended to Sales.
    """
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.org_id == org_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    db.delete(lead)
    log_audit_event(db, org_id, current_user.id, "delete_lead", "Lead", lead_id)
    db.commit()


@router.post("/leads/bulk-delete", dependencies=[Depends(require_permission("crm", "delete"))])
def bulk_delete_leads(payload: BulkDeleteRequest, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    Composes from the SAME per-item logic as delete_lead above, not a
    separate bulk-only code path - each id is checked against org_id
    individually (so a stray id from another org is silently skipped,
    not a security hole), and every deletion gets its own audit entry,
    same as if it had been deleted one at a time. Returns a per-item
    report rather than an all-or-nothing result, so a partially-valid
    batch (some real ids, some already-deleted or bogus ones) is never
    ambiguous about what actually happened.
    """
    deleted_ids: list[str] = []
    not_found_ids: list[str] = []
    for lead_id in payload.ids:
        lead = db.query(Lead).filter(Lead.id == lead_id, Lead.org_id == org_id).first()
        if not lead:
            not_found_ids.append(lead_id)
            continue
        db.delete(lead)
        log_audit_event(db, org_id, current_user.id, "delete_lead", "Lead", lead_id)
        deleted_ids.append(lead_id)
    db.commit()
    return {"deleted": deleted_ids, "not_found": not_found_ids}


@router.patch("/leads/{lead_id}/status", response_model=LeadOut, dependencies=[Depends(require_permission("crm", "edit"))])
def update_lead_status(lead_id: str, payload: LeadStatusUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.org_id == org_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.status = payload.status
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/leads/{lead_id}/convert", response_model=OpportunityOut, status_code=201, dependencies=[Depends(require_permission("crm", "edit"))])
def convert_lead(lead_id: str, payload: ConvertLeadRequest, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    The single most important CRM action: turns a Lead into a real Account
    (+ Contact, if we have a name/email) and an Opportunity ready to be
    quoted. This is the exact moment 'a stranger' becomes 'a real deal.'
    """
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.org_id == org_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status == "converted":
        raise HTTPException(status_code=400, detail="This lead has already been converted.")

    account = Account(
        org_id=org_id,
        name=lead.company_name or lead.name,
    )
    db.add(account)
    db.flush()

    contact = Contact(
        org_id=org_id,
        account_id=account.id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
    )
    db.add(contact)
    db.flush()

    opportunity = Opportunity(
        org_id=org_id,
        account_id=account.id,
        contact_id=contact.id,
        name=payload.opportunity_name,
        value=payload.opportunity_value,
    )
    db.add(opportunity)

    lead.status = "converted"

    db.commit()
    db.refresh(opportunity)
    return opportunity


# ---------------- Opportunities ----------------
@router.post("/opportunities", response_model=OpportunityOut, status_code=201, dependencies=[Depends(require_permission("crm", "create"))])
def create_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    opportunity = Opportunity(org_id=org_id, **payload.model_dump())
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.get("/opportunities", response_model=list[OpportunityOut], dependencies=[Depends(require_permission("crm", "view"))])
def list_opportunities(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Opportunity).filter(Opportunity.org_id == org_id).order_by(Opportunity.created_at.desc()).all()


@router.patch("/opportunities/{opportunity_id}/stage", response_model=OpportunityOut, dependencies=[Depends(require_permission("crm", "edit"))])
def update_opportunity_stage(opportunity_id: str, payload: OpportunityStageUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id, Opportunity.org_id == org_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    opportunity.stage = payload.stage
    db.commit()
    db.refresh(opportunity)
    return opportunity


# ---------------- CSV export / import (Leads only - see MANUAL.md for
# why this was deliberately scoped to one module first) ----------------
@router.get("/leads/export", dependencies=[Depends(require_permission("crm", "view"))])
def export_leads_csv(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    leads = db.query(Lead).filter(Lead.org_id == org_id).order_by(Lead.created_at.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "company_name", "email", "source", "status"])
    for lead in leads:
        writer.writerow([lead.name, lead.company_name or "", lead.email or "", lead.source or "", lead.status])

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


MAX_IMPORT_ROWS = 1000


@router.post("/leads/import", dependencies=[Depends(require_permission("crm", "create"))])
async def import_leads_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
    current_user=Depends(get_current_user),
):
    """
    Deliberately partial-success, never all-or-nothing: a 500-row file
    with one bad row should import the other 499, not fail the entire
    batch over a single typo - reporting exactly which rows failed and
    why, rather than forcing a re-upload of an otherwise-good file.

    Capped at MAX_IMPORT_ROWS to keep this synchronous endpoint from
    being usable to submit an arbitrarily large file and tie up a
    request indefinitely - a real, deliberate limit, not an oversight.

    Only ONE audit entry for the whole import (with a count), not one
    per imported row - unlike bulk-delete/bulk-role-assign, which log
    per item because those are typically small, deliberate batches; an
    import can legitimately be hundreds of rows, and an audit log
    entry per row would flood the log for very little added value over
    a single "imported N leads" entry.
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # -sig strips a UTF-8 BOM, which Excel adds by default on export
    except UnicodeDecodeError:
        raise HTTPException(400, "Could not read this file as UTF-8 text - please export it as a plain CSV.")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "name" not in reader.fieldnames:
        raise HTTPException(400, "CSV must have a 'name' column header. Optional columns: company_name, email, source.")

    rows = list(reader)
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(400, f"This file has {len(rows)} rows - the limit is {MAX_IMPORT_ROWS} per import.")

    imported = 0
    errors: list[dict] = []
    new_leads = []

    for i, row in enumerate(rows, start=2):  # row 1 is the header, so data starts at row 2
        name = (row.get("name") or "").strip()
        if not name:
            errors.append({"row": i, "reason": "'name' is required and was empty"})
            continue
        new_leads.append(Lead(
            org_id=org_id,
            name=name,
            company_name=(row.get("company_name") or "").strip() or None,
            email=(row.get("email") or "").strip() or None,
            source=(row.get("source") or "").strip() or None,
        ))
        imported += 1

    if new_leads:
        db.add_all(new_leads)
        log_audit_event(db, org_id, current_user.id, f"bulk_import ({imported} leads)", "Lead", None)
        db.commit()

    return {"imported": imported, "failed": len(errors), "errors": errors}
