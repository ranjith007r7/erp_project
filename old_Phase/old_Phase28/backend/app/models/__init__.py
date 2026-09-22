"""
Importing every model here (even though nothing in this file *uses* them
directly) is what makes Base.metadata.create_all() aware every table exists.
Forgetting to add a new model to this list is a classic "why isn't my table
being created?!" bug — if you add a new model file, add it here too.
"""
from app.models.organization import Organization
from app.models.role import Role, Permission
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.custom_field import CustomField, CustomFieldValue
from app.models.crm import Account, Contact, Lead, Opportunity
from app.models.sales import Product, Customer, Quotation, QuotationItem, SalesOrder, SalesOrderItem, Invoice
from app.models.finance import ChartOfAccounts, JournalEntry, JournalLine, Payment
from app.models.inventory import ProductCategory, Warehouse, StockLevel, StockMovement
from app.models.procurement import Vendor, PurchaseOrder, PurchaseOrderItem, GoodsReceipt
from app.models.hr import Department, Employee, Attendance, LeaveRequest, PayrollRun, Payslip
from app.models.projects import Project, Task, TimeLog
from app.models.documents import Document, ApprovalWorkflow, ApprovalRequest, ApprovalStep
from app.models.reports import SavedReport

__all__ = [
    "Organization",
    "Role",
    "Permission",
    "User",
    "AuditLog",
    "Notification",
    "CustomField",
    "CustomFieldValue",
    "Account",
    "Contact",
    "Lead",
    "Opportunity",
    "Product",
    "Customer",
    "Quotation",
    "QuotationItem",
    "SalesOrder",
    "SalesOrderItem",
    "Invoice",
    "ChartOfAccounts",
    "JournalEntry",
    "JournalLine",
    "Payment",
    "ProductCategory",
    "Warehouse",
    "StockLevel",
    "StockMovement",
    "Vendor",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "GoodsReceipt",
    "Department",
    "Employee",
    "Attendance",
    "LeaveRequest",
    "PayrollRun",
    "Payslip",
    "Project",
    "Task",
    "TimeLog",
    "Document",
    "ApprovalWorkflow",
    "ApprovalRequest",
    "ApprovalStep",
    "SavedReport",
]
