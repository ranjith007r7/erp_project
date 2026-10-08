export type WorkRow = {
  id: string; work_number: string; client_name: string; domain: string | null;
  status: string; status_label: string; status_color: string;
  quotation_amount: string; vendor_amount: string; discount_percent: string; discount_amount: string;
  net_payable: string; profit: string; received_amount: string; pending_amount: string;
  handling_department: string | null; handling_department_id: string | null; created_at: string;
};

export type WorkDetail = WorkRow & {
  client_details: string | null; description: string | null; delivered_on: string | null; delivery_note: string | null;
  closed_at: string | null; can_close: boolean;
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
  departments: { id: string; name: string }[];
  employees: { id: string; name: string; employee_code: string | null; department_id: string | null }[];
};

export const inr = (v: string | number) =>
  `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const METHOD_LABEL: Record<string, string> = {
  cash: "Cash", card: "Card", gpay: "GPay", bank_transfer: "Bank transfer", cheque: "Cheque",
};
