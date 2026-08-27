"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { apiRequest, clearToken, getToken } from "@/lib/api";
import { NotificationBell } from "@/components/NotificationBell";
import { VerificationBanner } from "@/components/VerificationBanner";
import { GlobalSearch } from "@/components/GlobalSearch";
import { SkeletonStatTile, SkeletonCard } from "@/components/Skeleton";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  Settings2, Shield, ScrollText, LogOut, Palette,
  Users2, ShoppingCart, Wallet, Package, Truck, UserRound, FolderKanban, FileText, BarChart3,
} from "lucide-react";

type CurrentUser = {
  id: string;
  name: string;
  email: string;
  org_id: string;
  status: string;
  email_verified: boolean;
};

type Summary = {
  leads: number;
  open_opportunities: number;
  quotations: number;
  sales_orders: number;
  unpaid_invoices: number;
  low_stock_products: number;
  pending_purchase_orders: number;
  employees: number;
  pending_leave_requests: number;
  active_projects: number;
  open_tasks: number;
  pending_approvals: number;
  saved_reports: number;
};

const LIVE_MODULES: { name: string; href: string; stat?: keyof Summary; label?: string; icon: typeof Users2 }[] = [
  { name: "CRM", href: "/crm", stat: "leads", label: "leads", icon: Users2 },
  { name: "Sales", href: "/sales", stat: "sales_orders", label: "orders", icon: ShoppingCart },
  { name: "Finance", href: "/finance", stat: "unpaid_invoices", label: "unpaid", icon: Wallet },
  { name: "Inventory", href: "/inventory", stat: "low_stock_products", label: "low stock", icon: Package },
  { name: "Procurement", href: "/procurement", stat: "pending_purchase_orders", label: "pending", icon: Truck },
  { name: "HR", href: "/hr", stat: "pending_leave_requests", label: "leave reqs", icon: UserRound },
  { name: "Projects", href: "/projects", stat: "open_tasks", label: "open tasks", icon: FolderKanban },
  { name: "Documents", href: "/documents", stat: "pending_approvals", label: "approvals", icon: FileText },
  { name: "Reports", href: "/reports", stat: "saved_reports", label: "saved", icon: BarChart3 },
];

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }

    apiRequest<CurrentUser>("/api/auth/me", { auth: true })
      .then(setUser)
      .catch((err) => {
        setError(err.message);
        clearToken();
        router.push("/login");
      });

    apiRequest<Summary>("/api/dashboard/summary", { auth: true }).then(setSummary).catch(() => {});
  }, [router]);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  if (error) return <p className="p-8 text-red-600">{error}</p>;
  if (!user) {
    return (
      <main className="min-h-screen p-8">
        <div className="h-8 w-40 bg-slate-200 rounded animate-pulse mb-8" />
        <SkeletonCard />
        <div className="grid grid-cols-2 md:grid-cols-7 gap-4 mt-8 max-w-5xl">
          {Array.from({ length: 7 }).map((_, i) => <SkeletonStatTile key={i} />)}
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-8">
      <div className="flex justify-between items-center mb-8 gap-4 flex-wrap">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Dashboard</h1>
        <GlobalSearch />
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <NotificationBell />
            <Link
              href="/settings/custom-fields"
              className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-800 dark:hover:text-slate-100 transition-colors"
            >
              <Settings2 size={16} /> Custom Fields
            </Link>
            <Link
              href="/settings/roles"
              className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-800 dark:hover:text-slate-100 transition-colors"
            >
              <Shield size={16} /> Roles & Permissions
            </Link>
            <Link
              href="/settings/audit-log"
              className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-800 dark:hover:text-slate-100 transition-colors"
            >
              <ScrollText size={16} /> Audit Log
            </Link>
            <Link
              href="/settings/appearance"
              className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-800 dark:hover:text-slate-100 transition-colors"
            >
              <Palette size={16} /> Appearance
            </Link>
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-800 dark:hover:text-slate-100 transition-colors"
            >
              <LogOut size={16} /> Log out
            </button>
          </div>
        </div>

        {user && !user.email_verified && <VerificationBanner email={user.email} />}

        <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm p-6 max-w-md mb-8">
        <p className="text-slate-500 text-sm mb-1">Logged in as</p>
        <p className="text-lg font-medium text-slate-800">{user.name}</p>
        <p className="text-slate-500">{user.email}</p>
        <hr className="my-4" />
        <p className="text-xs text-slate-400">Organization ID: {user.org_id}</p>
        <p className="text-xs text-slate-400">Status: {user.status}</p>
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-7 gap-4 mb-8 max-w-5xl">
          <SummaryTile label="Leads" value={summary.leads} />
          <SummaryTile label="Open Opportunities" value={summary.open_opportunities} />
          <SummaryTile label="Quotations" value={summary.quotations} />
          <SummaryTile label="Sales Orders" value={summary.sales_orders} />
          <SummaryTile label="Unpaid Invoices" value={summary.unpaid_invoices} />
          <SummaryTile label="Low Stock" value={summary.low_stock_products} />
          <SummaryTile label="Pending POs" value={summary.pending_purchase_orders} />
          <SummaryTile label="Employees" value={summary.employees} />
          <SummaryTile label="Pending Leave" value={summary.pending_leave_requests} />
          <SummaryTile label="Active Projects" value={summary.active_projects} />
          <SummaryTile label="Open Tasks" value={summary.open_tasks} />
          <SummaryTile label="Pending Approvals" value={summary.pending_approvals} />
          <SummaryTile label="Saved Reports" value={summary.saved_reports} />
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 max-w-3xl">
        {LIVE_MODULES.map((mod) => {
          const Icon = mod.icon;
          return (
            <Link
              key={mod.name}
              href={mod.href}
              className="bg-white rounded-lg shadow-sm p-4 text-center hover:shadow-md hover:-translate-y-0.5 active:translate-y-0 active:shadow-sm transition-all duration-150"
            >
              <Icon size={20} className="mx-auto mb-1.5 text-slate-400" />
              <span className="text-slate-800 font-medium">{mod.name}</span>
              {summary && mod.stat && (
                <div className="text-xs mt-1 text-slate-500">
                  {summary[mod.stat]} {mod.label}
                </div>
              )}
            </Link>
          );
        })}
      </div>
      </main>
  );
}

function SummaryTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-white rounded-lg shadow-sm p-4 text-center">
      <div className="text-2xl font-bold text-slate-800">{value}</div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
    </div>
  );
}
