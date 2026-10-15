"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { PaginationControls } from "@/components/Pagination";
import { SkeletonList } from "@/components/Skeleton";

type Work = { work_id: string; work_number: string; status: string; status_label: string } | null;
type Item = { id: string; name: string; company_name: string | null; phone: string | null; email: string | null; source: string | null; estimated_amount: string | null; converted_at: string | null; created_at: string; work: Work };
type Page = { total: number; page: number; page_size: number; total_pages: number; items: Item[] };

export default function ConvertedPage() {
  const [data, setData] = useState<Page | null>(null);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { const t = setTimeout(() => { setTerm(q); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => {
    apiRequest<Page>(`/api/crm/leads/converted?page=${page}&page_size=15&q=${encodeURIComponent(term)}`, { auth: true }).then(setData).catch((e) => setError(e.message));
  }, [page, term]);

  const input = "border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm";
  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Converted list" description="Quotations that were converted into jobs, newest first. They cannot be deleted: each job ends as Work completed or Cancelled on its work page." backHref="/crm" backLabel="← CRM" />
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <input placeholder="Search name, company or mobile" className={input} value={q} onChange={(e) => setQ(e.target.value)} data-testid="converted-search" />
        {data && <span className="text-xs text-slate-500 dark:text-zinc-400">{data.total} converted</span>}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!data ? <SkeletonList rows={5} /> : (
        <>
          <div className="space-y-2" data-testid="converted-list">
            {data.items.map((l) => (
              <div key={l.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3 flex flex-wrap items-center justify-between gap-3" data-testid="converted-row">
                <div>
                  <p className="font-medium text-slate-800 dark:text-white">{l.name}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">
                    {[l.company_name, l.phone, l.estimated_amount != null ? `₹${Number(l.estimated_amount).toLocaleString("en-IN")}` : null, l.source].filter(Boolean).join(" · ")}
                  </p>
                  <p className="text-xs text-slate-400 dark:text-zinc-500">Converted {l.converted_at ? new Date(l.converted_at + "Z").toLocaleDateString("en-IN") : "-"}</p>
                </div>
                {l.work ? (
                  <Link href={`/workpage/${l.work.work_id}`} className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline">
                    {l.work.work_number} · {l.work.status_label} →
                  </Link>
                ) : <span className="text-xs text-slate-400">No work linked</span>}
              </div>
            ))}
            {data.items.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">{term ? "Nothing matches that search." : "Nothing has been converted yet."}</p>}
          </div>
          <PaginationControls page={page} totalPages={data.total_pages} onChange={setPage} />
        </>
      )}
    </main>
  );
}
