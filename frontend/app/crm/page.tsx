"use client";

import { useEffect, useState } from "react";
import { apiRequest, apiDownload, apiUpload } from "@/lib/api";
import { CustomFieldsSection } from "@/components/CustomFieldsSection";
import { Modal } from "@/components/Modal";
import { PageHeader, Button } from "@/components/ui";
import { usePagination, PaginationControls } from "@/components/Pagination";
import { useToast } from "@/components/Toast";
import { SkeletonList } from "@/components/Skeleton";

type Lead = {
  id: string;
  name: string;
  company_name: string | null;
  email: string | null;
  source: string | null;
  status: string;
};

type Opportunity = {
  id: string;
  name: string;
  stage: string;
  value: string;
};

export default function CRMPage() {
  const { showToast } = useToast();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [leadsLoading, setLeadsLoading] = useState(true);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [form, setForm] = useState({ name: "", company_name: "", email: "", source: "" });
  const [error, setError] = useState<string | null>(null);
  const [expandedLeadId, setExpandedLeadId] = useState<string | null>(null);
  const { pageItems: pagedLeads, page: leadPage, totalPages: leadTotalPages, setPage: setLeadPage } = usePagination(leads, 10);
  const [convertingLead, setConvertingLead] = useState<Lead | null>(null);
  const [convertForm, setConvertForm] = useState({ opportunity_name: "", value: "" });
  const [selectedLeadIds, setSelectedLeadIds] = useState<Set<string>>(new Set());
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; failed: number; errors: { row: number; reason: string }[] } | null>(null);

  function toggleLeadSelection(id: string) {
    setSelectedLeadIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleBulkDelete() {
    if (selectedLeadIds.size === 0) return;
    if (!window.confirm(`Delete ${selectedLeadIds.size} selected lead(s)? This can't be undone.`)) return;
    setError(null);
    try {
      await apiRequest("/api/crm/leads/bulk-delete", { method: "POST", auth: true, body: { ids: Array.from(selectedLeadIds) } });
      showToast(`Deleted ${selectedLeadIds.size} lead(s).`, "success");
      setSelectedLeadIds(new Set());
      loadAll();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Bulk delete failed";
      setError(message);
      showToast(message, "error");
    }
  }

  function handleExportCsv() {
    apiDownload("/api/crm/leads/export", "leads.csv").catch((err) => {
      const message = err instanceof Error ? err.message : "Export failed";
      setError(message);
      showToast(message, "error");
    });
  }

  async function handleImportCsv() {
    if (!importFile) return;
    setImporting(true);
    setError(null);
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append("file", importFile);
      const result = await apiUpload<{ imported: number; failed: number; errors: { row: number; reason: string }[] }>(
        "/api/crm/leads/import", formData
      );
      setImportResult(result);
      setImportFile(null);
      loadAll();
      showToast(
        result.failed > 0 ? `Imported ${result.imported}, ${result.failed} failed.` : `Imported ${result.imported} lead(s).`,
        result.failed > 0 ? "info" : "success"
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Import failed";
      setError(message);
      showToast(message, "error");
    } finally {
      setImporting(false);
    }
  }

  function loadAll() {
    apiRequest<Lead[]>("/api/crm/leads", { auth: true })
      .then(setLeads)
      .catch((e) => setError(e.message))
      .finally(() => setLeadsLoading(false));
    apiRequest<Opportunity[]>("/api/crm/opportunities", { auth: true }).then(setOpportunities).catch(() => {});
  }

  useEffect(loadAll, []);

  async function handleAddLead(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await apiRequest("/api/crm/leads", { method: "POST", auth: true, body: form });
      setForm({ name: "", company_name: "", email: "", source: "" });
      loadAll();
      showToast("Lead added.", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to add lead";
      setError(message);
      showToast(message, "error");
    }
  }

  function openConvertModal(lead: Lead) {
    setConvertForm({ opportunity_name: "", value: "0" });
    setConvertingLead(lead);
  }

  async function handleConvert(e: React.FormEvent) {
    e.preventDefault();
    if (!convertingLead) return;
    try {
      await apiRequest(`/api/crm/leads/${convertingLead.id}/convert`, {
        method: "POST",
        auth: true,
        body: {
          opportunity_name: convertForm.opportunity_name,
          opportunity_value: Number(convertForm.value) || 0,
        },
      });
      setConvertingLead(null);
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to convert lead");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="CRM" />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-2 gap-8">
        {/* Leads */}
        <section>
          <h2 className="text-lg font-semibold text-slate-700 dark:text-zinc-200 mb-3">Leads</h2>

          <form onSubmit={handleAddLead} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 mb-4 space-y-2">
            <input
              placeholder="Name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Company"
              value={form.company_name}
              onChange={(e) => setForm({ ...form, company_name: e.target.value })}
              className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Source (e.g. Website)"
              value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value })}
              className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
            />
            <Button type="submit" className="w-full">Add Lead</Button>
          </form>

          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <Button variant="secondary" size="sm" onClick={handleExportCsv}>Export CSV</Button>
            <input
              type="file"
              accept=".csv"
              onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
              className="text-xs"
            />
            <Button variant="secondary" size="sm" disabled={!importFile || importing} onClick={handleImportCsv}>
              {importing ? "Importing…" : "Import CSV"}
            </Button>
            {selectedLeadIds.size > 0 && (
              <Button variant="danger" size="sm" onClick={handleBulkDelete}>
                Delete {selectedLeadIds.size} selected
              </Button>
            )}
          </div>

          {importResult && (
            <div className="text-xs bg-slate-50 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-800 rounded-lg p-2 mb-2">
              <p className="text-slate-700 dark:text-zinc-200">
                Imported {importResult.imported}, failed {importResult.failed}.
              </p>
              {importResult.errors.map((e) => (
                <p key={e.row} className="text-red-600">Row {e.row}: {e.reason}</p>
              ))}
            </div>
          )}

          {leadsLoading ? (
            <SkeletonList rows={3} />
          ) : (
            <div className="space-y-2">
              {pagedLeads.map((lead) => {
                const expanded = expandedLeadId === lead.id;
                return (
                  <div key={lead.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3">
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selectedLeadIds.has(lead.id)}
                          onChange={() => toggleLeadSelection(lead.id)}
                        />
                        <div>
                          <p className="font-medium text-slate-800 dark:text-white">{lead.name}</p>
                          <p className="text-xs text-slate-500 dark:text-zinc-500">
                            {lead.company_name} · {lead.source} ·{" "}
                            <span
                              className={
                                lead.status === "converted" ? "text-green-600 font-medium" : "text-slate-400 dark:text-zinc-500"
                              }
                            >
                              {lead.status}
                            </span>
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="ghost"
                          onClick={() => setExpandedLeadId(expanded ? null : lead.id)}
                        >
                          {expanded ? "Hide fields" : "Fields"}
                        </Button>
                        {lead.status !== "converted" && (
                          <Button size="sm" onClick={() => openConvertModal(lead)}>
                            Convert →
                          </Button>
                        )}
                      </div>
                    </div>
                    {expanded && <CustomFieldsSection entityType="lead" entityId={lead.id} />}
                  </div>
                );
              })}
              {leads.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No leads yet.</p>}
            </div>
          )}
          <PaginationControls page={leadPage} totalPages={leadTotalPages} onChange={setLeadPage} />
        </section>

        {/* Opportunities */}
        <section>
          <h2 className="text-lg font-semibold text-slate-700 dark:text-zinc-200 mb-3">Opportunities</h2>
          <div className="space-y-2">
            {opportunities.map((opp) => (
              <div key={opp.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3">
                <p className="font-medium text-slate-800 dark:text-white">{opp.name}</p>
                <p className="text-xs text-slate-500 dark:text-zinc-500">
                  Stage: {opp.stage} · Value: ₹{Number(opp.value).toLocaleString("en-IN")}
                </p>
              </div>
            ))}
            {opportunities.length === 0 && (
              <p className="text-sm text-slate-400 dark:text-zinc-500">
                No opportunities yet — convert a lead to create one.
              </p>
            )}
          </div>
        </section>
      </div>

      {convertingLead && (
        <Modal title={`Convert "${convertingLead.name}" to an Opportunity`} onClose={() => setConvertingLead(null)}>
          <form onSubmit={handleConvert} className="space-y-3">
            <label className="block text-sm text-slate-600 dark:text-zinc-300">
              Opportunity name
              <input
                autoFocus
                required
                value={convertForm.opportunity_name}
                onChange={(e) => setConvertForm({ ...convertForm, opportunity_name: e.target.value })}
                placeholder="e.g. Acme Corp — Website Revamp"
                className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm mt-1"
              />
            </label>
            <label className="block text-sm text-slate-600 dark:text-zinc-300">
              Estimated deal value (₹)
              <input
                type="number"
                min="0"
                value={convertForm.value}
                onChange={(e) => setConvertForm({ ...convertForm, value: e.target.value })}
                className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm mt-1"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConvertingLead(null)}
                className="text-sm text-slate-500 dark:text-zinc-500 px-3 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button type="submit" className="text-sm bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 px-4 py-1.5 rounded-lg hover:bg-slate-700 dark:hover:bg-zinc-300">
                Convert
              </button>
            </div>
          </form>
        </Modal>
      )}
    </main>
  );
}
