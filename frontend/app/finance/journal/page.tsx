"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { PaginationControls } from "@/components/Pagination";
import { SkeletonList } from "@/components/Skeleton";

type Account = { id: string; code: string; name: string };
type Entry = { id: string; entry_number: string | null; date: string; reference: string | null; description: string | null; lines: { account_id: string; debit: string; credit: string }[] };
type Page = { total: number; page: number; total_pages: number; items: Entry[] };
const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function JournalPage() {
  const [data, setData] = useState<Page | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { apiRequest<Account[]>("/api/finance/accounts", { auth: true }).then(setAccounts).catch(() => {}); }, []);
  useEffect(() => { const t = setTimeout(() => { setTerm(q); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  const load = useCallback(() => {
    const qs = new URLSearchParams({ page: String(page), page_size: "15" });
    if (term.trim()) qs.set("q", term.trim());
    apiRequest<Page>(`/api/finance/journal-entries/page?${qs}`, { auth: true }).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  }, [page, term]);
  useEffect(load, [load]);
  const name = (id: string) => { const a = accounts.find((x) => x.id === id); return a ? `${a.code} · ${a.name}` : id.slice(0, 8); };
  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Journal Entries" backHref="/finance" backLabel="← Finance" description="Every accounting entry, newest first. Each one's debits equal its credits." />
      <div className="flex flex-wrap gap-2 mb-4 items-center">
        <input placeholder="Search number, reference or description" className="border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm w-full max-w-sm" value={q} onChange={(e) => setQ(e.target.value)} />
        {data && <span className="text-xs text-slate-500 dark:text-zinc-400">{data.total} entr{data.total === 1 ? "y" : "ies"}</span>}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!data ? <SkeletonList rows={5} /> : (
        <>
          <div className="space-y-2" data-testid="journal-list">
            {data.items.map((e) => (
              <div key={e.id} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-3" data-testid="journal-entry">
                <div className="flex justify-between items-center mb-1"><span className="text-sm font-semibold text-slate-800 dark:text-white">{e.entry_number || "-"}</span><span className="text-xs text-slate-400 dark:text-zinc-500">{e.date}</span></div>
                <p className="text-sm text-slate-700 dark:text-zinc-200 mb-2">{e.description}</p>
                {e.lines.map((l, i) => (
                  <p key={i} className="text-xs text-slate-500 dark:text-zinc-400 flex justify-between"><span>{name(l.account_id)}</span><span className="tabular-nums">{Number(l.debit) > 0 ? `Dr ${inr(l.debit)}` : `Cr ${inr(l.credit)}`}</span></p>
                ))}
              </div>
            ))}
            {data.items.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No journal entries match.</p>}
          </div>
          <PaginationControls page={data.page} totalPages={data.total_pages} onChange={setPage} />
        </>
      )}
    </main>
  );
}
