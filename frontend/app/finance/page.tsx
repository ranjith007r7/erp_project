"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiRequest, apiBlob, openBlob } from "@/lib/api";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { SkeletonList } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";
import { useCurrentUser } from "@/components/AppShell";

type Account = { id: string; code: string; name: string; account_type: string };
type JournalLine = { account_id: string; debit: string; credit: string };
type JournalEntry = { id: string; entry_number: string | null; date: string; reference: string | null; description: string | null; lines: JournalLine[] };
type Invoice = { id: string; amount: string; status: string; invoice_number: string | null; paid_amount: string; balance: string; document_ready: boolean; cgst_amount: string; sgst_amount: string; subtotal: string };
type Payment = { id: string; invoice_id: string; amount: string; method: string; transaction_id: string | null; date: string };
type Run = { id: string; month: number; year: number; status: string };
type LeaveType = { id: string; code: string; name: string; days_per_year: string | null; per_month: string | null; paid: boolean; note: string | null };
type DeductionRow = {
  employee_id: string; employee_code: string | null; name: string; designation: string | null; salary: string;
  configured: boolean; pf_percent: string; insurance_percent: string; tds_percent: string; lop_days: string | null;
};
type Method = "cash" | "card" | "gpay";

const METHOD_LABEL: Record<string, string> = { cash: "Cash", card: "Card", gpay: "GPay", bank_transfer: "Bank transfer", cheque: "Cheque" };
const REFUND_METHODS = ["cash", "card", "gpay", "bank_transfer", "cheque"] as const;
const fmt = (v: string | number) => Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN")}`;

const RECON_LABEL: Record<string, string> = { matched: "Matched", mismatch: "Mismatch", awaiting_payment: "Awaiting payment", part_paid: "Part paid", not_started: "Not started", paid_awaiting_delivery: "Paid, awaiting delivery", cancelled: "Cancelled", cancelled_refund_due: "Cancelled, refund due", cancelled_refunded: "Cancelled, refunded" };
type ReconRow = {
  work_id: string; work_number: string; work_type?: string; client_name: string; status_label: string; quoted_net: number; received: number;
  booked_in_finance: number; difference: number; state: string; note: string; refunded?: number; kept?: number; refund_number?: string | null;
};
type GstMonth = { month: string; output_gst: number; input_credit: number; blocked: number; net_payable: number; out_cgst: number; out_sgst: number; in_cgst: number; in_sgst: number };
type GstLedger = { batch_id: string; date: string; product_name: string | null; vendor_name: string; po_number: string | null; quantity: number; taxable_value: number; cgst: number; sgst: number; total_gst: number; eligible: boolean };
type GstSummary = { months: GstMonth[]; ledger: GstLedger[]; totals: { output_gst: number; input_credit: number; blocked: number; net_payable: number } };
type Refund = {
  id: string; refund_number: string; work_id: string; work_number: string | null; invoice_number: string | null; client_name: string; reason: string | null;
  received_amount: string; charge_percent: string; charge_amount: string; refund_amount: string; status: "pending" | "completed";
  method: string | null; transaction_id: string | null; note: string | null; refund_date: string | null; completed_by_name: string | null; kind: string;
};
type PricingRow = {
  work_id: string; work_number: string; client_name: string; status_label: string; net_payable: number; mrp_total: number;
  lowest_allowed: number; effective_discount_percent: number; max_discount_percent: number; ok: boolean; violations: string[];
};

