"use client";

import { useEffect, useState } from "react";
import { apiRequest, apiDownload } from "@/lib/api";
import { PromptModal } from "@/components/Modal";
import { PageHeader } from "@/components/ui";
import { SkeletonCard } from "@/components/Skeleton";
import { TrendLineChart } from "@/components/charts/TrendLineChart";
import { ComparisonBarChart } from "@/components/charts/ComparisonBarChart";
import { BreakdownPieChart } from "@/components/charts/BreakdownPieChart";

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

// eslint-disable-next-line
type ReportData = any;

export default function ReportsPage() {
  const [activeTab, setActiveTab] = useState<ReportModule>("sales");
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedReports, setSavedReports] = useState<SavedReport[]>([]);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [subscribed, setSubscribed] = useState<boolean | null>(null); // null = not loaded yet
  const [subscribing, setSubscribing] = useState(false);

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

  useEffect(() => {
    apiRequest<{ subscribed: boolean }>("/api/reports/subscription", { auth: true })
      .then((r) => setSubscribed(r.subscribed))
      .catch(() => setSubscribed(false)); // fail closed - don't claim a subscription state we couldn't confirm
  }, []);

  async function handleToggleSubscription() {
    setSubscribing(true);
    try {
      if (subscribed) {
        await apiRequest("/api/reports/subscription", { method: "DELETE", auth: true });
        setSubscribed(false);
      } else {
        await apiRequest("/api/reports/subscription", { method: "POST", auth: true });
        setSubscribed(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update subscription");
    } finally {
      setSubscribing(false);
    }
  }

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
      <PageHeader
        title="Reports & Analytics"
        actions={
          subscribed !== null && (
            <button
              onClick={handleToggleSubscription}
              disabled={subscribing}
              className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
                subscribed
                  ? "bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300 hover:bg-slate-200 dark:hover:bg-zinc-700"
                  : "bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 hover:bg-slate-700 dark:hover:bg-zinc-300"
              }`}
              title={subscribed ? "You receive the weekly summary email — click to stop" : "Get a weekly summary emailed to you"}
            >
              {subscribing ? "…" : subscribed ? "✓ Weekly digest on" : "Get weekly digest email"}
            </button>
          )
        }
      />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {/* Tabs */}
      <div className="flex gap-2 mb-6 flex-wrap">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab.key ? "bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900" : "bg-white dark:bg-zinc-900 text-slate-600 dark:text-zinc-300 shadow-sm hover:bg-slate-100 dark:hover:bg-zinc-800"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex gap-3 mb-6">
        <button
          onClick={handleExport}
          className="text-sm bg-white dark:bg-zinc-900 shadow-sm rounded-lg px-3 py-1.5 text-slate-700 dark:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800"
        >
          ⬇ Export CSV
        </button>
        <button
          onClick={() => setShowSaveModal(true)}
          className="text-sm bg-white dark:bg-zinc-900 shadow-sm rounded-lg px-3 py-1.5 text-slate-700 dark:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800"
        >
          ★ Save this view
        </button>
      </div>

      {loading && (
        <div className="grid md:grid-cols-3 gap-6 mb-10">
          <div className="md:col-span-2 space-y-3">
            <SkeletonCard />
            <SkeletonCard />
          </div>
          <SkeletonCard />
        </div>
      )}

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
            <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Saved Reports</h2>
            <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm divide-y">
              {savedReports.length === 0 && (
                <p className="p-3 text-sm text-slate-400 dark:text-zinc-500">No saved views yet.</p>
              )}
              {savedReports.map((r) => (
                <div key={r.id} className="p-3 flex justify-between items-center text-sm">
                  <div>
                    <p className="text-slate-800 dark:text-white">{r.name}</p>
                    <p className="text-xs text-slate-400 dark:text-zinc-500">{r.module}</p>
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
    <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4 text-center">
      <div className="text-2xl font-bold text-slate-800 dark:text-white">{value}</div>
      <div className="text-xs text-slate-500 dark:text-zinc-500 mt-1">{label}</div>
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
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Monthly Revenue</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <TrendLineChart
            data={data.monthly_revenue ?? []}
            xKey="month"
            valuePrefix="₹"
            series={[{ key: "total", label: "Revenue", color: { light: "#1e293b", dark: "#e4e4e7" } }]}
          />
        </div>
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Top Products</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <ComparisonBarChart
            items={(data.top_products ?? []).map((p: ReportData) => ({ label: p.name, value: p.revenue }))}
            valuePrefix="₹"
          />
        </div>
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
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Monthly Revenue vs Expense</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <TrendLineChart
            data={monthly}
            xKey="month"
            valuePrefix="₹"
            series={[
              { key: "revenue", label: "Revenue", color: { light: "#059669", dark: "#34d399" } },
              { key: "expense", label: "Expense", color: { light: "#e11d48", dark: "#fb7185" } },
            ]}
          />
        </div>
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">
          Accounts Receivable Aging ({data.unpaid_invoice_count ?? 0} unpaid)
        </h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <ComparisonBarChart
            items={[
              { label: "0–30 days", value: aging["0_30"] ?? 0 },
              { label: "31–60 days", value: aging["31_60"] ?? 0 },
              { label: "61–90 days", value: aging["61_90"] ?? 0 },
              { label: "90+ days", value: aging["90_plus"] ?? 0 },
            ]}
            valuePrefix="₹"
          />
        </div>
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
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Low Stock Items</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm divide-y">
          {lowStockItems.length === 0 && <p className="p-3 text-sm text-slate-400 dark:text-zinc-500">Nothing below reorder level. 🎉</p>}
          {lowStockItems.map((item: ReportData, i: number) => (
            <div key={i} className="p-3 flex justify-between text-sm">
              <span className="text-slate-800 dark:text-white">{item.name} {item.sku ? `(${item.sku})` : ""}</span>
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
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Spend by Vendor</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <ComparisonBarChart
            items={spendByVendor.map((v: ReportData) => ({ label: v.vendor, value: v.spend }))}
            valuePrefix="₹"
          />
        </div>
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">PO Status Breakdown</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <BreakdownPieChart
            items={Object.entries(data.status_breakdown ?? {}).map(([label, value]) => ({
              label,
              value: value as number,
            }))}
          />
        </div>
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
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Headcount by Department</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <ComparisonBarChart
            items={(data.headcount_by_department ?? []).map((d: ReportData) => ({ label: d.department, value: d.count }))}
          />
        </div>
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Payroll Cost by Month</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <TrendLineChart
            data={data.payroll_cost_by_month ?? []}
            xKey="month"
            valuePrefix="₹"
            series={[{ key: "total", label: "Payroll Cost", color: { light: "#1e293b", dark: "#e4e4e7" } }]}
          />
        </div>
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
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Leads by Status</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <BreakdownPieChart
            items={Object.entries(data.leads_by_status ?? {}).map(([label, value]) => ({ label, value: value as number }))}
          />
        </div>
      </div>
      <div>
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Pipeline Value by Stage</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <ComparisonBarChart
            items={Object.entries(data.pipeline_value_by_stage ?? {}).map(([label, value]) => ({
              label,
              value: value as number,
            }))}
            valuePrefix="₹"
          />
        </div>
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
        <h3 className="font-semibold text-slate-700 dark:text-zinc-200 mb-2 text-sm">Projects by Status</h3>
        <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-4">
          <BreakdownPieChart
            items={Object.entries(data.projects_by_status ?? {}).map(([label, value]) => ({
              label,
              value: value as number,
            }))}
          />
        </div>
      </div>
    </>
  );
}
