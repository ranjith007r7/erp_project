"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Plus } from "lucide-react";
import { apiRequest, apiUpload, getToken } from "@/lib/api";
import { PageHeader, Button, Input, Select, Card } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { StatusPill, STATUS_DOT } from "@/components/StatusPill";
import { useToast } from "@/components/Toast";
import { useCurrentUser } from "@/components/AppShell";
import { SkeletonList } from "@/components/Skeleton";
import { WorkRow, WorkMeta, inr } from "@/lib/workpage";
import { tenDigits } from "@/lib/format";

type ListResp = { counts: Record<string, number>; total: number; works: WorkRow[] };

export default function WorkpagePage() {
  const router = useRouter();
  const { showToast } = useToast();
  const { can } = useCurrentUser();
  const [data, setData] = useState<ListResp | null>(null);
  const [meta, setMeta] = useState<WorkMeta | null>(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ client_name: "", client_mobile: "", domain: "", client_details: "", quotation_amount: "", vendor_amount: "", discount_percent: "0", department_id: "" });

  const load = useCallback(() => {
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (q.trim()) qs.set("q", q.trim());
    return apiRequest<ListResp>(`/api/workpage/works?${qs}`, { auth: true }).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  }, [status, q]);

  useEffect(() => { if (!getToken()) router.push("/login"); }, [router]);
  useEffect(() => { apiRequest<WorkMeta>("/api/workpage/meta", { auth: true }).then(setMeta).catch(() => {}); }, []);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      const w = await apiRequest<{ id: string }>("/api/workpage/works", {
        method: "POST", auth: true,
        body: {
          client_name: form.client_name, client_mobile: form.client_mobile || null, domain: form.domain || null, client_details: form.client_details || null,
          quotation_amount: Number(form.quotation_amount || 0), vendor_amount: Number(form.vendor_amount || 0),
          discount_percent: Number(form.discount_percent || 0), department_id: form.department_id || null,
        },
      });
      showToast("Work created.", "success");
      setCreating(false);
      router.push(`/workpage/${w.id}`);
    } catch (err) { showToast(err instanceof Error ? err.message : "Could not create the work", "error"); }
  }

  async function importAccepted() {
    try {
      const r = await apiRequest<{ created: number }>("/api/workpage/import-accepted", { method: "POST", auth: true });
      showToast(r.created ? `${r.created} accepted quotation(s) imported as works.` : "Nothing to import - every accepted quotation already has a work.", "success");
      load();
    } catch (err) { showToast(err instanceof Error ? err.message : "Import failed", "error"); }
  }

  async function importCsv(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await apiUpload<{ imported: number; failed: number; errors: { row: number; reason: string }[] }>("/api/workpage/works/import", fd);
      showToast(r.failed ? `Imported ${r.imported}; ${r.failed} row(s) failed (first: row ${r.errors[0].row}, ${r.errors[0].reason}).` : `Imported ${r.imported} work(s) as Assigned.`, r.failed ? "info" : "success");
      load();
    } catch (err) { showToast(err instanceof Error ? err.message : "Import failed", "error"); }
  }

  return (
    <main className="p-4 sm:p-8">
      <PageHeader title="Workpage" description="Every customer work, its status, money and who is handling it. A work opens by itself when a quotation is converted in CRM; statuses then move by themselves as the team, Procurement and Inventory do their part. Manual and bulk entry is for quotations received outside CRM."
        actions={can("workpage", "create") ? (
          <div className="flex gap-2 flex-wrap">
            <label className="inline-flex items-center px-3 py-2 rounded-lg text-sm border border-slate-300 dark:border-zinc-700 text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-800 cursor-pointer" title="Columns: client_name, client_mobile, domain, quotation_amount, description">
              Bulk import CSV<input type="file" accept=".csv" className="hidden" onChange={importCsv} data-testid="bulk-import" />
            </label>
            <Button variant="secondary" onClick={importAccepted} data-testid="import-accepted">Import from Sales</Button>
            <Button onClick={() => setCreating(true)} data-testid="new-work"><span className="flex items-center gap-1.5"><Plus size={15} /> Add work manually</span></Button>
          </div>) : undefined} />

      {error && <p className="text-red-600 mb-3" role="alert">{error}</p>}

      <div className="flex flex-wrap gap-2 mb-4" data-testid="status-filters">
        <button onClick={() => setStatus("")} className={`px-3 py-1 rounded-full text-sm border ${status === "" ? "bg-slate-800 text-white dark:bg-zinc-100 dark:text-zinc-950 border-transparent" : "border-slate-300 dark:border-zinc-700 text-slate-600 dark:text-zinc-300"}`}>All {data ? `(${data.total})` : ""}</button>
        {(meta?.statuses ?? []).map((s) => (
          <button key={s.key} onClick={() => setStatus(s.key)} className={`px-3 py-1 rounded-full text-sm border flex items-center gap-1.5 ${status === s.key ? "bg-slate-800 text-white dark:bg-zinc-100 dark:text-zinc-950 border-transparent" : "border-slate-300 dark:border-zinc-700 text-slate-600 dark:text-zinc-300"}`}>
            <span className={`h-2 w-2 rounded-full ${STATUS_DOT[s.color]}`} />{s.label} {data ? `(${data.counts[s.key] ?? 0})` : ""}
          </button>
        ))}
        <div className="ml-auto w-full sm:w-64"><Input placeholder="Search client, domain or number…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search works" /></div>
      </div>

      {!data ? <SkeletonList rows={5} /> : data.works.length === 0 ? (
        <Card className="p-8 text-center text-slate-500 dark:text-zinc-400">No works {status || q ? "match this filter" : "yet"}. {can("workpage", "create") && !status && !q ? "Convert a quotation in CRM and it appears here as Assigned." : ""}</Card>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="work-table">
            <thead>
              <tr className="text-left text-xs text-slate-500 dark:text-zinc-400 border-b border-slate-200 dark:border-zinc-800">
                <th className="p-3 font-medium">Client name</th><th className="p-3 font-medium">Domain</th><th className="p-3 font-medium">Status</th>
                <th className="p-3 font-medium text-right">Quotation amount</th><th className="p-3 font-medium text-right">Vendor amount</th>
                <th className="p-3 font-medium text-right">Client discount</th><th className="p-3 font-medium text-right">Profit</th><th className="p-3 font-medium">Who is handling</th>
              </tr>
            </thead>
            <tbody>
              {data.works.map((w) => (
                <tr key={w.id} className="border-b last:border-0 border-slate-100 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/50">
                  <td className="p-3"><Link href={`/workpage/${w.id}`} className="font-medium text-slate-800 dark:text-white hover:underline">{w.client_name}</Link><div className="text-xs text-slate-400 dark:text-zinc-500">{w.work_number}{w.client_mobile ? ` · ${w.client_mobile}` : ""}</div></td>
                  <td className="p-3 text-slate-600 dark:text-zinc-300">{w.domain || "—"}</td>
                  <td className="p-3 max-w-xs"><StatusPill label={w.status_label} color={w.status_color} /><div className="text-xs text-slate-500 dark:text-zinc-400 mt-1 whitespace-normal" data-testid="work-reason">{w.pending_reason}</div></td>
                  <td className="p-3 text-right tabular-nums text-slate-800 dark:text-white">{inr(w.quotation_amount)}</td>
                  <td className="p-3 text-right tabular-nums text-slate-600 dark:text-zinc-300">{inr(w.vendor_amount)}</td>
                  <td className="p-3 text-right tabular-nums text-slate-600 dark:text-zinc-300">{Number(w.discount_percent)}%</td>
                  <td className={`p-3 text-right tabular-nums font-medium ${Number(w.profit) < 0 ? "text-red-600 dark:text-red-400" : "text-green-700 dark:text-green-400"}`}>{inr(w.profit)}</td>
                  <td className="p-3 text-slate-600 dark:text-zinc-300">{w.handling_department || <span className="text-slate-400">Not assigned</span>}{w.allocated_employee_name && <div className="text-xs text-slate-500 dark:text-zinc-400">{w.allocated_employee_name}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <p className="text-xs text-slate-500 dark:text-zinc-500 mt-3">Profit = quotation amount − client discount − vendor amount.</p>

      {creating && (
        <Modal title="Add work manually" onClose={() => setCreating(false)} wide>
          <form onSubmit={create} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Input label="Client name" required value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />
              <Input label="Client mobile number (10 digits)" type="tel" inputMode="numeric" pattern="[0-9]{10}" value={form.client_mobile} onChange={(e) => setForm({ ...form, client_mobile: tenDigits(e.target.value) })} />
            </div>
            <Input label="Domain (the client's industry)" value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} placeholder="e.g. Manufacturing, Retail, Education" />
            <div className="grid grid-cols-3 gap-3">
              <Input label="Quotation amount" type="number" min="0" step="0.01" value={form.quotation_amount} onChange={(e) => setForm({ ...form, quotation_amount: e.target.value })} />
              <Input label="Vendor amount" type="number" min="0" step="0.01" value={form.vendor_amount} onChange={(e) => setForm({ ...form, vendor_amount: e.target.value })} />
              <Input label="Client discount %" type="number" min="0" max="100" step="0.01" value={form.discount_percent} onChange={(e) => setForm({ ...form, discount_percent: e.target.value })} />
            </div>
            <Select label="Assign to department" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })}>
              <option value="">Choose later</option>
              {(meta?.departments ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
            <label className="block text-sm text-slate-600 dark:text-zinc-300">Client details
              <textarea className="mt-1 w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm" rows={3} value={form.client_details} onChange={(e) => setForm({ ...form, client_details: e.target.value })} placeholder="Contact person, phone, address" />
            </label>
            <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setCreating(false)}>Cancel</Button><Button type="submit">Create work</Button></div>
          </form>
        </Modal>
      )}
    </main>
  );
}
