"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { PageHeader } from "@/components/ui";

type Account = { id: string; code: string; name: string; account_type: string };
type JournalLine = { account_id: string; debit: string; credit: string };
type JournalEntry = { id: string; date: string; reference: string | null; description: string | null; lines: JournalLine[] };
type Invoice = { id: string; amount: string; status: string };

export default function FinancePage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [error, setError] = useState<string | null>(null);

  function loadAll() {
    apiRequest<Account[]>("/api/finance/accounts", { auth: true }).then(setAccounts).catch((e) => setError(e.message));
    apiRequest<JournalEntry[]>("/api/finance/journal-entries", { auth: true }).then(setEntries).catch(() => {});
    apiRequest<Invoice[]>("/api/sales/invoices", { auth: true }).then(setInvoices).catch(() => {});
  }

  useEffect(loadAll, []);

  function accountName(id: string) {
    return accounts.find((a) => a.id === id)?.name || id.slice(0, 8);
  }

  async function recordPayment(invoiceId: string, amount: string) {
    try {
      await apiRequest("/api/finance/payments", {
        method: "POST",
        auth: true,
        body: { invoice_id: invoiceId, amount: Number(amount), method: "bank_transfer" },
      });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to record payment");
    }
  }

  const unpaidInvoices = invoices.filter((inv) => inv.status !== "paid");

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Finance & Accounting" />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-3 gap-6">
        {/* Chart of Accounts */}
        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Chart of Accounts</h2>
          <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm divide-y">
            {accounts.map((a) => (
              <div key={a.id} className="p-3 flex justify-between text-sm">
                <span className="text-slate-800 dark:text-white">{a.code} · {a.name}</span>
                <span className="text-slate-400 dark:text-zinc-500 text-xs">{a.account_type}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Unpaid Invoices -> Record Payment */}
        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Unpaid Invoices</h2>
          <div className="space-y-2">
            {unpaidInvoices.map((inv) => (
              <div key={inv.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3 flex justify-between items-center">
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-white">₹{Number(inv.amount).toLocaleString("en-IN")}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">{inv.status}</p>
                </div>
                <button
                  onClick={() => recordPayment(inv.id, inv.amount)}
                  className="text-xs bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 px-3 py-1.5 rounded-lg hover:bg-slate-700 dark:hover:bg-zinc-300"
                >
                  Record Payment
                </button>
              </div>
            ))}
            {unpaidInvoices.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No unpaid invoices.</p>}
          </div>
        </section>

        {/* Journal Entries */}
        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Journal Entries</h2>
          <div className="space-y-2">
            {entries.map((entry) => (
              <div key={entry.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3">
                <p className="text-xs text-slate-400 dark:text-zinc-500 mb-1">{entry.date} · {entry.reference}</p>
                <p className="text-sm text-slate-700 dark:text-zinc-200 mb-2">{entry.description}</p>
                {entry.lines.map((line, i) => (
                  <p key={i} className="text-xs text-slate-500 dark:text-zinc-500 flex justify-between">
                    <span>{accountName(line.account_id)}</span>
                    <span>
                      {Number(line.debit) > 0
                        ? `Dr ₹${Number(line.debit).toLocaleString("en-IN")}`
                        : `Cr ₹${Number(line.credit).toLocaleString("en-IN")}`}
                    </span>
                  </p>
                ))}
              </div>
            ))}
            {entries.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No journal entries yet.</p>}
          </div>
        </section>
      </div>
    </main>
  );
}
