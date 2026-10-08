"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Download, IndianRupee, FileText, Handshake, Truck, PackageCheck, ClipboardList } from "lucide-react";
import { apiRequest, apiBlob, saveBlob, getToken } from "@/lib/api";
import { useCurrentUser } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { VerificationBanner } from "@/components/VerificationBanner";
import { SkeletonStatTile, SkeletonCard } from "@/components/Skeleton";
import { PullToRefresh } from "@/components/PullToRefresh";
import { StatusPill } from "@/components/StatusPill";
import { BreakdownPieChart } from "@/components/charts/BreakdownPieChart";
import { IncomeBars } from "@/components/charts/IncomeBars";
import { Card } from "@/components/ui";

type Home = {
  period: "today" | "week" | "month";
  from: string; to: string; today: string; scope: "organization" | "mine";
  income: { total: number; payments: number } | null;
  quotes: { processed: number; accepted: number; value: number } | null;
  purchase_orders: { raised: number; value: number; awaiting_approval: number } | null;
  deals: { new: number; value: number } | null;
  deliveries: { delivered: number; awaiting_delivery: number } | null;
  works: { assigned: number; completed: number; pending: number } | null;
  work_status: { key: string; label: string; color: string; count: number }[];
  recent_works: { id: string; work_number: string; client_name: string; domain: string | null; status_label: string; status_color: string; quotation_amount: string; handling_department: string | null }[];
  tasks: { todo: number; in_progress: number; done: number } | null;
  priority_tasks: { id: string; title: string; project: string; priority: string; status: string; due_date: string | null }[];
  projects: { id: string; name: string; status: string; end_date: string | null; tasks: number; done: number; progress: number }[];
  income_trend: { date: string; label: string; amount: number }[];
};

type Summary = {
  unpaid_invoices: number; low_stock_products: number; pending_purchase_orders: number;
  pending_leave_requests: number; pending_approvals: number; employees: number;
};

