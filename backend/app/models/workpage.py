import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, ForeignKey, DateTime, Date, Numeric, Text, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class WorkOrder(Base):
    """
    One piece of customer work (a "deal in delivery"), tracked from the moment
    it is received until it is delivered, fully paid and closed.

    The money columns hold what people agreed; PROFIT is never stored, it is
    always quotation - discount - vendor (see app/services/workpages.py).
    `status` is moved by people (allocate, deliver, close) AND by other modules
    (a PO raised / received in Procurement) through the service layer, so the
    other modules never import this one's routes.

    Statuses: assigned -> allocated -> (stock in inventory: delivered at once) or
    (stock short: po_not_raised -> po_raised -> in_transit -> po_received -> delivered)
    -> closed ("work done", automatically once fully paid), plus waiting_new_po when
    a received PO turned out defective.
    """
    __tablename__ = "work_orders"
    __table_args__ = (UniqueConstraint("org_id", "work_number", name="uq_work_number"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    work_number = Column(String, nullable=False)                      # "WK-0001"
    client_name = Column(String, nullable=False)
    domain = Column(String, nullable=True)                            # client's industry / domain
    client_details = Column(Text, nullable=True)                      # contact, address, free text
    description = Column(Text, nullable=True)

    status = Column(String, nullable=False, default="assigned", server_default="assigned")

    quotation_amount = Column(Numeric(14, 2), nullable=False, default=0)
    vendor_amount = Column(Numeric(14, 2), nullable=False, default=0)
    discount_percent = Column(Numeric(5, 2), nullable=False, default=0)

    # Optional links back to the records this work grew out of. Plain ids, no
    # relationships to the other modules' models.
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    quotation_id = Column(UUID(as_uuid=True), ForeignKey("quotations.id"), nullable=True)
    sales_order_id = Column(UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=True)

    # Where it came from: a CRM lead converted by the sales team (the normal route).
    lead_id = Column(UUID(as_uuid=True), ForeignKey("crm_leads.id"), nullable=True)
    opportunity_id = Column(UUID(as_uuid=True), ForeignKey("crm_opportunities.id"), nullable=True)
    client_mobile = Column(String, nullable=True)
    # Why it is waiting when stock was short (free text built by the system).
    pending_note = Column(Text, nullable=True)

    handling_department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True)
    allocated_employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)

    delivered_on = Column(Date, nullable=True)
    delivery_note = Column(Text, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # Cancellation: an employee raises it (status -> cancel_pending); only a user holding workpage.cancel_approve decides.
    # Rejected: the work returns to status_before_cancel. Approved: status -> cancelled and its stock goes back to Inventory.
    status_before_cancel = Column(String, nullable=True)
    cancel_reason = Column(String, nullable=True)
    cancel_remark = Column(Text, nullable=True)
    cancel_requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    cancel_decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    cancel_decided_at = Column(DateTime, nullable=True)
    cancel_decision_note = Column(Text, nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    department = relationship("Department")
    allocated_employee = relationship("Employee")
    events = relationship("WorkEvent", back_populates="work", cascade="all, delete-orphan",
                          order_by="WorkEvent.created_at")
    payments = relationship("WorkPayment", back_populates="work", cascade="all, delete-orphan",
                            order_by="WorkPayment.created_at")


class WorkEvent(Base):
    """Append-only history line shown on the work's tracking page."""
    __tablename__ = "work_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    work_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    kind = Column(String, nullable=False)          # created / allocated / po_raised / ... / payment / closed
    title = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_name = Column(String, nullable=True)     # kept as text so history survives user changes
    meta = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    work = relationship("WorkOrder", back_populates="events")


class WorkPayment(Base):
    """Money received from the client for a work: partial or full, by what means."""
    __tablename__ = "work_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    work_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    method = Column(String, nullable=False, default="cash")   # cash / card / gpay / bank_transfer / cheque
    transaction_id = Column(String, nullable=True)
    note = Column(String, nullable=True)
    paid_on = Column(Date, default=date.today)
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    work = relationship("WorkOrder", back_populates="payments")


class WorkItem(Base):
    """What the customer needs for a work: a product and a quantity (checked against inventory)."""
    __tablename__ = "work_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    work_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkStockIssue(Base):
    """Stock taken from inventory for a work, with the rates of the batch it came from (copied, never re-typed)."""
    __tablename__ = "work_stock_issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    work_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("stock_batches.id"), nullable=True)   # null: units that had no priced lot
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False)
    # "inventory": taken through Take from inventory (counts for the MRP / discount rule).
    # "purchased": goods bought on the work's PO, released at delivery (quantity only, no price rule). Both go back on cancel.
    source = Column(String, nullable=False, default="inventory", server_default="inventory")
    cost_rate = Column(Numeric(12, 2), nullable=False)
    mrp = Column(Numeric(12, 2), nullable=False)
    max_discount_percent = Column(Numeric(5, 2), nullable=False, default=0)
    issued_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
