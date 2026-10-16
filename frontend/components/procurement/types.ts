export type Vendor = { id: string; name: string; email?: string | null; contact?: string | null; address?: string | null };
export type Product = { id: string; name: string; unit_price: string; cgst_percent: string; sgst_percent: string };
export type ReceiptFile = { id: string; kind: string; filename: string; content_type: string; size: number };
export type Receipt = {
  id: string; condition: "good" | "bad"; notes?: string | null; received_date?: string | null;
  received_by_name?: string | null; files: ReceiptFile[];
  lines?: { product_name?: string | null; qty_good: number; qty_defective: number }[];
};
export type POItem = { id: string; product_id: string; product_name?: string | null; qty: number; unit_price: string; line_total: string; cgst_percent: string; sgst_percent: string; cgst_amount: string; sgst_amount: string; received_qty?: number; outstanding_qty?: number };
export type PurchaseOrder = {
  id: string; po_number?: string | null; vendor_id: string; vendor_name?: string | null; order_date: string;
  status: "pending" | "received" | "defective" | "cancelled"; approval_status: "pending" | "approved" | "rejected";
  total: string; cgst_amount: string; sgst_amount: string; grand_total: string; created_by_name?: string | null; created_by_email?: string | null; approved_by_name?: string | null;
  items: POItem[]; receipts: Receipt[];
  corrections?: { product_name?: string | null; qty: number; old_price: string; new_price: string; reason: string; corrected_by_name?: string | null; created_at?: string | null }[];
};
export type EmailPreview = {
  from_name: string; to_name: string; to_email?: string | null; subject: string; body: string; attachments: string[];
};
export type SendResult = { status: "sent" | "logged"; to_email: string; subject: string; message: string };

export const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
