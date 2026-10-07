export type Vendor = { id: string; name: string; email?: string | null; contact?: string | null; address?: string | null };
export type Product = { id: string; name: string; unit_price: string };
export type ReceiptFile = { id: string; kind: string; filename: string; content_type: string; size: number };
export type Receipt = {
  id: string; condition: "good" | "bad"; notes?: string | null; received_date?: string | null;
  received_by_name?: string | null; files: ReceiptFile[];
};
export type POItem = { id: string; product_id: string; product_name?: string | null; qty: number; unit_price: string; line_total: string };
export type PurchaseOrder = {
  id: string; po_number?: string | null; vendor_id: string; vendor_name?: string | null; order_date: string;
  status: "pending" | "received" | "defective" | "cancelled"; approval_status: "pending" | "approved" | "rejected";
  total: string; created_by_name?: string | null; created_by_email?: string | null; approved_by_name?: string | null;
  items: POItem[]; receipts: Receipt[];
};
export type EmailPreview = {
  from_name: string; to_name: string; to_email?: string | null; subject: string; body: string; attachments: string[];
};
export type SendResult = { status: "sent" | "logged"; to_email: string; subject: string; message: string };

export const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
