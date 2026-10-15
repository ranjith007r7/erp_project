"use client";

import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { usePagination, PaginationControls } from "@/components/Pagination";
import { SkeletonList } from "@/components/Skeleton";

type Account = { id: string; code: string; name: string; account_type: string };

export default function ChartOfAccountsPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { apiRequest<Account[]>("/api/finance/accounts", { auth: true }).then(setAccounts).catch((e) => setError(e.message)); }, []);
  const shown = useMemo(() => (accounts ?? []).filter((a) => !q.trim() || `${a.code} ${a.name} ${a.account_type}`.toLowerCase().includes(q.trim().toLowerCase())), [accounts, q]);
  const { pageItems, page, totalPages, setPage } = usePagination(shown, 15);
  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Chart of Accounts" backHref="/finance" backLabel="← Finance"
        description="The fixed list of ledger buckets every entry posts into. It is created for you and extends itself: the first time a feature needs a new account (for example payroll deductions or cancellation charges) it appears here." />
      <input placeholder="Search code, name or type" className="mb-4 border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm w-full max-w-xs" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!accounts ? <SkeletonList rows={5} /> : (
        <>
          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm divide-y divide-slate-100 dark:divide-zinc-800" data-testid="account-list">
            {pageItems.map((a) => (
              <div key={a.id} className="p-3 flex justify-between text-sm"><span className="text-slate-800 dark:text-white">{a.code} · {a.name}</span><span className="text-slate-400 dark:text-zinc-500 text-xs">{a.account_type}</span></div>
            ))}
            {shown.length === 0 && <p className="p-3 text-sm text-slate-400">No account matches.</p>}
          </div>
          <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />
        </>
      )}
    </main>
  );
}
