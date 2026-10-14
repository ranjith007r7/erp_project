"""
Sales module routes. Same shape as CRM: every query scoped to the logged-in
user's org_id. The interesting part here is the lifecycle chain:

    Quotation --(accept)--> Sales Order --(fulfill)--> Invoice

Each step is its own endpoint rather than one giant function, because in
real life each step can happen on a different day, sometimes by a
different person (a manager accepts the quote, a warehouse team fulfills
the order, finance sends the invoice).
"""
from decimal import Decimal
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.sales import Product, Customer, Quotation, QuotationItem, SalesOrder, SalesOrderItem, Invoice
from app.schemas.sales import (
    ProductCreate, ProductOut, ProductUpdate,
    CustomerCreate, CustomerOut,
    QuotationCreate, QuotationOut, QuotationStatusUpdate,
    SalesOrderOut,
    InvoiceOut,
)
from app.services.accounting import post_invoice_journal_entry
from app.services.invoice_pdf import invoice_pdf
from app.models.finance import Payment
from app.models.organization import Organization, OrganizationProfile
from app.services.inventory import issue_stock
from app.services import stock as stock_svc
from app.services.audit import log_audit_event
from app.services import workpages, gst

router = APIRouter(prefix="/api/sales", tags=["sales"], dependencies=[Depends(get_current_user)])


# ---------------- Products (minimal stub - see models/sales.py) ----------------
@router.post("/products", response_model=ProductOut, status_code=201, dependencies=[Depends(require_permission("sales", "create"))])
def create_product(payload: ProductCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    product = Product(org_id=org_id, **payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductOut, dependencies=[Depends(require_permission("sales", "edit"))])
def update_product(product_id: str, payload: ProductUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """Change a product's price or GST rates. Documents already issued keep the rates they were issued with."""
    product = db.query(Product).filter(Product.id == product_id, Product.org_id == org_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if k == "name" and not v:
            continue
        setattr(product, k, v)
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
    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.org_id == org_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        cg = product.cgst_percent if item.cgst_percent is None else item.cgst_percent
        sg = product.sgst_percent if item.sgst_percent is None else item.sgst_percent
        quotation.items.append(QuotationItem(product_id=item.product_id, qty=item.qty, unit_price=item.unit_price,
                                             cgst_percent=cg, sgst_percent=sg))

    t = gst.summarize(gst.item_lines(quotation.items))
    quotation.subtotal, quotation.cgst_amount, quotation.sgst_amount, quotation.total = t["subtotal"], t["cgst"], t["sgst"], t["total"]
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
def accept_quotation(quotation_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
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
        total=quotation.total, subtotal=quotation.subtotal,
        cgst_amount=quotation.cgst_amount, sgst_amount=quotation.sgst_amount,
    )
    for item in quotation.items:
        order.items.append(SalesOrderItem(product_id=item.product_id, qty=item.qty, unit_price=item.unit_price,
                                          cgst_percent=item.cgst_percent, sgst_percent=item.sgst_percent))

    quotation.status = "accepted"
    db.add(order)
    db.flush()
    workpages.safe(db, workpages.on_quotation_accepted, quotation, order, current_user)   # opens a Workpage entry
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


def next_invoice_number(db: Session, org_id) -> str:
    """INV-0001, 0002 ... per organization. The org row is locked so two simultaneous invoices cannot share a number."""
    from sqlalchemy import func
    from app.models.organization import Organization
    db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
    n = db.query(func.count(Invoice.id)).filter(Invoice.org_id == org_id).scalar() or 0
    while True:
        n += 1
        number = f"INV-{n:04d}"
        if not db.query(Invoice.id).filter(Invoice.org_id == org_id, Invoice.invoice_number == number).first():
            return number


@router.post("/orders/{order_id}/invoice", response_model=InvoiceOut, status_code=201, dependencies=[Depends(require_permission("sales", "edit"))])
def generate_invoice(order_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
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
    issued_cost = Decimal(0)
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
        for b, take in stock_svc.consume_best_effort(db, org_id, item.product_id, item.qty):   # keep the priced lots in step with the total
            issued_cost += Decimal(b.vendor_amount or 0) * take

    invoice = Invoice(
        org_id=org_id,
        invoice_number=next_invoice_number(db, org_id),
        order_id=order.id,
        customer_id=order.customer_id,
        amount=order.total, subtotal=order.subtotal,
        cgst_amount=order.cgst_amount, sgst_amount=order.sgst_amount,
    )
    order.status = "fulfilled"
    db.add(invoice)
    db.flush()  # generates invoice.id, needed for the journal entry reference below

    try:
        post_invoice_journal_entry(db, org_id, str(invoice.id), invoice.amount, invoice.cgst_amount, invoice.sgst_amount)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    workpages.safe(db, workpages.on_invoice_generated, order, invoice, current_user, issued_cost)
    log_audit_event(db, org_id, current_user.id, "generate_invoice", "Invoice", invoice.id)
    db.commit()
    db.refresh(invoice)
    return _invoice_out(db, invoice, Decimal(0))


def _invoice_out(db: Session, inv: Invoice, paid: Decimal | None = None) -> dict:
    if paid is None:
        paid = Decimal(db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.invoice_id == inv.id).scalar() or 0)
    return {"id": inv.id, "order_id": inv.order_id, "customer_id": inv.customer_id, "amount": inv.amount,
            "invoice_number": inv.invoice_number, "subtotal": inv.subtotal, "cgst_amount": inv.cgst_amount,
            "sgst_amount": inv.sgst_amount, "paid_amount": paid, "balance": max(Decimal(inv.amount) - paid, Decimal(0)),
            "document_ready": paid > 0, "due_date": inv.due_date, "status": inv.status, "created_at": inv.created_at}


@router.get("/invoices", response_model=list[InvoiceOut], dependencies=[Depends(require_permission("sales", "view"))])
def list_invoices(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    paid = dict(db.query(Payment.invoice_id, func.sum(Payment.amount)).filter(Payment.org_id == org_id).group_by(Payment.invoice_id).all())
    invs = db.query(Invoice).filter(Invoice.org_id == org_id).order_by(Invoice.created_at.desc()).all()
    return [_invoice_out(db, i, Decimal(paid.get(i.id) or 0)) for i in invs]


@router.get("/invoices/{invoice_id}/pdf", dependencies=[Depends(require_permission("sales", "view"))])
def invoice_document(invoice_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """The printable tax invoice. Issued once a payment has been recorded against the invoice; every field is read from
    the organization profile, the customer, the sales order and Finance's payments, so nothing is typed twice."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.org_id == org_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    payments = db.query(Payment).filter(Payment.invoice_id == inv.id).order_by(Payment.created_at).all()
    if not payments:
        raise HTTPException(status_code=409, detail="The tax invoice is issued once a payment has been recorded against this invoice. Record the payment in Finance first.")
    order = (db.query(SalesOrder).options(joinedload(SalesOrder.items).joinedload(SalesOrderItem.product))
             .filter(SalesOrder.id == inv.order_id, SalesOrder.org_id == org_id).first())
    customer = db.query(Customer).filter(Customer.id == inv.customer_id, Customer.org_id == org_id).first()
    org = db.query(Organization).filter(Organization.id == org_id).first()
    profile = db.query(OrganizationProfile).filter(OrganizationProfile.org_id == org_id).first()
    data = invoice_pdf(org=org, profile=profile, customer=customer, invoice=inv, order=order, items=order.items, payments=payments)
    name = (inv.invoice_number or "invoice") + ".pdf"
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})
