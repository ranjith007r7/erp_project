export type WarrantyRow = {
  id: string; work_id: string; work_number: string | null; client_name: string | null; product_name: string | null; qty: number;
  status: string; state: string; warranty_months: number | null; period_label: string | null; start_date: string; end_date: string | null;
  card_number: string | null; invoice_number: string | null;
};
export type WarrantyUnit = {
  id: string; position: number; model_number: string | null; serial_number: string | null;
  manufacture_month: string | null; expiry_date: string | null; prefilled_from_stock: boolean;
};
export type WarrantyDetail = WarrantyRow & {
  amount: string; warranty_terms: string | null; rejection_reason: string | null; no_warranty_reason: string | null;
  units: WarrantyUnit[]; submitted_by_name: string | null; approved_by_name: string | null; approved_at: string | null;
  periods: { months: number; label: string }[]; editable: boolean; out_of_warranty: boolean;
};
export type ClaimFile = { id: string; kind: string; label: string; filename: string; content_type: string; size: number };
export type ClaimRow = {
  id: string; claim_number: string; status: string; status_label: string; warranty_id: string; card_number: string | null;
  work_number: string | null; client_name: string | null; product_name: string | null; serial_number: string | null; out_of_warranty: boolean; created_at: string;
};
export type ClaimDetail = ClaimRow & {
  issue: string; resolution: string | null; decision_note: string | null; decided_by_name: string | null; decided_at: string | null;
  created_by_name: string | null; warranty_start: string | null; warranty_end: string | null; model_number: string | null; manufacture_month: string | null;
  files: ClaimFile[]; required: { kind: string; label: string; image_only: boolean; done: boolean }[]; missing: string[];
  replacement_work: { id: string; work_number: string; status: string } | null;
  vendor: { name: string | null; email: string | null; po_number: string | null; warranty_months: number | null; warranty_end: string | null;
            in_vendor_warranty: boolean | null; traced: boolean; notice_at: string | null; notice_to: string | null; notice_channel: string | null };
};

export const STATE_STYLE: Record<string, string> = {
  "Active": "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
  "Expiring soon": "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
  "Expired": "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300",
  "Details to fill": "bg-indigo-100 text-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300",
  "Waiting for approval": "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
  "No warranty": "bg-slate-100 text-slate-700 dark:bg-zinc-800 dark:text-zinc-300",
  "Cancelled": "bg-slate-100 text-slate-500 dark:bg-zinc-800 dark:text-zinc-400",
};
export const CLAIM_STYLE: Record<string, string> = {
  open: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300",
  pending_approval: "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
  replaced: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
  repaired: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300",
};
export const fmtDate = (d?: string | null) => (d ? new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "-");
