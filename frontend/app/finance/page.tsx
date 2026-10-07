"use client";

import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "@/lib/api";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { SkeletonList } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";

type Account = { id: string; code: string; name: string; account_type: string };
type JournalLine = { account_id: string; debit: string; credit: string };
type JournalEntry = { id: string; entry_number: string | null; date: string; reference: string | null; description: string | null; lines: JournalLine[] };
type Invoice = { id: string; amount: string; status: string };
type Payment = { id: string; invoice_id: string; amount: string; method: string; transaction_id: string | null; date: string };
type Run = { id: string; month: number; year: number; status: string };
type LeaveType = { id: string; code: string; name: string; days_per_year: string | null; per_month: string | null; paid: boolean; note: string | null };
type DeductionRow = {
  employee_id: string; employee_code: string | null; name: string; designation: string | null; salary: string;
  configured: boolean; pf_percent: string; insurance_percent: string; tds_percent: string; lop_days: string | null;
};
type Method = "cash" | "card" | "gpay";

const METHOD_LABEL: Record<string, string> = { cash: "Cash", card: "Card", gpay: "GPay", bank_transfer: "Bank transfer" };
const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN")}`;

export default function FinancePage() {
  const { showToast } = useToast();
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

  const [payFor, setPayFor] = useState<Invoice | null>(null);
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
    setPayFor(inv); setMethod("cash"); setTxn(""); setPayError(null);
  }

  async function confirmPayment() {
    if (!payFor) return;
    setPaying(true); setPayError(null);
    try {
      await apiRequest("/api/finance/payments", {
        method: "POST", auth: true,
        body: { invoice_id: payFor.id, amount: Number(payFor.amount), method, transaction_id: needsTxn ? txn.trim() : null },
      });
      setPayFor(null);
      showToast("Payment recorded", "success");
      loadAll();
    } catch (err) {
      setPayError(err instanceof Error ? err.message : "Failed to record payment");
    }
    setPaying(false);
  }

  const unpaidInvoices = invoices.filter((inv) => inv.status !== "paid");
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
          <div className="grid md:grid-cols-3 gap-6">
            <section>
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-1">Chart of Accounts</h2>
              <p className="text-xs text-slate-500 dark:text-zinc-400 mb-3">
                The fixed list of ledger buckets every entry posts into. It is created for you and extends itself: the first time a feature needs a new account (for example payroll deductions) it appears here.
              </p>
              <Card className="divide-y divide-slate-100 dark:divide-zinc-800">
                {accounts.map((a) => (
                  <div key={a.id} className="p-3 flex justify-between text-sm">
                    <span className="text-slate-800 dark:text-white">{a.code} · {a.name}</span>
                    <span className="text-slate-400 dark:text-zinc-500 text-xs">{a.account_type}</span>
                  </div>
                ))}
              </Card>
            </section>

            <section>
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Unpaid Invoices</h2>
              <div className="space-y-2">
                {unpaidInvoices.map((inv) => (
                  <Card key={inv.id} className="p-3 flex justify-between items-center">
                    <div>
                      <p className="text-sm font-medium text-slate-800 dark:text-white">{inv.amount ? inr(inv.amount) : ""}</p>
                      <p className="text-xs text-slate-500 dark:text-zinc-500">{inv.status}</p>
                    </div>
                    <Button size="sm" onClick={() => openPay(inv)}>Record Payment</Button>
                  </Card>
                ))}
                {unpaidInvoices.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No unpaid invoices.</p>}
              </div>

              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mt-6 mb-3">Payments Received</h2>
              <div className="space-y-2">
                {payments.map((p) => (
                  <Card key={p.id} className="p-3 text-sm" >
                    <div className="flex justify-between"><span className="font-medium text-slate-800 dark:text-white">{inr(p.amount)}</span><span className="text-xs text-slate-500 dark:text-zinc-400">{p.date}</span></div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">{METHOD_LABEL[p.method] || p.method}{p.transaction_id ? ` · Txn ${p.transaction_id}` : ""}</p>
                  </Card>
                ))}
                {payments.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No payments yet.</p>}
              </div>
            </section>

            <section>
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Journal Entries</h2>
              <div className="space-y-2">
                {entries.map((entry) => (
                  <Card key={entry.id} className="p-3">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-sm font-semibold text-slate-800 dark:text-white">{entry.entry_number || "-"}</span>
                      <span className="text-xs text-slate-400 dark:text-zinc-500">{entry.date}</span>
                    </div>
                    <p className="text-sm text-slate-700 dark:text-zinc-200 mb-2">{entry.description}</p>
                    {entry.lines.map((line, i) => (
                      <p key={i} className="text-xs text-slate-500 dark:text-zinc-500 flex justify-between">
                        <span>{accountName(line.account_id)}</span>
                        <span>{Number(line.debit) > 0 ? `Dr ${inr(line.debit)}` : `Cr ${inr(line.credit)}`}</span>
                      </p>
                    ))}
                  </Card>
                ))}
                {entries.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No journal entries yet.</p>}
              </div>
            </section>
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

      {payFor && (
        <Modal title="Record payment" onClose={() => setPayFor(null)}>
          <div className="space-y-3">
            <p className="text-sm text-slate-600 dark:text-zinc-300">Amount received: <b>{inr(payFor.amount)}</b></p>
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
