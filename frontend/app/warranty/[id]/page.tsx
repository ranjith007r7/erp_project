"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiRequest, apiBlob, openBlob } from "@/lib/api";
import { PageHeader, Button, Card } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { useCurrentUser } from "@/components/AppShell";
import { SkeletonList } from "@/components/Skeleton";
import { Modal } from "@/components/Modal";
import { WarrantyDetail, STATE_STYLE, fmtDate } from "@/lib/warranty";

const inr = (v: string | number) => "₹" + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2 });
const field = "w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-500 dark:disabled:bg-zinc-800/60 dark:disabled:text-zinc-400";

function Locked({ label, value, testid }: { label: string; value: string; testid?: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500 dark:text-zinc-400 mb-1">{label}</p>
      <div className="rounded-lg bg-slate-100 dark:bg-zinc-800/60 text-slate-700 dark:text-zinc-300 px-3 py-2 text-sm" data-testid={testid}>{value || "-"}</div>
    </div>
  );
}

type UnitForm = { id: string; model_number: string; serial_number: string; manufacture_month: string; expiry_date: string; prefilled: boolean };

export default function WarrantyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { showToast } = useToast();
  const { can } = useCurrentUser();
  const [d, setD] = useState<WarrantyDetail | null>(null);
  const [months, setMonths] = useState("");
  const [terms, setTerms] = useState("");
  const [units, setUnits] = useState<UnitForm[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dlg, setDlg] = useState<"reject" | "none" | "claim" | null>(null);
  const [reason, setReason] = useState("");
  const [claimUnit, setClaimUnit] = useState("");
  const [issue, setIssue] = useState("");

  const apply = useCallback((x: WarrantyDetail) => {
    setD(x);
    setMonths(x.warranty_months ? String(x.warranty_months) : "");
    setTerms(x.warranty_terms || "");
    setUnits(x.units.map((u) => ({ id: u.id, model_number: u.model_number || "", serial_number: u.serial_number || "",
      manufacture_month: (u.manufacture_month || "").slice(0, 7), expiry_date: u.expiry_date || "", prefilled: u.prefilled_from_stock })));
  }, []);
  const load = useCallback(() => { apiRequest<WarrantyDetail>(`/api/warranty/${id}`, { auth: true }).then(apply).catch((e) => setError(e.message)); }, [id, apply]);
  useEffect(() => { load(); }, [load]);

  const payload = () => ({ warranty_months: months ? Number(months) : null, warranty_terms: terms,
    units: units.map((u) => ({ id: u.id, model_number: u.model_number, serial_number: u.serial_number, manufacture_month: u.manufacture_month || null, expiry_date: u.expiry_date || null })) });

  async function run(path: string, method: string, body: unknown, ok: string) {
    setBusy(true);
    try {
      const x = await apiRequest<WarrantyDetail>(`/api/warranty/${id}${path}`, { method, auth: true, body });
      apply(x); showToast(ok, "success"); setDlg(null); setReason("");
    } catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); }
    setBusy(false);
  }
  async function submit() {
    setBusy(true);
    try {
      await apiRequest(`/api/warranty/${id}`, { method: "PATCH", auth: true, body: payload() });
      apply(await apiRequest<WarrantyDetail>(`/api/warranty/${id}/submit`, { method: "POST", auth: true }));
      showToast("Sent for approval.", "success");
    } catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); }
    setBusy(false);
  }
  async function raiseClaim() {
    setBusy(true);
    try {
      const c = await apiRequest<{ id: string }>("/api/claims", { method: "POST", auth: true, body: { warranty_id: id, unit_id: claimUnit, issue } });
      router.push(`/claims/${c.id}`);
    } catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); setBusy(false); }
  }

  if (error) return <main className="p-8"><p className="text-red-600">{error}</p></main>;
  if (!d) return <main className="p-8"><SkeletonList rows={4} /></main>;
  const editable = d.editable && can("warranty", "edit");

  return (
    <main className="min-h-screen p-4 sm:p-8 max-w-5xl">
      <PageHeader title={`Warranty · ${d.product_name}`} description={`${d.work_number} · ${d.client_name}`} backHref="/warranty" backLabel="← Warranty"
        actions={<span className={`text-xs px-2 py-1 rounded-full font-semibold ${STATE_STYLE[d.state] || ""}`} data-testid="warranty-state">{d.state}</span>} />

      {d.rejection_reason && d.status === "pending_details" && (
        <p className="mb-4 text-sm rounded-lg px-3 py-2 bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300" data-testid="sent-back">Sent back: {d.rejection_reason}</p>
      )}
      {d.status === "pending_approval" && <p className="mb-4 text-sm rounded-lg px-3 py-2 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200">Submitted by {d.submitted_by_name || "an employee"}; waiting for approval. Details are locked until it is decided.</p>}
      {d.status === "no_warranty" && <p className="mb-4 text-sm rounded-lg px-3 py-2 bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300">Sold without warranty: {d.no_warranty_reason}</p>}

      <Card className="p-4 mb-4">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-3">From the work (cannot be edited here)</h2>
        <div className="grid sm:grid-cols-3 gap-3">
          <Locked label="Work" value={d.work_number || ""} testid="f-work" />
          <Locked label="Client" value={d.client_name || ""} />
          <Locked label="Invoice number" value={d.invoice_number || "Not issued yet (generate the tax invoice on the work page)"} testid="f-invoice" />
          <Locked label="Product" value={d.product_name || ""} testid="f-product" />
          <Locked label="Quantity" value={String(d.qty)} />
          <Locked label="Amount (excl. GST)" value={inr(d.amount)} testid="f-amount" />
          <Locked label="Warranty starts (delivery date)" value={fmtDate(d.start_date)} testid="f-start" />
          <Locked label="Warranty ends" value={d.end_date ? fmtDate(d.end_date) : "Set when approved"} />
          {d.card_number && <Locked label="Warranty card no." value={d.card_number} />}
        </div>
        <p className="mt-3 text-xs"><Link className="underline text-indigo-600 dark:text-indigo-400" href={`/workpage/${d.work_id}`}>Open the work page →</Link></p>
      </Card>

      <Card className="p-4 mb-4">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-3">Warranty terms</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block text-sm text-slate-600 dark:text-zinc-300">Warranty period
            <select data-testid="period" className={`${field} mt-1`} disabled={!editable} value={months} onChange={(e) => setMonths(e.target.value)}>
              <option value="">Select the period…</option>
              {d.periods.map((p) => <option key={p.months} value={p.months}>{p.label}</option>)}
            </select>
          </label>
          <label className="block text-sm text-slate-600 dark:text-zinc-300 sm:col-span-2">Terms (optional, printed on the card)
            <textarea className={`${field} mt-1`} rows={2} disabled={!editable} value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="e.g. Manufacturing defects only; excludes physical damage and surge" />
          </label>
        </div>
      </Card>

      <Card className="p-4 mb-4">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-1">Units sold ({d.qty})</h2>
        <p className="text-xs text-slate-500 dark:text-zinc-400 mb-3">Model, manufacture month and expiry are filled from Stock Intake where they exist; type any that are missing. Every unit needs its own serial number.</p>
        <div className="space-y-3" data-testid="units">
          {units.map((u, i) => (
            <div key={u.id} className="grid sm:grid-cols-4 gap-3 border-t border-slate-100 dark:border-zinc-800 pt-3 first:border-0 first:pt-0" data-testid="unit-row">
              <label className="block text-xs text-slate-500 dark:text-zinc-400">Unit {i + 1} · Model number
                <input className={`${field} mt-1`} disabled={!editable} value={u.model_number} onChange={(e) => setUnits(units.map((x) => x.id === u.id ? { ...x, model_number: e.target.value } : x))} aria-label={`Model number ${i + 1}`} />
              </label>
              <label className="block text-xs text-slate-500 dark:text-zinc-400">Serial number
                <input className={`${field} mt-1`} disabled={!editable} value={u.serial_number} onChange={(e) => setUnits(units.map((x) => x.id === u.id ? { ...x, serial_number: e.target.value } : x))} aria-label={`Serial number ${i + 1}`} />
              </label>
              <label className="block text-xs text-slate-500 dark:text-zinc-400">Month of manufacture {u.prefilled && u.manufacture_month ? "· from stock" : ""}
                <input type="month" className={`${field} mt-1`} disabled={!editable} value={u.manufacture_month} onChange={(e) => setUnits(units.map((x) => x.id === u.id ? { ...x, manufacture_month: e.target.value } : x))} aria-label={`Manufacture month ${i + 1}`} />
              </label>
              <label className="block text-xs text-slate-500 dark:text-zinc-400">Expiry date {u.prefilled && u.expiry_date ? "· from stock" : "(if any)"}
                <input type="date" className={`${field} mt-1`} disabled={!editable} value={u.expiry_date} onChange={(e) => setUnits(units.map((x) => x.id === u.id ? { ...x, expiry_date: e.target.value } : x))} aria-label={`Expiry date ${i + 1}`} />
              </label>
            </div>
          ))}
        </div>
      </Card>

      <div className="flex flex-wrap gap-2 mb-6" data-testid="actions">
        {editable && <Button variant="secondary" disabled={busy} onClick={() => run("", "PATCH", payload(), "Saved.")}>Save</Button>}
        {editable && <Button disabled={busy} onClick={submit} data-testid="submit">Save and send for approval</Button>}
        {editable && <Button variant="secondary" disabled={busy} onClick={() => setDlg("none")}>No warranty on this product</Button>}
        {d.status === "pending_approval" && can("warranty", "approve") && <Button disabled={busy} onClick={() => run("/approve", "POST", undefined, "Approved. The warranty card is ready.")} data-testid="approve">Approve</Button>}
        {d.status === "pending_approval" && can("warranty", "approve") && <Button variant="danger" disabled={busy} onClick={() => setDlg("reject")} data-testid="send-back">Send back</Button>}
        {d.status === "active" && (
          <Button data-testid="print-card" onClick={async () => { try { openBlob(await apiBlob(`/api/warranty/${id}/card-pdf`), `${d.card_number}.pdf`); } catch (e) { showToast(e instanceof Error ? e.message : "Could not open the card", "error"); } }}>Print warranty card</Button>
        )}
        {d.status === "active" && can("claims", "create") && <Button variant="secondary" data-testid="raise-claim" onClick={() => { setClaimUnit(d.units[0]?.id || ""); setDlg("claim"); }}>Raise a claim</Button>}
      </div>

      {dlg === "reject" && (
        <Modal title="Send back to the employee" onClose={() => setDlg(null)}>
          <textarea className={field} rows={3} placeholder="What needs correcting?" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="reason" />
          <div className="flex justify-end gap-2 mt-3"><Button variant="secondary" onClick={() => setDlg(null)}>Cancel</Button>
            <Button variant="danger" disabled={busy || reason.trim().length < 2} onClick={() => run("/reject", "POST", { reason }, "Sent back.")}>Send back</Button></div>
        </Modal>
      )}
      {dlg === "none" && (
        <Modal title="No warranty on this product" onClose={() => setDlg(null)}>
          <textarea className={field} rows={3} placeholder="Why does it carry no warranty? (e.g. consumable, sold as is)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="flex justify-end gap-2 mt-3"><Button variant="secondary" onClick={() => setDlg(null)}>Cancel</Button>
            <Button disabled={busy || reason.trim().length < 2} onClick={() => run("/no-warranty", "POST", { reason }, "Marked as no warranty.")}>Confirm</Button></div>
        </Modal>
      )}
      {dlg === "claim" && (
        <Modal title="Raise a warranty claim" onClose={() => setDlg(null)}>
          <div className="space-y-3">
            {d.out_of_warranty && <p className="text-sm rounded-lg px-3 py-2 bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300">This warranty ended on {fmtDate(d.end_date)}. The claim will be flagged OUT OF WARRANTY.</p>}
            <label className="block text-sm text-slate-600 dark:text-zinc-300">Which unit?
              <select className={`${field} mt-1`} value={claimUnit} onChange={(e) => setClaimUnit(e.target.value)} data-testid="claim-unit">
                {d.units.map((u) => <option key={u.id} value={u.id}>Unit {u.position} · {u.serial_number}</option>)}
              </select></label>
            <label className="block text-sm text-slate-600 dark:text-zinc-300">What is the issue?
              <textarea className={`${field} mt-1`} rows={3} value={issue} onChange={(e) => setIssue(e.target.value)} data-testid="claim-issue" /></label>
            <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setDlg(null)}>Cancel</Button>
              <Button disabled={busy || issue.trim().length < 3 || !claimUnit} onClick={raiseClaim} data-testid="claim-create">Create claim</Button></div>
          </div>
        </Modal>
      )}
    </main>
  );
}
