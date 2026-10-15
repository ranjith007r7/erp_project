"""
Inventory module routes. Categories are a simple CRUD; stock levels and
movements are READ-ONLY here - stock only ever changes through
app/services/inventory.py, called from Procurement (in) or Sales (out).
There is deliberately no "manually edit stock count" endpoint - if you
need to adjust stock, that should go through a proper movement record
(e.g. a future 'stock adjustment' reason code), never a silent overwrite.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission, user_has_permission
from app.models.inventory import ProductCategory, Warehouse, StockLevel, StockMovement
from app.models.sales import Product
from app.schemas.inventory import (
    ProductCategoryCreate, ProductCategoryOut,
    WarehouseOut, StockLevelOut, StockMovementOut,
)
from app.services.inventory import get_default_warehouse

router = APIRouter(prefix="/api/inventory", tags=["inventory"], dependencies=[Depends(get_current_user)])


@router.post("/categories", response_model=ProductCategoryOut, status_code=201, dependencies=[Depends(require_permission("inventory", "create"))])
def create_category(payload: ProductCategoryCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    category = ProductCategory(org_id=org_id, name=payload.name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.get("/categories", response_model=list[ProductCategoryOut], dependencies=[Depends(require_permission("inventory", "view"))])
def list_categories(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(ProductCategory).filter(ProductCategory.org_id == org_id).all()


@router.get("/warehouses", response_model=list[WarehouseOut], dependencies=[Depends(require_permission("inventory", "view"))])
def list_warehouses(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    # Ensures the default warehouse exists even if nothing has moved stock yet,
    # so the frontend always has at least one warehouse to show.
    get_default_warehouse(db, org_id)
    db.commit()
    return db.query(Warehouse).filter(Warehouse.org_id == org_id).all()


@router.get("/stock-levels", response_model=list[StockLevelOut], dependencies=[Depends(require_permission("inventory", "view"))])
def list_stock_levels(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(StockLevel)
        .join(Product, Product.id == StockLevel.product_id)
        .filter(Product.org_id == org_id)
        .all()
    )


@router.get("/movements", response_model=list[StockMovementOut], dependencies=[Depends(require_permission("inventory", "view"))])
def list_movements(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(StockMovement)
        .filter(StockMovement.org_id == org_id)
        .order_by(StockMovement.created_at.desc())
        .all()
    )


@router.get("/movements/page", dependencies=[Depends(require_permission("inventory", "view"))])
def movements_page(page: int = 1, page_size: int = 15, product_id: str | None = None, direction: str | None = None,
                   db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """One page of the stock ledger (newest first), each row with who/what/which job. Profit is shown only to users who may see works."""
    from math import ceil
    from app.services import movement_details
    page, page_size = max(1, page), min(max(1, page_size), 100)
    q = db.query(StockMovement).filter(StockMovement.org_id == org_id)
    if product_id:
        q = q.filter(StockMovement.product_id == product_id)
    if direction in ("in", "out"):
        q = q.filter(StockMovement.movement_type == direction)
    total = q.count()
    rows = q.order_by(StockMovement.created_at.desc(), StockMovement.id).offset((page - 1) * page_size).limit(page_size).all()
    names = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.org_id == org_id, Product.id.in_({r.product_id for r in rows}))} if rows else {}
    info = movement_details.describe(db, org_id, rows, user_has_permission(db, current_user, "workpage", "view"))
    return {"total": total, "page": page, "page_size": page_size, "total_pages": max(1, ceil(total / page_size)),
            "items": [{"id": r.id, "product_id": r.product_id, "product_name": names.get(r.product_id, "Unknown product"),
                       "movement_type": r.movement_type, "qty": r.qty, "ref_type": r.ref_type, "date": r.date, "created_at": r.created_at,
                       **info.get(r.id, {"title": (r.ref_type or "Movement").replace("_", " ").capitalize(), "details": [], "link": None})} for r in rows]}
