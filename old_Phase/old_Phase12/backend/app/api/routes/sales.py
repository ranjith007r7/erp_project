"""
Sales module routes. Same shape as CRM: every query scoped to the logged-in
user's org_id. The interesting part here is the lifecycle chain:

    Quotation --(accept)--> Sales Order --(fulfill)--> Invoice

Each step is its own endpoint rather than one giant function, because in
real life each step can happen on a different day, sometimes by a
different person (a manager accepts the quote, a warehouse team fulfills
the order, finance sends the invoice).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.sales import Product, Customer, Quotation, QuotationItem, SalesOrder, SalesOrderItem, Invoice
from app.schemas.sales import (
    ProductCreate, ProductOut,
    CustomerCreate, CustomerOut,
    QuotationCreate, QuotationOut, QuotationStatusUpdate,
    SalesOrderOut,
    InvoiceOut,
)
from app.services.accounting import post_invoice_journal_entry
from app.services.inventory import issue_stock

router = APIRouter(prefix="/api/sales", tags=["sales"], dependencies=[Depends(get_current_user)])


# ---------------- Products (minimal stub - see models/sales.py) ----------------
@router.post("/products", response_model=ProductOut, status_code=201, dependencies=[Depends(require_permission("sales", "create"))])
def create_product(payload: ProductCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    product = Product(org_id=org_id, **payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products", response_model=list[ProductOut], dependencies=[Depends(require_permission("sales", "view"))])
def list_products(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Product).filter(Product.org_id == org_id).all()


# ---------------- Customers ----------------
@router.post("/customers", response_model=CustomerOut, status_code=201, dependencies=[Depends(require_permission("sales", "create"))])
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    customer = Customer(org_id=org_id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/customers", response_model=list[CustomerOut], dependencies=[Depends(require_permission("sales", "view"))])
def list_customers(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Customer).filter(Customer.org_id == org_id).all()


# ---------------- Quotations ----------------
@router.post("/quotations", response_model=QuotationOut, status_code=201, dependencies=[Depends(require_permission("sales", "create"))])
def create_quotation(payload: QuotationCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    customer = db.query(Customer).filter(Customer.id == payload.customer_id, Customer.org_id == org_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    quotation = Quotation(org_id=org_id, customer_id=payload.customer_id, opportunity_id=payload.opportunity_id)
    total = 0
    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.org_id == org_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        line_total = item.qty * item.unit_price
        total += line_total
        quotation.items.append(QuotationItem(product_id=item.product_id, qty=item.qty, unit_price=item.unit_price))

    quotation.total = total
    db.add(quotation)
    db.commit()
    db.refresh(quotation)
    return quotation


@router.get("/quotations", response_model=list[QuotationOut], dependencies=[Depends(require_permission("sales", "view"))])
def list_quotations(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(Quotation)
        .options(joinedload(Quotation.items))
        .filter(Quotation.org_id == org_id)
        .order_by(Quotation.created_at.desc())
        .all()
    )


@router.patch("/quotations/{quotation_id}/status", response_model=QuotationOut, dependencies=[Depends(require_permission("sales", "edit"))])
def update_quotation_status(quotation_id: str, payload: QuotationStatusUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id, Quotation.org_id == org_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    quotation.status = payload.status
    db.commit()
    db.refresh(quotation)
    return quotation


@router.post("/quotations/{quotation_id}/accept", response_model=SalesOrderOut, status_code=201, dependencies=[Depends(require_permission("sales", "edit"))])
def accept_quotation(quotation_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Turns an accepted Quotation into a real Sales Order, copying its line
    items across. This is the 'customer said yes' moment.
    """
    quotation = (
        db.query(Quotation)
        .options(joinedload(Quotation.items))
        .filter(Quotation.id == quotation_id, Quotation.org_id == org_id)
        .first()
    )
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if quotation.status == "accepted":
        raise HTTPException(status_code=400, detail="This quotation has already been accepted.")

    order = SalesOrder(
        org_id=org_id,
        customer_id=quotation.customer_id,
        quotation_id=quotation.id,
        order_date=date.today(),
        total=quotation.total,
    )
    for item in quotation.items:
        order.items.append(SalesOrderItem(product_id=item.product_id, qty=item.qty, unit_price=item.unit_price))

    quotation.status = "accepted"
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


# ---------------- Sales Orders ----------------
@router.get("/orders", response_model=list[SalesOrderOut], dependencies=[Depends(require_permission("sales", "view"))])
def list_orders(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(SalesOrder)
        .options(joinedload(SalesOrder.items))
        .filter(SalesOrder.org_id == org_id)
        .order_by(SalesOrder.order_date.desc())
        .all()
    )


@router.post("/orders/{order_id}/invoice", response_model=InvoiceOut, status_code=201, dependencies=[Depends(require_permission("sales", "edit"))])
def generate_invoice(order_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Generates an Invoice from a Sales Order, issues stock for every line
    item (Inventory), AND posts the matching Journal Entry (Finance) - all
    in the SAME database transaction. This is the actual multi-module
    "hand-off" that makes this an ERP: one action here correctly touches
    three modules at once, or none of them, never a partial mix.
    """
    order = (
        db.query(SalesOrder)
        .options(joinedload(SalesOrder.items))
        .filter(SalesOrder.id == order_id, SalesOrder.org_id == org_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Sales order not found")

    existing = db.query(Invoice).filter(Invoice.order_id == order.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="An invoice already exists for this order.")

    # Issue stock for every line item BEFORE creating the invoice - if any
    # item doesn't have enough stock, we fail here and nothing else about
    # this order (invoice, journal entry, status) gets touched at all.
    for item in order.items:
        try:
            issue_stock(
                db, org_id,
                product_id=str(item.product_id),
                product_name=item.product.name,
                qty=item.qty,
                ref_type="sales_order",
                ref_id=str(order.id),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    invoice = Invoice(
        org_id=org_id,
        order_id=order.id,
        customer_id=order.customer_id,
        amount=order.total,
    )
    order.status = "fulfilled"
    db.add(invoice)
    db.flush()  # generates invoice.id, needed for the journal entry reference below

    try:
        post_invoice_journal_entry(db, org_id, str(invoice.id), invoice.amount)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/invoices", response_model=list[InvoiceOut], dependencies=[Depends(require_permission("sales", "view"))])
def list_invoices(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Invoice).filter(Invoice.org_id == org_id).order_by(Invoice.created_at.desc()).all()
