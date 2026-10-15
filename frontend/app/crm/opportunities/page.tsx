"use client";

import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { usePagination, PaginationControls } from "@/components/Pagination";
import { SkeletonList } from "@/components/Skeleton";

type Opportunity = { id: string; name: string; stage: string; value: string };

export default function OpportunitiesPage() {
  const [items, setItems] = useState<Opportunity[] | null>(null);
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { apiRequest<Opportunity[]>("/api/crm/opportunities", { auth: true }).then(setItems).catch((e) => setError(e.message)); }, []);
  const stages = useMemo(() => Array.from(new Set((items ?? []).map((o) => o.stage))), [items]);
  const shown = useMemo(() => (items ?? []).filter((o) => (!stage || o.stage === stage) && (!q.trim() || o.name.toLowerCase().includes(q.trim().toLowerCase()))), [items, q, stage]);
  const { pageItems, page, totalPages, setPage } = usePagination(shown, 15);
  const total = shown.reduce((s, o) => s + Number(o.value || 0), 0);
  const sel = "border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm";
  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Opportunities" description="Deals converted from leads, with their stage and value." backHref="/crm" backLabel="← CRM" />
      <div className="flex flex-wrap gap-2 mb-4">
        <input placeholder="Search by name" className={sel} value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select aria-label="Stage" className={sel} value={stage} onChange={(e) => { setStage(e.target.value); setPage(1); }}>
          <option value="">All stages</option>{stages.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="self-center text-xs text-slate-500 dark:text-zinc-400">{shown.length} opportunit{shown.length === 1 ? "y" : "ies"} · total ₹{total.toLocaleString("en-IN")}</span>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!items ? <SkeletonList rows={5} /> : (
        <>
          <div className="space-y-2" data-testid="opportunity-list">
            {pageItems.map((o) => (
              <div key={o.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3 flex justify-between gap-3" data-testid="opportunity">
                <div><p className="font-medium text-slate-800 dark:text-white">{o.name}</p><p className="text-xs text-slate-500 dark:text-zinc-500">Stage: {o.stage}</p></div>
                <p className="font-semibold tabular-nums text-slate-800 dark:text-white">₹{Number(o.value).toLocaleString("en-IN")}</p>
              </div>
            ))}
            {shown.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">{items.length ? "No opportunity matches." : "No opportunities yet. Convert a lead to create one."}</p>}
          </div>
          <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />
        </>
      )}
    </main>
  );
}
