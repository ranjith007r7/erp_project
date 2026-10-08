"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Plus } from "lucide-react";
import { apiRequest, getToken } from "@/lib/api";
import { PageHeader, Button, Input, Select, Card } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { StatusPill, STATUS_DOT } from "@/components/StatusPill";
import { useToast } from "@/components/Toast";
import { useCurrentUser } from "@/components/AppShell";
import { SkeletonList } from "@/components/Skeleton";
import { WorkRow, WorkMeta, inr } from "@/lib/workpage";

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
  const [form, setForm] = useState({ client_name: "", domain: "", client_details: "", quotation_amount: "", vendor_amount: "", discount_percent: "0", department_id: "" });

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
          client_name: form.client_name, domain: form.domain || null, client_details: form.client_details || null,
          quotation_amount: Number(form.quotation_amount || 0), vendor_amount: Number(form.vendor_amount || 0),
          discount_percent: Number(form.discount_percent || 0), department_id: form.department_id || null,
        },
      });
      showToast("Work created.", "success");
      setCreating(false);
      router.push(`/workpage/${w.id}`);
    } catch (err) { showToast(err instanceof Error ? err.message : "Could not create the work", "error"); }
  }

  return (
    <main className="p-4 sm:p-8">
      <PageHeader title="Workpage" description="Every customer work, its status, money and who is handling it. Statuses move by themselves as Sales, Procurement and Inventory do their part."
        actions={can("workpage", "create") ? <Button onClick={() => setCreating(true)} data-testid="new-work"><span className="flex items-center gap-1.5"><Plus size={15} /> New work</span></Button> : undefined} />

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
        <Card className="p-8 text-center text-slate-500 dark:text-zinc-400">No works {status || q ? "match this filter" : "yet"}. {can("workpage", "create") && !status && !q ? "Create one, or accept a quotation in Sales and it appears here." : ""}</Card>
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
                  <td className="p-3"><Link href={`/workpage/${w.id}`} className="font-medium text-slate-800 dark:text-white hover:underline">{w.client_name}</Link><div className="text-xs text-slate-400 dark:text-zinc-500">{w.work_number}</div></td>
                  <td className="p-3 text-slate-600 dark:text-zinc-300">{w.domain || "—"}</td>
                  <td className="p-3"><StatusPill label={w.status_label} color={w.status_color} /></td>
                  <td className="p-3 text-right tabular-nums text-slate-800 dark:text-white">{inr(w.quotation_amount)}</td>
                  <td className="p-3 text-right tabular-nums text-slate-600 dark:text-zinc-300">{inr(w.vendor_amount)}</td>
                  <td className="p-3 text-right tabular-nums text-slate-600 dark:text-zinc-300">{Number(w.discount_percent)}%</td>
                  <td className={`p-3 text-right tabular-nums font-medium ${Number(w.profit) < 0 ? "text-red-600 dark:text-red-400" : "text-green-700 dark:text-green-400"}`}>{inr(w.profit)}</td>
                  <td className="p-3 text-slate-600 dark:text-zinc-300">{w.handling_department || <span className="text-slate-400">Not assigned</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <p className="text-xs text-slate-500 dark:text-zinc-500 mt-3">Profit = quotation amount − client discount − vendor amount.</p>

      {creating && (
        <Modal title="New work" onClose={() => setCreating(false)} wide>
          <form onSubmit={create} className="space-y-3">
            <Input label="Client name" required value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />
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
