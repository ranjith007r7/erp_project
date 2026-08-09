"""
Procurement module routes. The mirror image of Sales: instead of a
Quotation->SalesOrder->Invoice chain going OUT to a customer, this is a
PurchaseOrder->GoodsReceipt chain bringing stock IN from a vendor.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.models.procurement import Vendor, PurchaseOrder, PurchaseOrderItem, GoodsReceipt
from app.models.sales import Product
from app.schemas.procurement import (
    VendorCreate, VendorOut,
    PurchaseOrderCreate, PurchaseOrderOut,
)
from app.services.inventory import receive_stock

router = APIRouter(prefix="/api/procurement", tags=["procurement"], dependencies=[Depends(get_current_user)])


# ---------------- Vendors ----------------
@router.post("/vendors", response_model=VendorOut, status_code=201)
def create_vendor(payload: VendorCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    vendor = Vendor(org_id=org_id, **payload.model_dump())
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Vendor).filter(Vendor.org_id == org_id).all()


# ---------------- Purchase Orders ----------------
@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201)
def create_purchase_order(payload: PurchaseOrderCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    vendor = db.query(Vendor).filter(Vendor.id == payload.vendor_id, Vendor.org_id == org_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    po = PurchaseOrder(org_id=org_id, vendor_id=payload.vendor_id, order_date=date.today())
    total = 0
    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.org_id == org_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        total += item.qty * item.unit_price
        po.items.append(PurchaseOrderItem(product_id=item.product_id, qty=item.qty, unit_price=item.unit_price))

    po.total = total
    db.add(po)
    db.commit()
    db.refresh(po)
    return po


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.items))
        .filter(PurchaseOrder.org_id == org_id)
        .order_by(PurchaseOrder.order_date.desc())
        .all()
    )


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderOut)
def receive_purchase_order(po_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    The actual moment stock increases. A Purchase Order existing does NOT
    mean stock exists - only receiving it does, exactly mirroring how a
    Sales Order only reduces stock once it's invoiced/fulfilled.
    """
    po = (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.items))
        .filter(PurchaseOrder.id == po_id, PurchaseOrder.org_id == org_id)
        .first()
    )
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status == "received":
        raise HTTPException(status_code=400, detail="This purchase order has already been received.")

    for item in po.items:
        receive_stock(
            db, org_id,
            product_id=str(item.product_id),
            qty=item.qty,
            ref_type="purchase_order",
            ref_id=str(po.id),
        )

    po.status = "received"
    db.add(GoodsReceipt(org_id=org_id, po_id=po.id, received_date=date.today()))

    db.commit()
    db.refresh(po)
    return po
