"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, apiDownload } from "@/lib/api";
import { PromptModal } from "@/components/Modal";

type ReportModule = "sales" | "finance" | "inventory" | "procurement" | "hr" | "crm" | "projects";

const TABS: { key: ReportModule; label: string }[] = [
  { key: "sales", label: "Sales" },
  { key: "finance", label: "Finance" },
  { key: "inventory", label: "Inventory" },
  { key: "procurement", label: "Procurement" },
  { key: "hr", label: "HR" },
  { key: "crm", label: "CRM" },
  { key: "projects", label: "Projects" },
];

const ENDPOINTS: Record<ReportModule, string> = {
  sales: "/api/reports/sales-summary",
  finance: "/api/reports/finance-summary",
  inventory: "/api/reports/inventory-summary",
  procurement: "/api/reports/procurement-summary",
  hr: "/api/reports/hr-summary",
  crm: "/api/reports/crm-funnel",
  projects: "/api/reports/projects-summary",
};

type SavedReport = {
  id: string;
  name: string;
  module: string;
  query_config: Record<string, unknown>;
  created_at: string;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ReportData = any;

export default function ReportsPage() {
  const [activeTab, setActiveTab] = useState<ReportModule>("sales");
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedReports, setSavedReports] = useState<SavedReport[]>([]);
  const [showSaveModal, setShowSaveModal] = useState(false);

  function loadReport(tab: ReportModule) {
    setLoading(true);
    setError(null);
    apiRequest<ReportData>(ENDPOINTS[tab], { auth: true })
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load report"))
      .finally(() => setLoading(false));
  }

  function handleTabChange(tab: ReportModule) {
    // Clearing `data` here (not just relying on the effect below) matters:
    // setActiveTab causes an immediate re-render, and without this, that
    // render would try to draw e.g. FinanceReport using the PREVIOUS tab's
    // data shape (still sitting in state until the new fetch resolves),
    // which throws - a real bug found from your bug report. Clearing data
    // synchronously means the render that happens before the fetch
    // completes has nothing to draw, so it safely shows "Loading..." instead.
    setData(null);
    setActiveTab(tab);
  }

  function loadSavedReports() {
    apiRequest<SavedReport[]>("/api/reports/saved", { auth: true }).then(setSavedReports).catch(() => {});
  }

  useEffect(() => {
    loadReport(activeTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  useEffect(loadSavedReports, []);

  async function handleExport() {
    try {
      await apiDownload(`/api/reports/export/${activeTab}`, `${activeTab}_report.csv`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    }
  }

  async function handleSaveView(name: string) {
    try {
      await apiRequest("/api/reports/saved", {
        method: "POST",
        auth: true,
        body: { name, module: activeTab, query_config: {} },
      });
      setShowSaveModal(false);
      loadSavedReports();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save report");
    }
  }

  async function handleDeleteSaved(id: string) {
    try {
      await apiRequest(`/api/reports/saved/${id}`, { method: "DELETE", auth: true });
      loadSavedReports();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Reports & Analytics</h1>
        <Link href="/dashboard" className="text-sm text-slate-500 underline">
          ← Dashboard
        </Link>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {/* Tabs */}
      <div className="flex gap-2 mb-6 flex-wrap">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab.key ? "bg-slate-800 text-white" : "bg-white text-slate-600 shadow-sm hover:bg-slate-100"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex gap-3 mb-6">
        <button
          onClick={handleExport}
          className="text-sm bg-white shadow-sm rounded-lg px-3 py-1.5 text-slate-700 hover:bg-slate-100"
        >
          ⬇ Export CSV
        </button>
        <button
          onClick={() => setShowSaveModal(true)}
          className="text-sm bg-white shadow-sm rounded-lg px-3 py-1.5 text-slate-700 hover:bg-slate-100"
        >
          ★ Save this view
        </button>
      </div>

      {loading && <p className="text-slate-400 text-sm">Loading...</p>}

      {!loading && data && (
        <div className="grid md:grid-cols-3 gap-6 mb-10">
          <div key={activeTab} className="md:col-span-2 space-y-6">
            {activeTab === "sales" && <SalesReport data={data} />}
            {activeTab === "finance" && <FinanceReport data={data} />}
            {activeTab === "inventory" && <InventoryReport data={data} />}
            {activeTab === "procurement" && <ProcurementReport data={data} />}
            {activeTab === "hr" && <HrReport data={data} />}
            {activeTab === "crm" && <CrmReport data={data} />}
            {activeTab === "projects" && <ProjectsReport data={data} />}
          </div>

          {/* Saved Reports sidebar */}
          <section>
            <h2 className="font-semibold text-slate-700 mb-3">Saved Reports</h2>
            <div className="bg-white rounded-lg shadow-sm divide-y">
              {savedReports.length === 0 && (
                <p className="p-3 text-sm text-slate-400">No saved views yet.</p>
              )}
              {savedReports.map((r) => (
                <div key={r.id} className="p-3 flex justify-between items-center text-sm">
                  <div>
                    <p className="text-slate-800">{r.name}</p>
                    <p className="text-xs text-slate-400">{r.module}</p>
                  </div>
                  <button
                    onClick={() => handleDeleteSaved(r.id)}
                    className="text-xs text-red-500 hover:underline"
                  >
                    delete
                  </button>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {showSaveModal && (
        <PromptModal
          title="Save Report View"
          label="Name this saved report view"
          placeholder="e.g. Monthly Revenue Snapshot"
          onSubmit={handleSaveView}
          onClose={() => setShowSaveModal(false)}
        />
      )}
    </main>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-lg shadow-sm p-4 text-center">
      <div className="text-2xl font-bold text-slate-800">{value}</div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
    </div>
  );
}

function BarList({ items }: { items: { label: string; value: number }[] }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="bg-white rounded-lg shadow-sm p-4 space-y-2">
      {items.length === 0 && <p className="text-sm text-slate-400">No data yet.</p>}
      {items.map((item) => (
        <div key={item.label}>
          <div className="flex justify-between text-xs text-slate-600 mb-1">
            <span>{item.label}</span>
            <span>{item.value.toLocaleString("en-IN")}</span>
          </div>
          <div className="w-full bg-slate-100 rounded h-2">
            <div
              className="bg-slate-800 h-2 rounded"
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function SalesReport({ data }: { data: ReportData }) {
  const funnel = data.funnel ?? {};
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card label="Leads" value={funnel.leads ?? 0} />
        <Card label="Sales Orders" value={funnel.sales_orders ?? 0} />
        <Card label="Win Rate" value={data.win_rate_pct != null ? `${data.win_rate_pct}%` : "—"} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Monthly Revenue</h3>
        <BarList items={(data.monthly_revenue ?? []).map((r: ReportData) => ({ label: r.month, value: r.total }))} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Top Products</h3>
        <BarList items={(data.top_products ?? []).map((p: ReportData) => ({ label: p.name, value: p.revenue }))} />
      </div>
    </>
  );
}

function FinanceReport({ data }: { data: ReportData }) {
  const totalRevenue = data.total_revenue ?? 0;
  const totalExpense = data.total_expense ?? 0;
  const netProfit = data.net_profit ?? 0;
  const monthly = data.monthly_revenue_expense ?? [];
  const aging = data.accounts_receivable_aging ?? {};
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card label="Revenue" value={`₹${totalRevenue.toLocaleString("en-IN")}`} />
        <Card label="Expense" value={`₹${totalExpense.toLocaleString("en-IN")}`} />
        <Card label="Net Profit" value={`₹${netProfit.toLocaleString("en-IN")}`} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Monthly Revenue vs Expense</h3>
        <div className="bg-white rounded-lg shadow-sm p-4 space-y-3">
          {monthly.length === 0 && <p className="text-sm text-slate-400">No data yet.</p>}
          {monthly.map((m: ReportData) => (
            <div key={m.month} className="text-xs">
              <p className="text-slate-600 mb-1">{m.month}</p>
              <div className="flex gap-1 items-center mb-0.5">
                <span className="w-14 text-slate-500">Revenue</span>
                <div className="flex-1 bg-slate-100 rounded h-2">
                  <div className="bg-emerald-600 h-2 rounded" style={{ width: `${Math.min(100, (m.revenue / (Math.max(m.revenue, m.expense, 1))) * 100)}%` }} />
                </div>
                <span className="w-20 text-right">₹{m.revenue.toLocaleString("en-IN")}</span>
              </div>
              <div className="flex gap-1 items-center">
                <span className="w-14 text-slate-500">Expense</span>
                <div className="flex-1 bg-slate-100 rounded h-2">
                  <div className="bg-rose-500 h-2 rounded" style={{ width: `${Math.min(100, (m.expense / (Math.max(m.revenue, m.expense, 1))) * 100)}%` }} />
                </div>
                <span className="w-20 text-right">₹{m.expense.toLocaleString("en-IN")}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">
          Accounts Receivable Aging ({data.unpaid_invoice_count ?? 0} unpaid)
        </h3>
        <BarList
          items={[
            { label: "0–30 days", value: aging["0_30"] ?? 0 },
            { label: "31–60 days", value: aging["31_60"] ?? 0 },
            { label: "61–90 days", value: aging["61_90"] ?? 0 },
            { label: "90+ days", value: aging["90_plus"] ?? 0 },
          ]}
        />
      </div>
    </>
  );
}

function InventoryReport({ data }: { data: ReportData }) {
  const lowStockItems = data.low_stock_items ?? [];
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card label="Total Products" value={data.total_products ?? 0} />
        <Card label="Stock Valuation" value={`₹${(data.stock_valuation ?? 0).toLocaleString("en-IN")}`} />
        <Card label="Low Stock Items" value={data.low_stock_count ?? 0} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Low Stock Items</h3>
        <div className="bg-white rounded-lg shadow-sm divide-y">
          {lowStockItems.length === 0 && <p className="p-3 text-sm text-slate-400">Nothing below reorder level. 🎉</p>}
          {lowStockItems.map((item: ReportData, i: number) => (
            <div key={i} className="p-3 flex justify-between text-sm">
              <span className="text-slate-800">{item.name} {item.sku ? `(${item.sku})` : ""}</span>
              <span className="text-amber-600">{item.quantity} / reorder at {item.reorder_level}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function ProcurementReport({ data }: { data: ReportData }) {
  const spendByVendor = data.spend_by_vendor ?? [];
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card label="Total Spend" value={`₹${(data.total_spend ?? 0).toLocaleString("en-IN")}`} />
        <Card label="Vendors" value={spendByVendor.length} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Spend by Vendor</h3>
        <BarList items={spendByVendor.map((v: ReportData) => ({ label: v.vendor, value: v.spend }))} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">PO Status Breakdown</h3>
        <BarList
          items={Object.entries(data.status_breakdown ?? {}).map(([label, value]) => ({
            label,
            value: value as number,
          }))}
        />
      </div>
    </>
  );
}

function HrReport({ data }: { data: ReportData }) {
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card label="Active Employees" value={data.active_employees ?? 0} />
        <Card label="Pending Leave Requests" value={data.pending_leave_requests ?? 0} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Headcount by Department</h3>
        <BarList items={(data.headcount_by_department ?? []).map((d: ReportData) => ({ label: d.department, value: d.count }))} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Payroll Cost by Month</h3>
        <BarList items={(data.payroll_cost_by_month ?? []).map((p: ReportData) => ({ label: p.month, value: p.total }))} />
      </div>
    </>
  );
}

function CrmReport({ data }: { data: ReportData }) {
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card label="Lead Conversion" value={data.lead_conversion_pct != null ? `${data.lead_conversion_pct}%` : "—"} />
        <Card label="Pipeline Stages" value={Object.keys(data.opportunities_by_stage ?? {}).length} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Leads by Status</h3>
        <BarList
          items={Object.entries(data.leads_by_status ?? {}).map(([label, value]) => ({ label, value: value as number }))}
        />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Pipeline Value by Stage</h3>
        <BarList
          items={Object.entries(data.pipeline_value_by_stage ?? {}).map(([label, value]) => ({
            label,
            value: value as number,
          }))}
        />
      </div>
    </>
  );
}

function ProjectsReport({ data }: { data: ReportData }) {
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card label="Open Tasks" value={data.open_tasks ?? 0} />
        <Card label="Project Statuses" value={Object.keys(data.projects_by_status ?? {}).length} />
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 mb-2 text-sm">Projects by Status</h3>
        <BarList
          items={Object.entries(data.projects_by_status ?? {}).map(([label, value]) => ({
            label,
            value: value as number,
          }))}
        />
      </div>
    </>
  );
}
