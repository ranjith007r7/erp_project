"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader, Card } from "@/components/ui";
import { usePagination, PaginationControls } from "@/components/Pagination";

type AuditEntry = {
  id: string;
  user_id: string | null;
  user_name: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  created_at: string;
};

const ACTION_LABELS: Record<string, string> = {
  grant_permission: "granted a permission",
  revoke_permission: "revoked a permission",
  create_user: "created a user",
  change_user_role: "changed a user's role",
  approval_approve: "approved a request",
  approval_reject: "rejected a request",
  record_payment: "recorded a payment",
  receive_purchase_order: "received a purchase order",
  process_payroll: "processed payroll",
  generate_invoice: "generated an invoice",
};

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { pageItems, page, totalPages, setPage } = usePagination(entries, 20);

  useEffect(() => {
    apiRequest<AuditEntry[]>("/api/core/audit-log", { auth: true })
      .then(setEntries)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load audit log"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Audit Log" />

      <p className="text-sm text-slate-500 dark:text-zinc-500 mb-4 max-w-2xl">
        A permanent, read-only record of sensitive actions — role and permission changes, payments,
        approvals, payroll, and invoices. Showing the {entries.length >= 500 ? "500 most recent (older entries exist beyond this)" : `${entries.length} most recent`} entries.
      </p>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <Card className="max-w-3xl">
        {loading && <p className="p-4 text-sm text-slate-400 dark:text-zinc-500">Loading…</p>}
        {!loading && (
          <div className="divide-y">
            {pageItems.map((entry) => (
              <div key={entry.id} className="p-3 text-sm">
                <p className="text-slate-800 dark:text-white">
                  <span className="font-medium">{entry.user_name || "Someone"}</span>{" "}
                  {ACTION_LABELS[entry.action] || entry.action}
                  {entry.entity && <span className="text-slate-500 dark:text-zinc-500"> ({entry.entity})</span>}
                </p>
                <p className="text-xs text-slate-400 dark:text-zinc-500 mt-0.5">
                  {new Date(entry.created_at).toLocaleString()}
                </p>
              </div>
            ))}
            {entries.length === 0 && <p className="p-4 text-sm text-slate-400 dark:text-zinc-500">No audit entries yet.</p>}
          </div>
        )}
        <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />
      </Card>
    </main>
  );
}
