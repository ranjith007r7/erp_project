"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { CustomFieldsSection } from "@/components/CustomFieldsSection";

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
  const [leads, setLeads] = useState<Lead[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [form, setForm] = useState({ name: "", company_name: "", email: "", source: "" });
  const [error, setError] = useState<string | null>(null);
  const [expandedLeadId, setExpandedLeadId] = useState<string | null>(null);

  function loadAll() {
    apiRequest<Lead[]>("/api/crm/leads", { auth: true }).then(setLeads).catch((e) => setError(e.message));
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add lead");
    }
  }

  async function handleConvert(leadId: string) {
    const opportunity_name = window.prompt("Opportunity name for this deal?");
    if (!opportunity_name) return;
    const valueStr = window.prompt("Estimated deal value (₹)?", "0") || "0";
    try {
      await apiRequest(`/api/crm/leads/${leadId}/convert`, {
        method: "POST",
        auth: true,
        body: { opportunity_name, opportunity_value: Number(valueStr) },
      });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to convert lead");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-slate-800">CRM</h1>
        <Link href="/dashboard" className="text-sm text-slate-500 underline">
          ← Dashboard
        </Link>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-2 gap-8">
        {/* Leads */}
        <section>
          <h2 className="text-lg font-semibold text-slate-700 mb-3">Leads</h2>

          <form onSubmit={handleAddLead} className="bg-white rounded-xl shadow-sm p-4 mb-4 space-y-2">
            <input
              placeholder="Name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Company"
              value={form.company_name}
              onChange={(e) => setForm({ ...form, company_name: e.target.value })}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Source (e.g. Website)"
              value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value })}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
              Add Lead
            </button>
          </form>

          <div className="space-y-2">
            {leads.map((lead) => {
              const expanded = expandedLeadId === lead.id;
              return (
                <div key={lead.id} className="bg-white rounded-lg shadow-sm p-3">
                  <div className="flex justify-between items-center">
                    <div>
                      <p className="font-medium text-slate-800">{lead.name}</p>
                      <p className="text-xs text-slate-500">
                        {lead.company_name} · {lead.source} ·{" "}
                        <span
                          className={
                            lead.status === "converted" ? "text-green-600 font-medium" : "text-slate-400"
                          }
                        >
                          {lead.status}
                        </span>
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setExpandedLeadId(expanded ? null : lead.id)}
                        className="text-xs text-slate-400 underline hover:text-slate-600"
                      >
                        {expanded ? "Hide fields" : "Fields"}
                      </button>
                      {lead.status !== "converted" && (
                        <button
                          onClick={() => handleConvert(lead.id)}
                          className="text-xs bg-slate-800 text-white px-3 py-1.5 rounded-lg hover:bg-slate-700"
                        >
                          Convert →
                        </button>
                      )}
                    </div>
                  </div>
                  {expanded && <CustomFieldsSection entityType="lead" entityId={lead.id} />}
                </div>
              );
            })}
            {leads.length === 0 && <p className="text-sm text-slate-400">No leads yet.</p>}
          </div>
        </section>

        {/* Opportunities */}
        <section>
          <h2 className="text-lg font-semibold text-slate-700 mb-3">Opportunities</h2>
          <div className="space-y-2">
            {opportunities.map((opp) => (
              <div key={opp.id} className="bg-white rounded-lg shadow-sm p-3">
                <p className="font-medium text-slate-800">{opp.name}</p>
                <p className="text-xs text-slate-500">
                  Stage: {opp.stage} · Value: ₹{Number(opp.value).toLocaleString("en-IN")}
                </p>
              </div>
            ))}
            {opportunities.length === 0 && (
              <p className="text-sm text-slate-400">
                No opportunities yet — convert a lead to create one.
              </p>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
