"""
Same shape as app/services/accounting.py: the ONE place that knows how to
move stock, so Procurement (stock in) and Sales (stock out) both call into
here instead of each writing their own copy of "update StockLevel and log
a StockMovement" logic. Living here also avoids Sales and Procurement/
Inventory needing to import each other directly.
"""
from sqlalchemy.orm import Session

from app.models.inventory import Warehouse, StockLevel, StockMovement

DEFAULT_WAREHOUSE_NAME = "Main Warehouse"


def get_default_warehouse(db: Session, org_id: str) -> Warehouse:
    """
    Self-healing, same pattern as get_account() in accounting.py: every
    organization needs at least one warehouse before stock can move, but
    rather than requiring it to be seeded at signup (and hitting the exact
    same "old org missing new data" trap we already fixed once in
    Finance), we create it lazily the first time it's actually needed.
    """
    warehouse = db.query(Warehouse).filter(Warehouse.org_id == org_id).first()
    if warehouse:
        return warehouse

    warehouse = Warehouse(org_id=org_id, name=DEFAULT_WAREHOUSE_NAME)
    db.add(warehouse)
    db.flush()
    return warehouse


def _get_or_create_stock_level(db: Session, product_id: str, warehouse_id: str) -> StockLevel:
    level = (
        db.query(StockLevel)
        .filter(StockLevel.product_id == product_id, StockLevel.warehouse_id == warehouse_id)
        .first()
    )
    if not level:
        level = StockLevel(product_id=product_id, warehouse_id=warehouse_id, quantity=0)
        db.add(level)
        db.flush()
    return level


def receive_stock(db: Session, org_id: str, product_id: str, qty: int, ref_type: str, ref_id: str) -> StockMovement:
    """Stock coming IN - called when a Purchase Order's goods are received."""
    warehouse = get_default_warehouse(db, org_id)
    level = _get_or_create_stock_level(db, product_id, warehouse.id)
    level.quantity += qty

    movement = StockMovement(
        org_id=org_id, product_id=product_id, warehouse_id=warehouse.id,
        movement_type="in", qty=qty, ref_type=ref_type, ref_id=ref_id,
    )
    db.add(movement)
    return movement


def issue_stock(db: Session, org_id: str, product_id: str, product_name: str, qty: int, ref_type: str, ref_id: str) -> StockMovement:
    """
    Stock going OUT - called when a Sales Order is fulfilled. Raises
    ValueError if there isn't enough stock, rather than silently letting
    the count go negative - this is the actual point of Inventory
    existing: Sales can no longer promise something that isn't there.
    """
    warehouse = get_default_warehouse(db, org_id)
    level = _get_or_create_stock_level(db, product_id, warehouse.id)

    if level.quantity < qty:
        raise ValueError(
            f"Insufficient stock for '{product_name}': "
            f"{level.quantity} available, {qty} required."
        )

    level.quantity -= qty

    movement = StockMovement(
        org_id=org_id, product_id=product_id, warehouse_id=warehouse.id,
        movement_type="out", qty=qty, ref_type=ref_type, ref_id=ref_id,
    )
    db.add(movement)
    return movement
