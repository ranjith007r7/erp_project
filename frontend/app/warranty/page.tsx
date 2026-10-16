"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { SkeletonList } from "@/components/Skeleton";
import { WarrantyRow, STATE_STYLE, fmtDate } from "@/lib/warranty";

const TABS = [
  { key: "", label: "All" }, { key: "pending_details", label: "Details to fill" }, { key: "pending_approval", label: "Waiting for approval" },
  { key: "active", label: "Active" }, { key: "no_warranty", label: "No warranty" },
];

export default function WarrantyPage() {
  const [rows, setRows] = useState<WarrantyRow[] | null>(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { const t = setTimeout(() => setTerm(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => {
    apiRequest<WarrantyRow[]>(`/api/warranty?status=${status}&q=${encodeURIComponent(term)}`, { auth: true }).then(setRows).catch((e) => setError(e.message));
  }, [status, term]);

  const input = "border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm";
  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Warranty" description="Every delivered work lands here. Fill the unit details, send for approval, and print the warranty card once it is approved." />
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setStatus(t.key)} data-testid={`tab-${t.key || "all"}`}
            className={`px-3 py-1.5 rounded-lg text-sm border ${status === t.key ? "bg-slate-800 text-white border-slate-800 dark:bg-zinc-100 dark:text-zinc-900" : "bg-white dark:bg-zinc-900 text-slate-700 dark:text-zinc-200 border-slate-200 dark:border-zinc-700"}`}>{t.label}</button>
        ))}
        <input placeholder="Search work no., client or card no." className={`${input} ml-auto`} value={q} onChange={(e) => setQ(e.target.value)} data-testid="warranty-search" />
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!rows ? <SkeletonList rows={5} /> : (
        <div className="space-y-2" data-testid="warranty-list">
          {rows.map((r) => (
            <Link key={r.id} href={`/warranty/${r.id}`} data-testid="warranty-row"
              className="block bg-white dark:bg-zinc-900 rounded-lg shadow-sm dark:shadow-none dark:border dark:border-zinc-800 p-3 hover:bg-slate-50 dark:hover:bg-zinc-800">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium text-slate-800 dark:text-white">{r.product_name} <span className="text-slate-500 dark:text-zinc-400 font-normal">× {r.qty}</span></p>
                  <p className="text-xs text-slate-500 dark:text-zinc-400">{r.work_number} · {r.client_name} · Invoice {r.invoice_number || "not issued yet"}</p>
                  <p className="text-xs text-slate-400 dark:text-zinc-500">
                    {r.end_date ? `Valid ${fmtDate(r.start_date)} to ${fmtDate(r.end_date)} (${r.period_label})` : `Delivered ${fmtDate(r.start_date)}`}{r.card_number ? ` · ${r.card_number}` : ""}
                  </p>
                </div>
                <span className={`text-xs px-2 py-1 rounded-full font-semibold ${STATE_STYLE[r.state] || ""}`}>{r.state}</span>
              </div>
            </Link>
          ))}
          {rows.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">Nothing here yet. Warranty records appear automatically when a work is delivered.</p>}
        </div>
      )}
    </main>
  );
}
