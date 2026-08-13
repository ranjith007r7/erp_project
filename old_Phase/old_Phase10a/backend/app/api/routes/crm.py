"""
CRM module routes. Every route here follows the same shape:
1. Require a logged-in user (get_current_user)
2. Scope every query to that user's organization (get_org_id)
3. Never let one org see or touch another org's rows - this is the
   multi-tenancy rule enforced in code, on every single query.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.models.crm import Account, Contact, Lead, Opportunity
from app.schemas.crm import (
    AccountCreate, AccountOut,
    ContactCreate, ContactOut,
    LeadCreate, LeadOut, LeadStatusUpdate, ConvertLeadRequest,
    OpportunityCreate, OpportunityOut, OpportunityStageUpdate,
)

router = APIRouter(prefix="/api/crm", tags=["crm"], dependencies=[Depends(get_current_user)])


# ---------------- Accounts ----------------
@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    account = Account(org_id=org_id, **payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Account).filter(Account.org_id == org_id).order_by(Account.created_at.desc()).all()


# ---------------- Contacts ----------------
@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    contact = Contact(org_id=org_id, **payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Contact).filter(Contact.org_id == org_id).all()


# ---------------- Leads ----------------
@router.post("/leads", response_model=LeadOut, status_code=201)
def create_lead(payload: LeadCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    lead = Lead(org_id=org_id, **payload.model_dump())
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/leads", response_model=list[LeadOut])
def list_leads(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Lead).filter(Lead.org_id == org_id).order_by(Lead.created_at.desc()).all()


@router.patch("/leads/{lead_id}/status", response_model=LeadOut)
def update_lead_status(lead_id: str, payload: LeadStatusUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.org_id == org_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.status = payload.status
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/leads/{lead_id}/convert", response_model=OpportunityOut, status_code=201)
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
@router.post("/opportunities", response_model=OpportunityOut, status_code=201)
def create_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    opportunity = Opportunity(org_id=org_id, **payload.model_dump())
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Opportunity).filter(Opportunity.org_id == org_id).order_by(Opportunity.created_at.desc()).all()


@router.patch("/opportunities/{opportunity_id}/stage", response_model=OpportunityOut)
def update_opportunity_stage(opportunity_id: str, payload: OpportunityStageUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id, Opportunity.org_id == org_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    opportunity.stage = payload.stage
    db.commit()
    db.refresh(opportunity)
    return opportunity
