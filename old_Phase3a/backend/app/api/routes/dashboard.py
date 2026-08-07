"""
One small endpoint that gives the Dashboard page real numbers instead of
static placeholder text. Deliberately simple counts for now - as each
module gains real business meaning (e.g. "open opportunities value"),
this endpoint grows, but the frontend contract (one JSON object of
summary numbers) stays the same.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.models.crm import Lead, Opportunity
from app.models.sales import Quotation, SalesOrder, Invoice

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/summary")
def get_summary(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return {
        "leads": db.query(Lead).filter(Lead.org_id == org_id).count(),
        "open_opportunities": db.query(Opportunity).filter(
            Opportunity.org_id == org_id, Opportunity.stage.notin_(["won", "lost"])
        ).count(),
        "quotations": db.query(Quotation).filter(Quotation.org_id == org_id).count(),
        "sales_orders": db.query(SalesOrder).filter(SalesOrder.org_id == org_id).count(),
        "unpaid_invoices": db.query(Invoice).filter(
            Invoice.org_id == org_id, Invoice.status == "unpaid"
        ).count(),
    }