export default function FinancePage() {
  const { showToast } = useToast();
  const { can } = useCurrentUser();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [rows, setRows] = useState<DeductionRow[]>([]);
  const [runId, setRunId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [recon, setRecon] = useState<{ matched: number; mismatch: number; open: number; works: ReconRow[] } | null>(null);
  const [pricing, setPricing] = useState<{ checked: number; violations: number; works: PricingRow[] } | null>(null);

  const [gstSum, setGstSum] = useState<GstSummary | null>(null);
  const [refunds, setRefunds] = useState<Refund[]>([]);
  const [rfFor, setRfFor] = useState<Refund | null>(null);
  const [rfCharge, setRfCharge] = useState("0");
  const [rfMethod, setRfMethod] = useState<(typeof REFUND_METHODS)[number]>("cash");
  const [rfTxn, setRfTxn] = useState("");
  const [rfNote, setRfNote] = useState("");
  const [rfBusy, setRfBusy] = useState(false);
  const [rfError, setRfError] = useState<string | null>(null);

  const [payFor, setPayFor] = useState<Invoice | null>(null);
  const [payAmount, setPayAmount] = useState("");
  const [method, setMethod] = useState<Method>("cash");
  const [txn, setTxn] = useState("");
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  function loadDeductions(id: string) {
    apiRequest<DeductionRow[]>(`/api/finance/payroll-deductions${id ? `?run_id=${id}` : ""}`, { auth: true })
      .then(setRows).catch(() => setRows([]));
  }

  function loadAll() {
    Promise.allSettled([
      apiRequest<Account[]>("/api/finance/accounts", { auth: true }).then(setAccounts).catch((e) => setError(e.message)),
      apiRequest<JournalEntry[]>("/api/finance/journal-entries", { auth: true }).then(setEntries),
      apiRequest<Invoice[]>("/api/sales/invoices", { auth: true }).then(setInvoices),
      apiRequest<Payment[]>("/api/finance/payments", { auth: true }).then(setPayments),
      apiRequest<Refund[]>("/api/finance/refunds", { auth: true }).then(setRefunds).catch(() => {}),
      apiRequest<GstSummary>("/api/finance/gst-summary", { auth: true }).then(setGstSum).catch(() => {}),
      apiRequest<{ matched: number; mismatch: number; open: number; works: ReconRow[] }>("/api/finance/work-reconciliation", { auth: true }).then(setRecon).catch(() => {}),
      apiRequest<{ checked: number; violations: number; works: PricingRow[] }>("/api/finance/pricing-check", { auth: true }).then(setPricing).catch(() => {}),
      apiRequest<LeaveType[]>("/api/finance/leave-types", { auth: true }).then(setLeaveTypes),
      apiRequest<Run[]>("/api/finance/payroll-runs", { auth: true }).then((r) => {
        setRuns(r);
        const open = r.find((x) => x.status !== "processed");
        setRunId((cur) => cur || open?.id || "");
      }),
    ]).finally(() => setLoading(false));
  }
  useEffect(loadAll, []);
  useEffect(() => { loadDeductions(runId); }, [runId]);

  function accountName(id: string) {
    return accounts.find((a) => a.id === id)?.name || id.slice(0, 8);
  }

  const needsTxn = method !== "cash";
  const txnOk = !needsTxn || /^[A-Za-z0-9._\-/]{4,64}$/.test(txn.trim());

  function openPay(inv: Invoice) {
    setPayFor(inv); setPayAmount(String(Number(inv.balance))); setMethod("cash"); setTxn(""); setPayError(null);
  }

  async function confirmPayment() {
    if (!payFor) return;
    setPaying(true); setPayError(null);
    try {
      await apiRequest("/api/finance/payments", {
        method: "POST", auth: true,
        body: { invoice_id: payFor.id, amount: Number(payAmount), method, transaction_id: needsTxn ? txn.trim() : null },
      });
      setPayFor(null);
      showToast("Payment recorded", "success");
      loadAll();
    } catch (err) {
      setPayError(err instanceof Error ? err.message : "Failed to record payment");
    }
    setPaying(false);
  }

  const rfCp = Math.min(100, Math.max(0, Number(rfCharge) || 0));
  const rfReceived = rfFor ? Number(rfFor.received_amount) : 0;
  const rfCharged = Math.round(rfReceived * rfCp) / 100;
  const rfPay = Math.round((rfReceived - rfCharged) * 100) / 100;
  const rfNeedsTxn = rfPay > 0 && rfMethod !== "cash";
  const rfTxnOk = !rfNeedsTxn || /^[A-Za-z0-9._\-/]{4,64}$/.test(rfTxn.trim());
  const pendingRefunds = refunds.filter((r) => r.status === "pending");

  function openRefund(r: Refund) {
    setRfFor(r); setRfCharge("0"); setRfMethod("cash"); setRfTxn(""); setRfNote(""); setRfError(null);
  }

  async function completeRefund() {
    if (!rfFor) return;
    setRfBusy(true); setRfError(null);
    try {
      await apiRequest(`/api/finance/refunds/${rfFor.id}/complete`, {
        method: "POST", auth: true,
        body: { charge_percent: rfCp, method: rfPay > 0 ? rfMethod : null, transaction_id: rfNeedsTxn ? rfTxn.trim() : null, note: rfNote.trim() || null },
      });
      setRfFor(null);
      showToast("Refund completed", "success");
      loadAll();
    } catch (err) {
      setRfError(err instanceof Error ? err.message : "Could not complete the refund");
    }
    setRfBusy(false);
  }

  const unpaidInvoices = invoices.filter((inv) => inv.status !== "paid");
  const taxInvoices = invoices.filter((inv) => inv.document_ready);

  async function openTaxInvoice(inv: Invoice) {
    try {
      openBlob(await apiBlob(`/api/sales/invoices/${inv.id}/pdf`), `${inv.invoice_number || "invoice"}.pdf`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not open the invoice", "error");
    }
  }
  const selectedRun = runs.find((r) => r.id === runId);
  const locked = selectedRun?.status === "processed";
  const unconfigured = rows.filter((r) => !r.configured).length;

  function setRow(id: string, patch: Partial<DeductionRow>) {
    setRows((rs) => rs.map((r) => (r.employee_id === id ? { ...r, ...patch } : r)));
  }

  async function saveRow(r: DeductionRow) {
    try {
      await apiRequest(`/api/finance/payroll-deductions/${r.employee_id}`, {
        method: "PUT", auth: true,
        body: { pf_percent: Number(r.pf_percent) || 0, insurance_percent: Number(r.insurance_percent) || 0, tds_percent: Number(r.tds_percent) || 0 },
      });
      if (runId && !locked && r.lop_days !== null) {
        await apiRequest(`/api/finance/payroll-runs/${runId}/lop/${r.employee_id}`, { method: "PUT", auth: true, body: { lop_days: Number(r.lop_days) || 0 } });
      }
      setRow(r.employee_id, { configured: true });
      showToast(`Saved deductions for ${r.name}`, "success");
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not save", "error");
    }
  }

  const preview = useMemo(() => {
    const now = new Date();
    return selectedRun ? new Date(selectedRun.year, selectedRun.month, 0).getDate() : new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  }, [selectedRun]);

  function netFor(r: DeductionRow) {
    const g = Number(r.salary);
    const pct = (Number(r.pf_percent) + Number(r.insurance_percent) + Number(r.tds_percent)) / 100;
    const leave = Math.min((g / preview) * (Number(r.lop_days) || 0), g * (1 - pct));
    return g - g * pct - leave;
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Finance & Accounting" />
      {error && <p className="text-red-600 dark:text-red-400 text-sm mb-4">{error}</p>}

      {loading ? (
        <SkeletonList rows={3} />
      ) : (
        <>
          {gstSum && (gstSum.months.length > 0) && (
            <section className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 mb-6" data-testid="gst-summary">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm mb-1">GST summary</h2>
              <p className="text-xs text-slate-500 dark:text-zinc-500 mb-3">
                GST collected from customers belongs to the government; GST you paid vendors is claimed back as credit. You remit only the difference.
                Collected comes from the books (credit notes and refunds already reduce it); credit comes from the stock lots you bought (Stock Intake / purchase orders).
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                {[["Collected from customers", gstSum.totals.output_gst, ""], ["Credit on purchases", gstSum.totals.input_credit, ""],
                  [gstSum.totals.net_payable >= 0 ? "Net GST to pay" : "Credit carried forward", Math.abs(gstSum.totals.net_payable), "gst-net-total"], ["GST not claimable (cost)", gstSum.totals.blocked, ""]].map(([t, v, id]) => (
                  <div key={String(t)} className="rounded-lg bg-slate-50 dark:bg-zinc-800 p-3"><p className="text-xs text-slate-500 dark:text-zinc-400">{t}</p><p className="text-lg font-semibold text-slate-800 dark:text-white" data-testid={String(id) || undefined}>{inr(Number(v))}</p></div>
                ))}
              </div>
              <div className="overflow-x-auto mb-4">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-500 border-b border-slate-200 dark:border-zinc-800"><th className="py-2 pr-3">Month</th><th className="pr-3 text-right">Collected (CGST / SGST)</th><th className="pr-3 text-right">Credit (CGST / SGST)</th><th className="pr-3 text-right">Not claimable</th><th className="text-right">Net payable</th></tr></thead>
                  <tbody>{gstSum.months.map((m) => (
                    <tr key={m.month} className="border-b border-slate-100 dark:border-zinc-800">
                      <td className="py-2 pr-3">{m.month}</td>
                      <td className="pr-3 text-right tabular-nums">{fmt(m.output_gst)} <span className="text-xs text-slate-400">({fmt(m.out_cgst)} / {fmt(m.out_sgst)})</span></td>
                      <td className="pr-3 text-right tabular-nums">{fmt(m.input_credit)} <span className="text-xs text-slate-400">({fmt(m.in_cgst)} / {fmt(m.in_sgst)})</span></td>
                      <td className="pr-3 text-right tabular-nums">{fmt(m.blocked)}</td>
                      <td className={`text-right tabular-nums font-semibold ${m.net_payable < 0 ? "text-emerald-600" : ""}`}>{m.net_payable < 0 ? `${fmt(-m.net_payable)} credit` : fmt(m.net_payable)}</td>
                    </tr>))}</tbody>
                </table>
              </div>
              {gstSum.ledger.length > 0 && (
                <details>
                  <summary className="text-xs font-medium cursor-pointer text-slate-600 dark:text-zinc-300">GST credit ledger ({gstSum.ledger.length} purchase lot{gstSum.ledger.length === 1 ? "" : "s"})</summary>
                  <div className="overflow-x-auto mt-2">
                    <table className="w-full text-sm">
                      <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-500 border-b border-slate-200 dark:border-zinc-800"><th className="py-2 pr-3">Date</th><th className="pr-3">Product</th><th className="pr-3">Vendor / PO</th><th className="pr-3 text-right">Qty</th><th className="pr-3 text-right">Taxable</th><th className="pr-3 text-right">CGST</th><th className="pr-3 text-right">SGST</th><th>Credit</th></tr></thead>
                      <tbody>{gstSum.ledger.map((l) => (
                        <tr key={l.batch_id} className="border-b border-slate-100 dark:border-zinc-800">
                          <td className="py-1.5 pr-3">{l.date}</td><td className="pr-3">{l.product_name}</td><td className="pr-3">{l.vendor_name}{l.po_number && <span className="text-xs text-slate-400"> · {l.po_number}</span>}</td>
                          <td className="pr-3 text-right">{l.quantity}</td><td className="pr-3 text-right tabular-nums">{fmt(l.taxable_value)}</td><td className="pr-3 text-right tabular-nums">{fmt(l.cgst)}</td><td className="pr-3 text-right tabular-nums">{fmt(l.sgst)}</td>
                          <td className={l.eligible ? "text-emerald-600" : "text-amber-600"}>{l.eligible ? "Claimable" : "Not claimable"}</td>
                        </tr>))}</tbody>
                    </table>
                  </div>
                </details>
              )}
            </section>
          )}
          {refunds.length > 0 && (
            <section className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 mb-6" data-testid="refunds">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm mb-1">Refunds {pendingRefunds.length > 0 && <span className="ml-1 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200 px-2 py-0.5 text-xs">{pendingRefunds.length} pending</span>}</h2>
              <p className="text-xs text-slate-500 dark:text-zinc-500 mb-3">
                A cancelled work (or a cancelled Sales order after its invoice, which is reversed with a credit note) that had received money lands here. Set the cancellation charge in percent, choose how it is paid back, paste the transaction id for anything that is not cash, and mark it completed.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-500 border-b border-slate-200 dark:border-zinc-800"><th className="py-2 pr-3">Refund</th><th className="pr-3">Work</th><th className="pr-3">Client</th><th className="pr-3 text-right">Received</th><th className="pr-3 text-right">Charge</th><th className="pr-3 text-right">Refunded</th><th className="pr-3">Paid via</th><th>Status</th></tr></thead>
                  <tbody>
                    {refunds.map((r) => (
                      <tr key={r.id} className="border-b border-slate-100 dark:border-zinc-800 align-top" data-testid={`refund-${r.refund_number}`}>
                        <td className="py-2 pr-3">{r.refund_number}{r.kind === "sales_invoice" && <div className="text-xs text-indigo-600 dark:text-indigo-300">Credit note {r.invoice_number}</div>}</td>
                        <td className="pr-3">{r.work_number}</td><td className="pr-3">{r.client_name}{r.reason && <div className="text-xs text-slate-500">{r.reason}</div>}</td>
                        <td className="pr-3 text-right tabular-nums">{fmt(r.received_amount)}</td>
                        <td className="pr-3 text-right tabular-nums">{r.status === "completed" ? `${fmt(r.charge_amount)} (${Number(r.charge_percent)}%)` : "-"}</td>
                        <td className="pr-3 text-right tabular-nums">{r.status === "completed" ? fmt(r.refund_amount) : "-"}</td>
                        <td className="pr-3">{r.method ? METHOD_LABEL[r.method] ?? r.method : "-"}{r.transaction_id && <div className="text-xs text-slate-500">Ref {r.transaction_id}</div>}</td>
                        <td>
                          {r.status === "pending" ? (
                            can("finance", "refund")
                              ? <Button size="sm" onClick={() => openRefund(r)} data-testid={`refund-open-${r.refund_number}`}>Process refund</Button>
                              : <span className="text-amber-600 text-xs">Pending (needs refund permission)</span>
                          ) : <span className="text-emerald-600 font-semibold">Completed</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {recon && recon.works.length > 0 && (
            <section className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 mb-6" data-testid="work-reconciliation">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm mb-1">Work payment reconciliation</h2>
              <p className="text-xs text-slate-500 dark:text-zinc-500 mb-3">
                A work becomes <b>Work done</b> only when the amount quoted (net of discount) equals the amount received, and Finance has booked the same amount.{" "}
                <b className="text-emerald-600">{recon.matched} matched</b> · <b className="text-amber-600">{recon.open} open</b> · <b className={recon.mismatch ? "text-red-600" : ""}>{recon.mismatch} mismatch</b>
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-500 border-b border-slate-200 dark:border-zinc-800"><th className="py-2 pr-3">Work</th><th className="pr-3">Client</th><th className="pr-3">Status</th><th className="pr-3 text-right">Quoted (net)</th><th className="pr-3 text-right">Received</th><th className="pr-3 text-right">Booked in Finance</th><th className="pr-3 text-right">Difference</th><th>Result</th></tr></thead>
                  <tbody>
                    {recon.works.map((r) => (
                      <tr key={r.work_id} className="border-b border-slate-100 dark:border-zinc-800 align-top">
                        <td className="py-2 pr-3">{r.work_number}{r.work_type === "sales_order" && <div className="text-xs text-indigo-600 dark:text-indigo-300">Sales order</div>}</td><td className="pr-3">{r.client_name}</td><td className="pr-3">{r.status_label}</td>
                        <td className="pr-3 text-right tabular-nums">{Number(r.quoted_net).toLocaleString("en-IN")}</td>
                        <td className="pr-3 text-right tabular-nums">{Number(r.received).toLocaleString("en-IN")}</td>
                        <td className="pr-3 text-right tabular-nums">{Number(r.booked_in_finance).toLocaleString("en-IN")}</td>
                        <td className="pr-3 text-right tabular-nums">{Number(r.difference).toLocaleString("en-IN")}</td>
                        <td className={r.state === "matched" || r.state === "cancelled_refunded" ? "text-emerald-600" : r.state === "mismatch" ? "text-red-600" : "text-amber-600"}><span className="font-semibold">{RECON_LABEL[r.state] ?? r.state}</span>{r.state !== "matched" && <span className="block text-xs">{r.note}</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {pricing && pricing.checked > 0 && (
            <section className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 mb-6">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm mb-1">Pricing check - works billed from stock</h2>
              <p className="text-xs text-slate-500 dark:text-zinc-500 mb-3">
                Each bill must stay at or under the MRP of the stock taken and within its maximum discount.{" "}
                {pricing.violations ? <b className="text-red-600">{pricing.violations} work(s) break the rule.</b> : <b className="text-emerald-600">All {pricing.checked} work(s) comply.</b>}
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-500 border-b border-slate-200 dark:border-zinc-800"><th className="py-2 pr-3">Work</th><th className="pr-3">Client</th><th className="pr-3">Billed (net)</th><th className="pr-3">MRP total</th><th className="pr-3">Lowest allowed</th><th className="pr-3">Discount given / allowed</th><th>Result</th></tr></thead>
                  <tbody>
                    {pricing.works.map((r) => (
                      <tr key={r.work_id} className="border-b border-slate-100 dark:border-zinc-800 align-top">
                        <td className="py-2 pr-3">{r.work_number}</td><td className="pr-3">{r.client_name}</td>
                        <td className="pr-3">{Number(r.net_payable).toLocaleString("en-IN")}</td><td className="pr-3">{Number(r.mrp_total).toLocaleString("en-IN")}</td>
                        <td className="pr-3">{Number(r.lowest_allowed).toLocaleString("en-IN")}</td>
                        <td className="pr-3">{r.effective_discount_percent}% / {r.max_discount_percent}%</td>
                        <td className={r.ok ? "text-emerald-600" : "text-red-600"}>{r.ok ? "OK" : r.violations.join(" ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <div className="grid md:grid-cols-3 gap-4" data-testid="finance-launchers">
            {[
              { href: "/finance/accounts", id: "open-accounts", t: "Chart of Accounts", s: `${accounts.length} accounts` },
              { href: "/finance/invoices", id: "open-invoices", t: "Invoices", s: `${invoices.length} invoices · ${payments.length} payments` },
              { href: "/finance/journal", id: "open-journal", t: "Journal Entries", s: `${entries.length}+ entries` },
            ].map((c) => (
              <Link key={c.href} href={c.href} data-testid={c.id}
                className="block rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 hover:border-indigo-400 transition">
                <div className="font-semibold text-slate-700 dark:text-zinc-200">{c.t}</div>
                <div className="text-sm text-slate-500 dark:text-zinc-400 mt-1">{c.s}</div>
                <div className="text-xs text-indigo-600 dark:text-indigo-400 mt-2">Open →</div>
              </Link>
            ))}
          </div>

          <section className="mt-10" data-testid="deductions">
            <div className="flex flex-wrap items-end justify-between gap-3 mb-2">
              <div>
                <h2 className="font-semibold text-slate-700 dark:text-zinc-200">Payroll Deductions</h2>
                <p className="text-xs text-slate-500 dark:text-zinc-400 max-w-2xl">
                  Fill this in for each employee before payroll is processed. PF, insurance and TDS are percentages of salary (enter 0 if not applicable). Unpaid leave is a number of days for the chosen payroll month.
                </p>
              </div>
              <div className="w-64">
                <Select aria-label="Payroll run" value={runId} onChange={(e) => setRunId(e.target.value)}>
                  <option value="">No payroll run selected</option>
                  {runs.map((r) => <option key={r.id} value={r.id}>{r.month}/{r.year} · {r.status}</option>)}
                </Select>
              </div>
            </div>
            {unconfigured > 0 && (
              <p className="text-sm rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800/60 text-amber-800 dark:text-amber-200 p-2 mb-3">
                {unconfigured} employee{unconfigured > 1 ? "s have" : " has"} no deductions saved yet. They would be paid in full with 0% deductions.
              </p>
            )}
            {locked && <p className="text-xs text-slate-500 dark:text-zinc-400 mb-2">This run is processed, so its unpaid-leave days are locked. Percentage changes apply from the next run.</p>}

            <div className="grid lg:grid-cols-3 gap-6">
              <Card className="lg:col-span-2 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 dark:text-zinc-400">
                      <th className="p-2">Employee</th><th className="p-2">Salary</th><th className="p-2">PF %</th><th className="p-2">Insurance %</th>
                      <th className="p-2">TDS %</th><th className="p-2">Unpaid leave days</th><th className="p-2">Est. net</th><th className="p-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-zinc-800">
                    {rows.map((r) => (
                      <tr key={r.employee_id} data-testid={`ded-${r.employee_code}`}>
                        <td className="p-2"><p className="font-medium text-slate-800 dark:text-white">{r.name}</p><p className="text-xs text-slate-500 dark:text-zinc-400">{r.employee_code} · {r.designation || "-"}</p></td>
                        <td className="p-2 whitespace-nowrap text-slate-700 dark:text-zinc-200">{inr(r.salary)}</td>
                        {(["pf_percent", "insurance_percent", "tds_percent"] as const).map((k) => (
                          <td key={k} className="p-2 w-20">
                            <Input aria-label={`${r.name} ${k}`} type="number" min={0} max={100} step="0.01" value={r[k]} onChange={(e) => setRow(r.employee_id, { [k]: e.target.value })} />
                          </td>
                        ))}
                        <td className="p-2 w-24">
                          {r.lop_days === null ? <span className="text-xs text-slate-400">pick a run</span> : (
                            <Input aria-label={`${r.name} unpaid leave days`} type="number" min={0} step="0.5" disabled={locked} value={r.lop_days} onChange={(e) => setRow(r.employee_id, { lop_days: e.target.value })} />
                          )}
                        </td>
                        <td className="p-2 whitespace-nowrap text-slate-700 dark:text-zinc-200">{inr(Math.round(netFor(r)))}</td>
                        <td className="p-2"><Button size="sm" variant={r.configured ? "secondary" : "primary"} onClick={() => saveRow(r)}>{r.configured ? "Update" : "Save"}</Button></td>
                      </tr>
                    ))}
                    {rows.length === 0 && <tr><td colSpan={8} className="p-3 text-slate-400 dark:text-zinc-500">No employees yet. HR adds them first.</td></tr>}
                  </tbody>
                </table>
              </Card>

              <Card className="p-3 h-fit" >
                <h3 className="font-semibold text-sm text-slate-700 dark:text-zinc-200 mb-2">Leave legend</h3>
                <p className="text-xs text-slate-500 dark:text-zinc-400 mb-2">Standard entitlements. Only unpaid types cost salary: count those days in &quot;Unpaid leave days&quot;. One day costs salary ÷ days in the month.</p>
                <ul className="space-y-1.5">
                  {leaveTypes.map((t) => (
                    <li key={t.id} className="text-xs flex justify-between gap-2">
                      <span className="text-slate-800 dark:text-zinc-100"><b>{t.code}</b> {t.name}</span>
                      <span className={t.paid ? "text-slate-500 dark:text-zinc-400" : "text-red-600 dark:text-red-400 font-medium"}>
                        {t.paid ? `${t.per_month ? `${Number(t.per_month)}/mo · ` : ""}${t.days_per_year ? `${Number(t.days_per_year)}/yr` : "as earned"}` : "UNPAID"}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          </section>
        </>
      )}

      {rfFor && (
        <Modal title={`Refund ${rfFor.refund_number}`} onClose={() => setRfFor(null)}>
          <div className="space-y-3">
            <p className="text-sm text-slate-600 dark:text-zinc-300">{rfFor.work_number} · {rfFor.client_name}. The customer had paid <b>{inr(rfFor.received_amount)}</b> (GST included).</p>
            <Input label="Cancellation charge (% of the amount received, 0 = full refund)" type="number" min="0" max="100" step="0.01" value={rfCharge} onChange={(e) => setRfCharge(e.target.value)} data-testid="refund-charge" />
            <div className="rounded-lg bg-slate-50 dark:bg-zinc-800 p-3 text-sm space-y-1" data-testid="refund-split">
              <div className="flex justify-between"><span>Amount received</span><span className="tabular-nums">{fmt(rfReceived)}</span></div>
              <div className="flex justify-between text-red-600"><span>Less cancellation charge ({rfCp}%)</span><span className="tabular-nums">- {fmt(rfCharged)}</span></div>
              <div className="flex justify-between font-semibold border-t border-slate-200 dark:border-zinc-700 pt-1"><span>Refund to customer</span><span className="tabular-nums">{fmt(rfPay)}</span></div>
            </div>
            {rfPay > 0 ? (
              <>
                <fieldset>
                  <legend className="text-sm text-slate-600 dark:text-zinc-300 mb-1">Refund paid by</legend>
                  <div className="flex flex-wrap gap-2">
                    {REFUND_METHODS.map((m) => (
                      <label key={m} className={`cursor-pointer rounded-lg border px-3 py-2 text-sm ${rfMethod === m ? "border-slate-800 dark:border-zinc-200 bg-slate-100 dark:bg-zinc-800 font-medium" : "border-slate-300 dark:border-zinc-700"} text-slate-800 dark:text-zinc-100`}>
                        <input type="radio" name="rfmethod" className="sr-only" checked={rfMethod === m} onChange={() => setRfMethod(m)} />
                        {METHOD_LABEL[m]}
                      </label>
                    ))}
                  </div>
                </fieldset>
                {rfNeedsTxn && <Input label="Transaction / reference id (required)" placeholder="e.g. GPAY99887766" value={rfTxn} onChange={(e) => setRfTxn(e.target.value)} data-testid="refund-txn" />}
              </>
            ) : <p className="text-xs text-slate-500 dark:text-zinc-400">Nothing is paid out: the whole amount is kept as the cancellation charge.</p>}
            <Input label="Note (optional)" value={rfNote} onChange={(e) => setRfNote(e.target.value)} />
            {rfError && <p className="text-sm text-red-600 dark:text-red-400">{rfError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setRfFor(null)}>Cancel</Button>
              <Button onClick={completeRefund} disabled={!rfTxnOk || rfBusy} data-testid="refund-complete">{rfBusy ? "Saving…" : "Mark refund completed"}</Button>
            </div>
          </div>
        </Modal>
      )}

      {payFor && (
        <Modal title="Record payment" onClose={() => setPayFor(null)}>
          <div className="space-y-3">
            <p className="text-sm text-slate-600 dark:text-zinc-300">{payFor.invoice_number}: total {inr(payFor.amount)}, already received {inr(payFor.paid_amount)}, due <b>{inr(payFor.balance)}</b></p>
            <Input label="Amount received now" type="number" min="0.01" step="0.01" max={Number(payFor.balance)} value={payAmount} onChange={(e) => setPayAmount(e.target.value)} data-testid="pay-amount" />
            <fieldset>
              <legend className="text-sm text-slate-600 dark:text-zinc-300 mb-1">Payment mode</legend>
              <div className="flex gap-2">
                {(["cash", "card", "gpay"] as Method[]).map((m) => (
                  <label key={m} className={`flex-1 text-center cursor-pointer rounded-lg border px-3 py-2 text-sm ${method === m ? "border-slate-800 dark:border-zinc-200 bg-slate-100 dark:bg-zinc-800 font-medium" : "border-slate-300 dark:border-zinc-700"} text-slate-800 dark:text-zinc-100`}>
                    <input type="radio" name="method" className="sr-only" checked={method === m} onChange={() => setMethod(m)} />
                    {METHOD_LABEL[m]}
                  </label>
                ))}
              </div>
            </fieldset>
            {needsTxn ? (
              <div>
                <Input label={`${method === "gpay" ? "GPay / UPI" : "Card"} transaction ID (required)`} id="txn" placeholder="e.g. T2610071234" value={txn} onChange={(e) => setTxn(e.target.value)} />
                <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">The payment is only recorded once this is entered.</p>
              </div>
            ) : (
              <p className="text-xs text-slate-500 dark:text-zinc-400">Cash needs no transaction ID.</p>
            )}
            {payError && <p className="text-sm text-red-600 dark:text-red-400">{payError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setPayFor(null)}>Cancel</Button>
              <Button onClick={confirmPayment} disabled={!txnOk || paying}>{paying ? "Recording…" : "Confirm payment received"}</Button>
            </div>
          </div>
        </Modal>
      )}
    </main>
  );
}
