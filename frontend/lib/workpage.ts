export type WorkRow = {
  id: string; work_number: string; client_name: string; domain: string | null;
  status: string; status_label: string; status_color: string;
  quotation_amount: string; vendor_amount: string; discount_percent: string; discount_amount: string;
  net_payable: string; profit: string; received_amount: string; pending_amount: string;
  handling_department: string | null; handling_department_id: string | null; created_at: string;
  client_mobile: string | null; is_pending: boolean; pending_reason: string; allocated_employee_name: string | null;
  delivered_on: string | null; closed_at: string | null;
  work_type: "project" | "sales_order"; sales_order_id: string | null;
  taxable_net: string; cgst_percent: string; sgst_percent: string; cgst_amount: string; sgst_amount: string;
};

export type StockCheckItem = {
  product_id: string; product_name: string; sku: string | null; required: number; available: number; on_hand: number;
  short_by: number; ok: boolean; unpriced: number;
  batches: { batch_id: string; take: number; mrp: string; max_discount_percent: string; expiry_date: string | null; inward_date: string; vendor_name?: string; vendor_amount?: string }[];
};
export type StockCheck = {
  items: StockCheckItem[]; has_items: boolean; all_available: boolean; can_issue: boolean; already_issued: boolean;
  pricing: { limits: { ceiling: string; floor: string; max_discount_percent: string; ceiling_excl_gst?: string; floor_excl_gst?: string; cgst_percent?: string; sgst_percent?: string } | null; violations: string[]; ok: boolean };
};

export type WorkDetail = WorkRow & {
  sales_invoice: { id: string; amount: string; status: string; invoice_number: string | null; document_ready: boolean } | null;
  client_details: string | null; description: string | null; delivered_on: string | null; delivery_note: string | null;
  can_close: boolean; pending_note: string | null; can_cancel: boolean;
  refund: { number: string; status: "pending" | "completed"; received_amount: string; charge_percent: string; charge_amount: string; refund_amount: string; method: string | null; transaction_id: string | null; refund_date: string | null } | null;
  invoice_number: string | null; invoice_ready: boolean; vendor_gst: string; vendor_total_paid: string;
  cancellation: { reason: string; remark: string | null; status_before: string | null; status_before_label: string | null; requested_by: string | null; requested_at: string | null; decided_by: string | null; decided_at: string | null; decision_note: string | null } | null;
  items: { id: string; product_id: string; qty: number; product_name: string | null }[];
  purchased_items: { product_id: string; product_name: string | null; qty: number; cost_rate: string; po_numbers: string }[];
  stock_issues: { id: string; product_id: string; qty: number; cost_rate: string; mrp: string; max_discount_percent: string; product_name: string | null; batch_vendor: string | null }[];
  pricing: { limits: { ceiling: string; floor: string; max_discount_percent: string; ceiling_excl_gst?: string; floor_excl_gst?: string; cgst_percent?: string; sgst_percent?: string } | null; violations: string[] };
  quotation: { id: string; total: string; status: string; created_at: string } | null;
  allocated_employee: { id: string; name: string; employee_code: string | null } | null;
  purchase_orders: {
    id: string; po_number: string | null; vendor_name: string | null; total: string; approval_status: string; status: string;
    ordered_on: string; created_at: string; assigned_to: string | null; approved_by: string | null; approved_at: string | null;
    receipts: { condition: string; received_date: string; notes: string | null; received_by: string | null }[];
    notices: { kind: string; channel: string; to_email: string | null; status: string; created_at: string }[];
  }[];
  payments: { id: string; amount: string; method: string; transaction_id: string | null; note: string | null; paid_on: string; recorded_by: string | null }[];
  events: { id: string; kind: string; title: string; detail: string | null; actor_name: string | null; created_at: string }[];
};

export type WorkMeta = {
  statuses: { key: string; label: string; color: string }[];
  payment_methods: string[];
  cancel_reasons: string[];
  other_reason: string;
  products: { id: string; name: string; sku: string | null }[];
  departments: { id: string; name: string }[];
  employees: { id: string; name: string; employee_code: string | null; department_id: string | null }[];
};

export const inr = (v: string | number) =>
  `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const METHOD_LABEL: Record<string, string> = {
  cash: "Cash", card: "Card", gpay: "GPay", bank_transfer: "Bank transfer", cheque: "Cheque",
};
