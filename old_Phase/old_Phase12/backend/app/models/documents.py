import uuid
from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Document(Base):
    """
    A stored file reference. file_url points at external storage (S3/R2/
    Cloudinary in production - not built yet, so this holds a plain URL
    for now). related_type/related_id let a document attach to ANY other
    record (an Invoice, an Employee, a Purchase Order) without needing a
    separate join table per module.
    """
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    title = Column(String, nullable=False)
    file_url = Column(String, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    related_type = Column(String, nullable=True)   # e.g. "invoice", "employee"
    related_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApprovalWorkflow(Base):
    """
    A REUSABLE approval rule an org defines once, e.g. 'Expenses over
    ₹10,000 need Manager then Finance approval.' steps_config is a JSON
    list of step definitions - this is what makes the engine generic:
    any module (Procurement, HR, Sales) can trigger a request against
    the SAME workflow definitions instead of each hardcoding its own
    approval logic.

    Example steps_config: [{"role": "Manager"}, {"role": "Finance"}]
    """
    __tablename__ = "approval_workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    module = Column(String, nullable=False)   # e.g. "procurement", "hr"
    steps_config = Column(JSON, nullable=False, default=list)

    requests = relationship("ApprovalRequest", back_populates="workflow")


class ApprovalRequest(Base):
    """
    One actual instance of a workflow being run against one real record -
    e.g. THIS specific Purchase Order needing approval, using the
    'Purchase Orders over ₹X' workflow definition. entity_type/entity_id
    point at the real record, same pattern as Document's related_type/id.
    """
    __tablename__ = "approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("approval_workflows.id"), nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")  # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)

    workflow = relationship("ApprovalWorkflow", back_populates="requests")
    steps = relationship("ApprovalStep", back_populates="request", cascade="all, delete-orphan", order_by="ApprovalStep.step_order")


class ApprovalStep(Base):
    """
    One stage of one approval request - e.g. step 1 = Manager, step 2 =
    Finance. Steps are approved IN ORDER: step 2 can't be actioned until
    step 1 is approved. This row-per-step design (vs a single status
    field) is what lets a request show exactly who approved what, and
    when, later - a proper audit trail, same philosophy as Journal Lines
    or Stock Movements.
    """
    __tablename__ = "approval_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_request_id = Column(UUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=False)
    step_order = Column(Integer, nullable=False)
    role_required = Column(String, nullable=False)
    approver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")  # pending / approved / rejected
    acted_at = Column(DateTime, nullable=True)

    request = relationship("ApprovalRequest", back_populates="steps")
