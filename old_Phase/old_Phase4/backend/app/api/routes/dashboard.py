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
from app.models.sales import Quotation, SalesOrder, Invoice, Product
from app.models.inventory import StockLevel
from app.models.procurement import PurchaseOrder

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/summary")
def get_summary(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    # Low stock = a product whose current stock is at or below its
    # reorder_level. Products with no StockLevel row yet (never
    # received) count as 0 in stock, which correctly counts as low
    # whenever reorder_level > 0.
    products = db.query(Product).filter(Product.org_id == org_id).all()
    stock_by_product = {
        s.product_id: s.quantity
        for s in db.query(StockLevel).join(Product, Product.id == StockLevel.product_id).filter(Product.org_id == org_id)
    }
    low_stock_count = sum(
        1 for p in products if stock_by_product.get(p.id, 0) <= p.reorder_level and p.reorder_level > 0
    )

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
        "low_stock_products": low_stock_count,
        "pending_purchase_orders": db.query(PurchaseOrder).filter(
            PurchaseOrder.org_id == org_id, PurchaseOrder.status == "pending"
        ).count(),
    }
