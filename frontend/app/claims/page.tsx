"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { SkeletonList } from "@/components/Skeleton";
import { ClaimRow, CLAIM_STYLE, fmtDate } from "@/lib/warranty";

const TABS = [{ key: "", label: "All" }, { key: "open", label: "Open" }, { key: "pending_approval", label: "Waiting for approval" },
  { key: "replaced", label: "Replaced" }, { key: "repaired", label: "Repaired" }, { key: "rejected", label: "Rejected" }];

export default function ClaimsPage() {
  const [rows, setRows] = useState<ClaimRow[] | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { apiRequest<ClaimRow[]>(`/api/claims?status=${status}`, { auth: true }).then(setRows).catch((e) => setError(e.message)); }, [status]);
  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Claims" description="Customer warranty claims. Raise one from an active warranty (Warranty > open the record > Raise a claim)." />
      <div className="flex flex-wrap gap-2 mb-4">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setStatus(t.key)} data-testid={`ctab-${t.key || "all"}`}
            className={`px-3 py-1.5 rounded-lg text-sm border ${status === t.key ? "bg-slate-800 text-white border-slate-800 dark:bg-zinc-100 dark:text-zinc-900" : "bg-white dark:bg-zinc-900 text-slate-700 dark:text-zinc-200 border-slate-200 dark:border-zinc-700"}`}>{t.label}</button>
        ))}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!rows ? <SkeletonList rows={5} /> : (
        <div className="space-y-2" data-testid="claims-list">
          {rows.map((c) => (
            <Link key={c.id} href={`/claims/${c.id}`} data-testid="claim-row" className="block bg-white dark:bg-zinc-900 rounded-lg shadow-sm dark:shadow-none dark:border dark:border-zinc-800 p-3 hover:bg-slate-50 dark:hover:bg-zinc-800">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium text-slate-800 dark:text-white">{c.claim_number} · {c.product_name}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-400">{c.work_number} · {c.client_name} · Serial {c.serial_number || "-"} · raised {fmtDate(c.created_at.slice(0, 10))}</p>
                </div>
                <div className="flex items-center gap-2">
                  {c.out_of_warranty && <span className="text-xs px-2 py-1 rounded-full font-semibold bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300">Out of warranty</span>}
                  <span className={`text-xs px-2 py-1 rounded-full font-semibold ${CLAIM_STYLE[c.status] || ""}`}>{c.status_label}</span>
                </div>
              </div>
            </Link>
          ))}
          {rows.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No claims.</p>}
        </div>
      )}
    </main>
  );
}