const PERIODS = [["today", "Today"], ["week", "This week"], ["month", "This month"]] as const;
const inr = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function DashboardPage() {
  const router = useRouter();
  const { showToast } = useToast();
  const { user } = useCurrentUser();
  const [period, setPeriod] = useState<Home["period"]>("today");
  const [home, setHome] = useState<Home | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);

  const load = useCallback((): Promise<void> => {
    return apiRequest<Home>(`/api/dashboard/home?period=${period}`, { auth: true })
      .then((h) => { setHome(h); setError(null); })
      .catch((e) => setError(e.message));
  }, [period]);

  useEffect(() => {
    if (!getToken()) { router.push("/login"); return; }
    apiRequest<Summary>("/api/dashboard/summary", { auth: true }).then(setSummary).catch(() => {});
  }, [router]);

  // reload when the period changes, every minute, and when the tab comes back (so "today" is always today)
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    const vis = () => { if (document.visibilityState === "visible") load(); };
    document.addEventListener("visibilitychange", vis);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", vis); };
  }, [load]);

  async function download(kind: "daily" | "weekly" | "monthly", format: "pdf" | "csv") {
    setMenu(false);
    try {
      const blob = await apiBlob(`/api/dashboard/report?kind=${kind}&format=${format}`);
      saveBlob(blob, `${kind}_report_${new Date().toISOString().slice(0, 10)}.${format}`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Could not download the report.", "error");
    }
  }

  if (error && !home) return <p className="p-8 text-red-600" role="alert">{error}</p>;

  const firstName = (user?.name || "").split(" ")[0];
  const workPie = home?.works ? [
    { label: "Assigned", value: home.works.assigned },
    { label: "Completed", value: home.works.completed },
    { label: "Pending", value: home.works.pending },
  ] : [];
  const statusPie = (home?.work_status ?? []).map((s) => ({ label: s.label, value: s.count }));

  return (
    <main className="p-4 sm:p-8 max-w-7xl">
      <PullToRefresh onRefresh={load}>
        {user && !user.email_verified && <VerificationBanner email={user.email} />}

        <div className="flex justify-between items-start gap-4 flex-wrap mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-800 dark:text-white" data-testid="home-title">
              {greeting()}{firstName ? `, ${firstName}` : ""}
            </h1>
            <p className="text-sm text-slate-500 dark:text-zinc-400 mt-1">
              {user?.org_name ? `${user.org_name} · ` : ""}
              {home ? (home.from === home.to ? new Date(home.from + "T00:00:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
                : `${home.from} to ${home.to}`) : ""}
              {home?.scope === "mine" ? " · showing your work" : ""}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <div role="tablist" aria-label="Period" className="inline-flex rounded-lg border border-slate-300 dark:border-zinc-700 overflow-hidden">
              {PERIODS.map(([k, label]) => (
                <button key={k} role="tab" aria-selected={period === k} onClick={() => setPeriod(k)}
                  className={`px-3 py-1.5 text-sm ${period === k ? "bg-slate-800 text-white dark:bg-zinc-100 dark:text-zinc-950" : "bg-white dark:bg-zinc-900 text-slate-600 dark:text-zinc-300 hover:bg-slate-50 dark:hover:bg-zinc-800"}`}>
                  {label}
                </button>
              ))}
            </div>
            {user?.is_admin && (
              <div className="relative">
                <button onClick={() => setMenu((m) => !m)} aria-haspopup="menu" aria-expanded={menu} data-testid="report-menu-button"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-800">
                  <Download size={15} /> Download report
                </button>
                {menu && (
                  <div role="menu" className="absolute right-0 mt-2 w-56 rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-lg py-1 z-40">
                    {(["daily", "weekly", "monthly"] as const).map((k) => (
                      <div key={k} className="px-3 py-1.5 flex items-center justify-between text-sm text-slate-700 dark:text-zinc-200">
                        <span className="capitalize">{k}</span>
                        <span className="flex gap-1">
                          <button role="menuitem" onClick={() => download(k, "pdf")} data-testid={`dl-${k}-pdf`} className="px-2 py-0.5 rounded border border-slate-300 dark:border-zinc-700 text-xs hover:bg-slate-100 dark:hover:bg-zinc-800">PDF</button>
                          <button role="menuitem" onClick={() => download(k, "csv")} data-testid={`dl-${k}-csv`} className="px-2 py-0.5 rounded border border-slate-300 dark:border-zinc-700 text-xs hover:bg-slate-100 dark:hover:bg-zinc-800">CSV</button>
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {!home ? (
          <div className="grid grid-cols-2 lg:grid-cols-6 gap-4"><>{Array.from({ length: 6 }).map((_, i) => <SkeletonStatTile key={i} />)}</></div>
        ) : (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-6 gap-4 mb-6" data-testid="home-stats">
              {home.income && <Stat icon={IndianRupee} label="Income" value={inr(home.income.total)} hint={`${home.income.payments} payment${home.income.payments === 1 ? "" : "s"}`} />}
              {home.quotes && <Stat icon={FileText} label="Quotes processed" value={String(home.quotes.processed)} hint={`${home.quotes.accepted} accepted`} />}
              {home.deals && <Stat icon={Handshake} label="Deals" value={String(home.deals.new)} hint={inr(home.deals.value)} />}
              {home.purchase_orders && <Stat icon={Truck} label="PO raised" value={String(home.purchase_orders.raised)} hint={`${home.purchase_orders.awaiting_approval} awaiting approval`} />}
              {home.deliveries && <Stat icon={PackageCheck} label="Deliveries" value={String(home.deliveries.delivered)} hint={`${home.deliveries.awaiting_delivery} ready to deliver`} />}
              {home.works && <Stat icon={ClipboardList} label="Works pending" value={String(home.works.pending)} hint={`${home.works.assigned} new · ${home.works.completed} done`} />}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
              {home.income && (
                <Card className="p-5 lg:col-span-2">
                  <h2 className="font-semibold text-slate-800 dark:text-white mb-1">Income, last 7 days</h2>
                  <p className="text-xs text-slate-500 dark:text-zinc-400 mb-3">Payments received against works and invoices.</p>
                  <IncomeBars data={home.income_trend} />
                </Card>
              )}
              {home.works && (
                <Card className="p-5">
                  <h2 className="font-semibold text-slate-800 dark:text-white mb-1">Works, {period === "today" ? "today" : period === "week" ? "this week" : "this month"}</h2>
                  <p className="text-xs text-slate-500 dark:text-zinc-400">Assigned · completed · pending</p>
                  <BreakdownPieChart items={workPie} />
                </Card>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
              {home.works && (
                <Card className="p-5">
                  <h2 className="font-semibold text-slate-800 dark:text-white mb-1">Where works stand</h2>
                  <p className="text-xs text-slate-500 dark:text-zinc-400">Every work by its current status.</p>
                  <BreakdownPieChart items={statusPie} />
                </Card>
              )}
              {home.tasks && (
                <Card className="p-5 lg:col-span-2">
                  <div className="flex justify-between items-center mb-3">
                    <h2 className="font-semibold text-slate-800 dark:text-white">Priority tasks</h2>
                    <span className="text-xs text-slate-500 dark:text-zinc-400">{home.tasks.todo} to do · {home.tasks.in_progress} in progress · {home.tasks.done} done</span>
                  </div>
                  {home.priority_tasks.length === 0 ? <p className="text-sm text-slate-400 dark:text-zinc-500">Nothing open. 🎉</p> : (
                    <ul className="divide-y divide-slate-100 dark:divide-zinc-800">
                      {home.priority_tasks.map((t) => (
                        <li key={t.id} className="py-2 flex items-center justify-between gap-3 text-sm">
                          <div className="min-w-0">
                            <p className="text-slate-800 dark:text-white truncate">{t.title}</p>
                            <p className="text-xs text-slate-500 dark:text-zinc-400 truncate">{t.project}{t.due_date ? ` · due ${t.due_date}` : ""}</p>
                          </div>
                          <span className={`text-xs rounded-full px-2 py-0.5 ${t.priority === "high" ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300" : t.priority === "medium" ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300" : "bg-slate-100 text-slate-700 dark:bg-zinc-800 dark:text-zinc-300"}`}>{t.priority}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
              {home.projects.length > 0 && (
                <Card className="p-5">
                  <div className="flex justify-between items-center mb-3">
                    <h2 className="font-semibold text-slate-800 dark:text-white">Projects</h2>
                    <Link href="/projects" className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">Open Projects</Link>
                  </div>
                  <table className="w-full text-sm">
                    <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-400"><th className="pb-2 font-medium">Project</th><th className="pb-2 font-medium">Progress</th><th className="pb-2 font-medium text-right">Tasks</th></tr></thead>
                    <tbody>
                      {home.projects.map((p) => (
                        <tr key={p.id} className="border-t border-slate-100 dark:border-zinc-800">
                          <td className="py-2 pr-3 text-slate-800 dark:text-white">{p.name}</td>
                          <td className="py-2 pr-3 w-1/2">
                            <div className="h-2 rounded-full bg-slate-100 dark:bg-zinc-800 overflow-hidden"><div className="h-full bg-indigo-500" style={{ width: `${p.progress}%` }} /></div>
                          </td>
                          <td className="py-2 text-right text-slate-600 dark:text-zinc-300">{p.done}/{p.tasks}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}
              {home.recent_works.length > 0 && (
                <Card className="p-5">
                  <div className="flex justify-between items-center mb-3">
                    <h2 className="font-semibold text-slate-800 dark:text-white">Open works</h2>
                    <Link href="/workpage" className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">Open Workpage</Link>
                  </div>
                  <ul className="divide-y divide-slate-100 dark:divide-zinc-800">
                    {home.recent_works.map((w) => (
                      <li key={w.id} className="py-2 flex items-center justify-between gap-3 text-sm">
                        <Link href={`/workpage/${w.id}`} className="min-w-0 hover:underline">
                          <p className="text-slate-800 dark:text-white truncate">{w.client_name}</p>
                          <p className="text-xs text-slate-500 dark:text-zinc-400 truncate">{w.work_number}{w.handling_department ? ` · ${w.handling_department}` : ""}</p>
                        </Link>
                        <StatusPill label={w.status_label} color={w.status_color} />
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </div>
          </>
        )}

        {summary && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3" data-testid="glance">
            <Glance label="Unpaid invoices" value={summary.unpaid_invoices} />
            <Glance label="Low stock items" value={summary.low_stock_products} />
            <Glance label="POs awaiting delivery" value={summary.pending_purchase_orders} />
            <Glance label="Leave requests" value={summary.pending_leave_requests} />
            <Glance label="Pending approvals" value={summary.pending_approvals} />
            <Glance label="Employees" value={summary.employees} />
          </div>
        )}
        {!home && !summary && <SkeletonCard />}
      </PullToRefresh>
    </main>
  );
}

function Stat({ icon: Icon, label, value, hint }: { icon: typeof IndianRupee; label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-slate-500 dark:text-zinc-400"><span className="text-xs">{label}</span><Icon size={15} /></div>
      <div className="text-2xl font-bold text-slate-800 dark:text-white mt-1" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>{value}</div>
      {hint && <div className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">{hint}</div>}
    </Card>
  );
}

function Glance({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2">
      <div className="text-lg font-semibold text-slate-800 dark:text-white">{value}</div>
      <div className="text-xs text-slate-500 dark:text-zinc-400">{label}</div>
    </div>
  );
}
