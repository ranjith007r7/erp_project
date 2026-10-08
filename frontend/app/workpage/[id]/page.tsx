"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Check, ArrowLeft } from "lucide-react";
import { apiRequest, getToken } from "@/lib/api";
import { Button, Input, Select, Card } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { StatusPill } from "@/components/StatusPill";
import { useToast } from "@/components/Toast";
import { useCurrentUser } from "@/components/AppShell";
import { formatDateTime } from "@/lib/time";
import { WorkDetail, WorkMeta, inr, METHOD_LABEL } from "@/lib/workpage";

const STEPS = [
  ["assigned", "Assigned"], ["allocated", "Allocated"], ["po_raised", "PO raised"],
  ["po_received", "PO received"], ["delivered", "Delivered"], ["closed", "Closed"],
] as const;

type Dialog = null | "allocate" | "deliver" | "payment" | "edit";

export default function WorkDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { showToast } = useToast();
  const { can } = useCurrentUser();
  const [w, setW] = useState<WorkDetail | null>(null);
  const [meta, setMeta] = useState<WorkMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => apiRequest<WorkDetail>(`/api/workpage/works/${id}`, { auth: true }).then((d) => { setW(d); setError(null); }).catch((e) => setError(e.message)), [id]);
  useEffect(() => { if (!getToken()) { router.push("/login"); return; } load(); }, [load, router]);
  useEffect(() => { apiRequest<WorkMeta>("/api/workpage/meta", { auth: true }).then(setMeta).catch(() => {}); }, []);
  // the work moves while people elsewhere raise / receive POs: keep the page fresh
  useEffect(() => { const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);

  async function act(path: string, body?: unknown, ok = "Saved.") {
    setBusy(true);
    try {
      const d = await apiRequest<WorkDetail>(`/api/workpage/works/${id}${path}`, { method: "POST", auth: true, body: body ?? {} });
      setW(d); setDialog(null); showToast(ok, "success");
    } catch (e) { showToast(e instanceof Error ? e.message : "Something went wrong", "error"); }
    finally { setBusy(false); }
  }

  if (error && !w) return <main className="p-8"><p className="text-red-600" role="alert">{error}</p><Link href="/workpage" className="underline text-sm">Back to Workpage</Link></main>;
  if (!w) return <main className="p-8"><div className="h-8 w-48 bg-slate-200 dark:bg-zinc-800 rounded animate-pulse" /></main>;

  const stepIndex = Math.max(0, STEPS.findIndex(([k]) => k === (w.status === "waiting_new_po" ? "po_raised" : w.status)));
  const waiting = w.status === "waiting_new_po";
  const closed = w.status === "closed";
  const canEdit = can("workpage", "edit") && !closed;
  const events = [...w.events].reverse();

  return (
    <main className="p-4 sm:p-8 max-w-6xl">
      <Link href="/workpage" className="inline-flex items-center gap-1 text-sm text-slate-500 dark:text-zinc-400 hover:underline mb-3"><ArrowLeft size={14} /> Workpage</Link>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 dark:text-white" data-testid="work-title">{w.client_name}</h1>
          <p className="text-sm text-slate-500 dark:text-zinc-400">{w.work_number}{w.domain ? ` · ${w.domain}` : ""} · received {formatDateTime(w.created_at)}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span data-testid="work-status"><StatusPill label={w.status_label} color={w.status_color} /></span>
          {canEdit && <Button size="sm" variant="secondary" onClick={() => setDialog("edit")}>Edit amounts</Button>}
        </div>
      </div>

      {/* Amazon-style tracker */}
      <Card className="p-5 mb-4">
        <ol className="flex items-start" aria-label="Progress" data-testid="tracker">
          {STEPS.map(([k, label], i) => {
            const done = i < stepIndex || (closed && i <= stepIndex);
            const current = i === stepIndex && !closed;
            return (
              <li key={k} className="flex-1 flex flex-col items-center text-center relative">
                {i > 0 && <span className={`absolute top-3.5 right-1/2 w-full h-0.5 ${i <= stepIndex ? "bg-green-500" : "bg-slate-200 dark:bg-zinc-700"}`} aria-hidden />}
                <span className={`relative z-10 h-7 w-7 rounded-full grid place-items-center text-xs font-semibold ${done ? "bg-green-500 text-white" : current ? (waiting ? "bg-red-500 text-white" : "bg-indigo-600 text-white") : "bg-slate-200 dark:bg-zinc-700 text-slate-500 dark:text-zinc-400"}`}>
                  {done ? <Check size={14} /> : i + 1}
                </span>
                <span className={`mt-1.5 text-xs ${current ? "font-semibold text-slate-800 dark:text-white" : "text-slate-500 dark:text-zinc-400"}`}>{label}</span>
              </li>
            );
          })}
        </ol>
        {waiting && <p className="mt-4 text-sm rounded-lg bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300 px-3 py-2" role="status">The goods arrived defective. This work is waiting for a replacement purchase order — raise it in Procurement for this work.</p>}
      </Card>

      {/* money */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-4" data-testid="money">
        <Money label="Quotation" value={w.quotation_amount} />
        <Money label={`Client discount (${Number(w.discount_percent)}%)`} value={w.discount_amount} />
        <Money label="Net payable" value={w.net_payable} />
        <Money label="Vendor amount" value={w.vendor_amount} />
        <Money label="Profit" value={w.profit} tone={Number(w.profit) < 0 ? "bad" : "good"} />
        <Money label="Received" value={w.received_amount} />
        <Money label="Pending" value={w.pending_amount} tone={Number(w.pending_amount) > 0 ? "warn" : "good"} />
      </div>

      {/* actions */}
      {canEdit && (
        <div className="flex flex-wrap gap-2 mb-4" data-testid="actions">
          <Button variant="secondary" onClick={() => setDialog("allocate")}>{w.handling_department ? "Re-allocate" : "Allocate"}</Button>
          {!["delivered", "closed"].includes(w.status) && <Button variant="secondary" onClick={() => setDialog("deliver")}>Mark delivered</Button>}
          {Number(w.pending_amount) > 0 && <Button variant="secondary" onClick={() => setDialog("payment")}>Record payment</Button>}
          {w.status === "delivered" && can("workpage", "approve") && (
            <Button onClick={() => act("/close", {}, "Work closed.")} disabled={!w.can_close || busy} title={w.can_close ? "" : "Close is allowed only after the full payment is recorded"}>Close work</Button>
          )}
          {w.status === "delivered" && !w.can_close && <span className="self-center text-xs text-slate-500 dark:text-zinc-400">Closing needs the full payment ({inr(w.pending_amount)} pending).</span>}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-4">
          {/* handling */}
          <Card className="p-5" data-testid="handling">
            <h2 className="font-semibold text-slate-800 dark:text-white mb-3">Handling departments</h2>
            <ol className="space-y-3 text-sm">
              <li><span className="text-xs text-slate-500 dark:text-zinc-400 block">Assigned department</span><span className="text-slate-800 dark:text-white">{w.handling_department || "Not assigned yet"}</span></li>
              <li><span className="text-xs text-slate-500 dark:text-zinc-400 block">Allocated employee</span>
                <span className="text-slate-800 dark:text-white">{w.allocated_employee ? `${w.allocated_employee.name} (${w.allocated_employee.employee_code || "no code"})` : "Not allocated to a person yet"}</span></li>
              <li><span className="text-xs text-slate-500 dark:text-zinc-400 block">Purchase order assigned to</span>
                <span className="text-slate-800 dark:text-white">{w.purchase_orders.length ? [...new Set(w.purchase_orders.map((p) => p.assigned_to).filter(Boolean))].join(", ") || "—" : "No purchase order raised yet"}</span></li>
            </ol>
          </Card>

          {/* client + quotation */}
          <Card className="p-5">
            <h2 className="font-semibold text-slate-800 dark:text-white mb-3">Client and quotation</h2>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              <div><dt className="text-xs text-slate-500 dark:text-zinc-400">Client</dt><dd className="text-slate-800 dark:text-white">{w.client_name}</dd></div>
              <div><dt className="text-xs text-slate-500 dark:text-zinc-400">Domain</dt><dd className="text-slate-800 dark:text-white">{w.domain || "—"}</dd></div>
              <div className="sm:col-span-2"><dt className="text-xs text-slate-500 dark:text-zinc-400">Client details</dt><dd className="text-slate-800 dark:text-white whitespace-pre-line">{w.client_details || "—"}</dd></div>
              <div><dt className="text-xs text-slate-500 dark:text-zinc-400">Quoted amount</dt><dd className="text-slate-800 dark:text-white">{inr(w.quotation_amount)}</dd></div>
              <div><dt className="text-xs text-slate-500 dark:text-zinc-400">Quotation</dt><dd className="text-slate-800 dark:text-white">{w.quotation ? <Link href="/sales" className="underline">Open in Sales ({w.quotation.status})</Link> : "Entered directly"}</dd></div>
            </dl>
          </Card>

          {/* POs */}
          <Card className="p-5" data-testid="po-card">
            <h2 className="font-semibold text-slate-800 dark:text-white mb-3">Purchase orders</h2>
            {w.purchase_orders.length === 0 ? <p className="text-sm text-slate-500 dark:text-zinc-400">None yet. When the warehouse raises a PO for this work it is tracked here automatically.</p> : (
              <ul className="space-y-4">
                {w.purchase_orders.map((p) => (
                  <li key={p.id} className="text-sm border border-slate-200 dark:border-zinc-800 rounded-lg p-3">
                    <div className="flex flex-wrap justify-between gap-2">
                      <span className="font-medium text-slate-800 dark:text-white">{p.po_number} · {p.vendor_name}</span>
                      <span className="text-slate-600 dark:text-zinc-300">{inr(p.total)}</span>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">
                      Ordered {formatDateTime(p.created_at)} · raised by {p.assigned_to || "—"} · {p.approval_status === "approved" ? `approved by ${p.approved_by}` : p.approval_status} · {p.status === "pending" ? "in transit / awaiting delivery" : p.status}
                    </p>
                    {p.receipts.map((r, i) => (
                      <p key={i} className={`text-xs mt-1 ${r.condition === "bad" ? "text-red-700 dark:text-red-400" : "text-green-700 dark:text-green-400"}`}>
                        {r.condition === "bad" ? "Received DEFECTIVE" : "Received in good condition"} on {r.received_date}{r.received_by ? ` by ${r.received_by}` : ""}{r.notes ? ` — ${r.notes}` : ""}
                      </p>
                    ))}
                    {p.notices.map((n, i) => (
                      <p key={i} className="text-xs mt-1 text-slate-500 dark:text-zinc-400">
                        {n.kind === "po" ? "PO sent to vendor" : "Defect notice (send-back)"} — {n.channel === "print" ? "printed" : `emailed${n.to_email ? ` to ${n.to_email}` : ""}`} ({n.status}) {formatDateTime(n.created_at)}
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* payments */}
          <Card className="p-5" data-testid="payments-card">
            <div className="flex justify-between items-center mb-3"><h2 className="font-semibold text-slate-800 dark:text-white">Payments received</h2>
              <span className="text-xs text-slate-500 dark:text-zinc-400">{inr(w.received_amount)} of {inr(w.net_payable)} · {inr(w.pending_amount)} pending</span></div>
            {w.payments.length === 0 ? <p className="text-sm text-slate-500 dark:text-zinc-400">No payment recorded yet.</p> : (
              <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-400"><th className="pb-2 font-medium">Date</th><th className="pb-2 font-medium">Means</th><th className="pb-2 font-medium">Reference</th><th className="pb-2 font-medium text-right">Amount</th></tr></thead>
                <tbody>{w.payments.map((p) => (
                  <tr key={p.id} className="border-t border-slate-100 dark:border-zinc-800"><td className="py-2">{p.paid_on}</td><td>{METHOD_LABEL[p.method] ?? p.method}</td><td className="text-slate-500 dark:text-zinc-400">{p.transaction_id || p.note || "—"}</td><td className="text-right tabular-nums">{inr(p.amount)}</td></tr>
                ))}</tbody></table>
            )}
          </Card>
        </div>

        {/* timeline */}
        <Card className="p-5 h-fit" data-testid="timeline">
          <h2 className="font-semibold text-slate-800 dark:text-white mb-4">History</h2>
          <ol className="relative border-l border-slate-200 dark:border-zinc-700 ml-2 space-y-5">
            {events.map((e) => (
              <li key={e.id} className="ml-4">
                <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-indigo-500" aria-hidden />
                <p className="text-sm font-medium text-slate-800 dark:text-white">{e.title}</p>
                {e.detail && <p className="text-xs text-slate-600 dark:text-zinc-300 mt-0.5">{e.detail}</p>}
                <p className="text-xs text-slate-400 dark:text-zinc-500 mt-0.5">{formatDateTime(e.created_at)}{e.actor_name ? ` · ${e.actor_name}` : ""}</p>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      {dialog === "allocate" && meta && <AllocateDialog w={w} meta={meta} busy={busy} onClose={() => setDialog(null)} onSubmit={(b) => act("/allocate", b, "Allocated.")} />}
      {dialog === "deliver" && <DeliverDialog w={w} busy={busy} onClose={() => setDialog(null)} onSubmit={(b) => act("/deliver", b, "Marked as delivered.")} />}
      {dialog === "payment" && meta && <PaymentDialog w={w} meta={meta} busy={busy} onClose={() => setDialog(null)} onSubmit={(b) => act("/payments", b, "Payment recorded.")} />}
      {dialog === "edit" && <EditDialog w={w} onClose={() => setDialog(null)} onSaved={(d) => { setW(d); setDialog(null); showToast("Saved.", "success"); }} />}
    </main>
  );
}

function Money({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" | "warn" }) {
  const c = tone === "bad" ? "text-red-600 dark:text-red-400" : tone === "warn" ? "text-amber-700 dark:text-amber-400" : tone === "good" ? "text-green-700 dark:text-green-400" : "text-slate-800 dark:text-white";
  return <Card className="p-3"><div className="text-xs text-slate-500 dark:text-zinc-400">{label}</div><div className={`text-base font-semibold tabular-nums ${c}`}>{inr(value)}</div></Card>;
}

function Actions({ onClose, busy, label }: { onClose: () => void; busy: boolean; label: string }) {
  return <div className="flex justify-end gap-2 pt-1"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" disabled={busy}>{label}</Button></div>;
}

function AllocateDialog({ w, meta, busy, onClose, onSubmit }: { w: WorkDetail; meta: WorkMeta; busy: boolean; onClose: () => void; onSubmit: (b: unknown) => void }) {
  const [dept, setDept] = useState(w.handling_department_id ?? "");
  const [emp, setEmp] = useState(w.allocated_employee?.id ?? "");
  const people = meta.employees.filter((e) => e.department_id === dept);
  return (
    <Modal title="Allocate work" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); onSubmit({ department_id: dept, employee_id: emp || null }); }} className="space-y-3">
        <Select label="Department" required value={dept} onChange={(e) => { setDept(e.target.value); setEmp(""); }}>
          <option value="">Select department…</option>{meta.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </Select>
        <Select label="Employee (optional)" value={emp} onChange={(e) => setEmp(e.target.value)} disabled={!dept}>
          <option value="">Not picked yet</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.employee_code || "no code"})</option>)}
        </Select>
        <p className="text-xs text-slate-500 dark:text-zinc-400">Picking an employee moves the work to Allocated.</p>
        <Actions onClose={onClose} busy={busy} label="Allocate" />
      </form>
    </Modal>
  );
}

function DeliverDialog({ w, busy, onClose, onSubmit }: { w: WorkDetail; busy: boolean; onClose: () => void; onSubmit: (b: unknown) => void }) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const [fromStock, setFromStock] = useState(false);
  return (
    <Modal title="Mark as delivered" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); onSubmit({ delivered_on: date, note: note || null, from_stock: fromStock }); }} className="space-y-3">
        <Input label="Delivery date" type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
        <Input label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Courier, receiver name…" />
        {w.status === "allocated" && (
          <label className="flex items-start gap-2 text-sm text-slate-600 dark:text-zinc-300"><input type="checkbox" className="mt-1" checked={fromStock} onChange={(e) => setFromStock(e.target.checked)} /> Deliver from existing stock (no purchase order needed)</label>
        )}
        <Actions onClose={onClose} busy={busy} label="Mark delivered" />
      </form>
    </Modal>
  );
}

function PaymentDialog({ w, meta, busy, onClose, onSubmit }: { w: WorkDetail; meta: WorkMeta; busy: boolean; onClose: () => void; onSubmit: (b: unknown) => void }) {
  const [amount, setAmount] = useState(String(Number(w.pending_amount)));
  const [method, setMethod] = useState("cash");
  const [ref, setRef] = useState("");
  const [note, setNote] = useState("");
  return (
    <Modal title="Record payment" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); onSubmit({ amount: Number(amount), method, transaction_id: method === "cash" ? null : ref, note: note || null }); }} className="space-y-3">
        <p className="text-sm text-slate-600 dark:text-zinc-300">Pending now: <b>{inr(w.pending_amount)}</b>. Enter less for a part payment.</p>
        <Input label="Amount received" type="number" required min="0.01" step="0.01" max={Number(w.pending_amount)} value={amount} onChange={(e) => setAmount(e.target.value)} />
        <Select label="Paid by" value={method} onChange={(e) => setMethod(e.target.value)}>{meta.payment_methods.map((m) => <option key={m} value={m}>{METHOD_LABEL[m] ?? m}</option>)}</Select>
        {method !== "cash" && <Input label={method === "cheque" ? "Cheque number" : "Transaction / reference ID"} required value={ref} onChange={(e) => setRef(e.target.value)} />}
        <Input label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        <Actions onClose={onClose} busy={busy} label="Record payment" />
      </form>
    </Modal>
  );
}

function EditDialog({ w, onClose, onSaved }: { w: WorkDetail; onClose: () => void; onSaved: (d: WorkDetail) => void }) {
  const { showToast } = useToast();
  const [f, setF] = useState({ client_name: w.client_name, domain: w.domain ?? "", client_details: w.client_details ?? "", quotation_amount: String(Number(w.quotation_amount)), vendor_amount: String(Number(w.vendor_amount)), discount_percent: String(Number(w.discount_percent)) });
  const [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try {
      const d = await apiRequest<WorkDetail>(`/api/workpage/works/${w.id}`, { method: "PATCH", auth: true, body: {
        client_name: f.client_name, domain: f.domain, client_details: f.client_details,
        quotation_amount: Number(f.quotation_amount), vendor_amount: Number(f.vendor_amount), discount_percent: Number(f.discount_percent) } });
      onSaved(d);
    } catch (err) { showToast(err instanceof Error ? err.message : "Could not save", "error"); } finally { setBusy(false); }
  }
  return (
    <Modal title="Edit work" onClose={onClose} wide>
      <form onSubmit={save} className="space-y-3">
        <Input label="Client name" required value={f.client_name} onChange={(e) => setF({ ...f, client_name: e.target.value })} />
        <Input label="Domain" value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value })} />
        <div className="grid grid-cols-3 gap-3">
          <Input label="Quotation amount" type="number" min="0" step="0.01" value={f.quotation_amount} onChange={(e) => setF({ ...f, quotation_amount: e.target.value })} />
          <Input label="Vendor amount" type="number" min="0" step="0.01" value={f.vendor_amount} onChange={(e) => setF({ ...f, vendor_amount: e.target.value })} />
          <Input label="Client discount %" type="number" min="0" max="100" step="0.01" value={f.discount_percent} onChange={(e) => setF({ ...f, discount_percent: e.target.value })} />
        </div>
        <label className="block text-sm text-slate-600 dark:text-zinc-300">Client details
          <textarea className="mt-1 w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm" rows={3} value={f.client_details} onChange={(e) => setF({ ...f, client_details: e.target.value })} />
        </label>
        <Actions onClose={onClose} busy={busy} label="Save" />
      </form>
    </Modal>
  );
}
