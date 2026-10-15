"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, apiBlob, openBlob } from "@/lib/api";
import { Button, Card, Input, PageHeader } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { usePagination, PaginationControls } from "@/components/Pagination";
import { SkeletonList } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";

type Invoice = { id: string; amount: string; status: string; invoice_number: string | null; paid_amount: string; balance: string; document_ready: boolean; cgst_amount: string; sgst_amount: string; subtotal: string };
type Payment = { id: string; invoice_id: string; amount: string; method: string; transaction_id: string | null; date: string };
type Method = "cash" | "card" | "gpay";
const METHOD_LABEL: Record<string, string> = { cash: "Cash", card: "Card", gpay: "GPay", bank_transfer: "Bank transfer", cheque: "Cheque" };
const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN")}`;
const TABS = [["unpaid", "Unpaid invoices"], ["tax", "Tax invoices"], ["payments", "Payments received"]] as const;

export default function FinanceInvoicesPage() {
  const { showToast } = useToast();
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("unpaid");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [payFor, setPayFor] = useState<Invoice | null>(null);
  const [payAmount, setPayAmount] = useState("");
  const [method, setMethod] = useState<Method>("cash");
  const [txn, setTxn] = useState("");
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiRequest<Invoice[]>("/api/sales/invoices", { auth: true }).then(setInvoices).catch((e) => setError(e.message));
    apiRequest<Payment[]>("/api/finance/payments", { auth: true }).then(setPayments).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const needsTxn = method !== "cash";
  const txnOk = !needsTxn || /^[A-Za-z0-9._\-/]{4,64}$/.test(txn.trim());
  function openPay(inv: Invoice) { setPayFor(inv); setPayAmount(String(Number(inv.balance))); setMethod("cash"); setTxn(""); setPayError(null); }
  async function confirmPayment() {
    if (!payFor) return;
    setPaying(true); setPayError(null);
    try {
      await apiRequest("/api/finance/payments", { method: "POST", auth: true, body: { invoice_id: payFor.id, amount: Number(payAmount), method, transaction_id: needsTxn ? txn.trim() : null } });
      setPayFor(null); showToast("Payment recorded", "success"); load();
    } catch (err) { setPayError(err instanceof Error ? err.message : "Failed to record payment"); }
    setPaying(false);
  }
  async function openTaxInvoice(inv: Invoice) {
    try { openBlob(await apiBlob(`/api/sales/invoices/${inv.id}/pdf`), `${inv.invoice_number || "invoice"}.pdf`); }
    catch (err) { showToast(err instanceof Error ? err.message : "Could not open the invoice", "error"); }
  }

  const numberOf = useMemo(() => Object.fromEntries((invoices ?? []).map((i) => [i.id, i.invoice_number])), [invoices]);
  const match = (s: string) => !q.trim() || s.toLowerCase().includes(q.trim().toLowerCase());
  const unpaid = useMemo(() => (invoices ?? []).filter((i) => i.status !== "paid" && i.status !== "cancelled" && match(`${i.invoice_number} ${i.amount}`)), [invoices, q]);
  const tax = useMemo(() => (invoices ?? []).filter((i) => i.document_ready && match(`${i.invoice_number} ${i.amount}`)), [invoices, q]);
  const pays = useMemo(() => payments.filter((p) => match(`${numberOf[p.invoice_id] ?? ""} ${p.amount} ${p.method} ${p.transaction_id ?? ""}`)), [payments, q, numberOf]);
  const list = tab === "unpaid" ? unpaid : tab === "tax" ? tax : pays;
  const { pageItems, page, totalPages, setPage } = usePagination<Invoice | Payment>(list as (Invoice | Payment)[], 15);

  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Invoices and payments" backHref="/finance" backLabel="← Finance" description="Record payments against unpaid invoices, download tax invoices (issued once a payment is recorded) and see every payment received." />
      <div className="flex flex-wrap gap-2 mb-3" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} data-testid={`tab-${k}`} onClick={() => { setTab(k); setPage(1); }}
            className={`px-3 py-1.5 rounded-lg text-sm border ${tab === k ? "border-slate-800 dark:border-zinc-200 bg-slate-100 dark:bg-zinc-800 font-medium" : "border-slate-300 dark:border-zinc-700"} text-slate-800 dark:text-zinc-100`}>
            {label} <span className="text-xs text-slate-500">({k === "unpaid" ? unpaid.length : k === "tax" ? tax.length : pays.length})</span>
          </button>
        ))}
      </div>
      <input placeholder="Search invoice number, amount or reference" className="mb-4 border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm w-full max-w-sm" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!invoices ? <SkeletonList rows={4} /> : (
        <>
          <div className="space-y-2" data-testid="invoice-list">
            {tab === "unpaid" && (pageItems as Invoice[]).map((inv) => (
              <Card key={inv.id} className="p-3 flex justify-between items-center gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-white">{inv.invoice_number} · {inr(inv.amount)}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">{inv.status} · taxable {inr(inv.subtotal)} + CGST {inr(inv.cgst_amount)} + SGST {inr(inv.sgst_amount)}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">received {inr(inv.paid_amount)} · due {inr(inv.balance)}</p>
                </div>
                <Button size="sm" onClick={() => openPay(inv)}>Record Payment</Button>
              </Card>
            ))}
            {tab === "tax" && (pageItems as Invoice[]).map((inv) => (
              <Card key={inv.id} className="p-3 flex justify-between items-center gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-white">{inv.invoice_number} · {inr(inv.amount)}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">{inv.status === "cancelled" ? "cancelled (credit note)" : Number(inv.balance) > 0 ? `part paid, ${inr(inv.balance)} due` : "paid"}</p>
                </div>
                <Button size="sm" variant="secondary" onClick={() => openTaxInvoice(inv)} data-testid="open-tax-invoice">Download PDF</Button>
              </Card>
            ))}
            {tab === "payments" && (pageItems as Payment[]).map((p) => (
              <Card key={p.id} className="p-3 text-sm">
                <div className="flex justify-between"><span className="font-medium text-slate-800 dark:text-white">{inr(p.amount)} <span className="text-xs text-slate-500">· {numberOf[p.invoice_id] ?? "invoice"}</span></span><span className="text-xs text-slate-500 dark:text-zinc-400">{p.date}</span></div>
                <p className="text-xs text-slate-500 dark:text-zinc-400">{METHOD_LABEL[p.method] || p.method}{p.transaction_id ? ` · Txn ${p.transaction_id}` : ""}</p>
              </Card>
            ))}
            {list.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">{tab === "unpaid" ? "No unpaid invoices." : tab === "tax" ? "None yet." : "No payments yet."}</p>}
          </div>
          <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />
        </>
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
