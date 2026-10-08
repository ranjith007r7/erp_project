"use client";

/**
 * The frame every signed-in page lives in:
 *   - a collapsible LEFT sidebar with the modules (so nobody has to go back to the dashboard
 *     to switch module), and
 *   - a top bar with search, theme, notifications and the RIGHT-hand profile menu
 *     (My Profile, Organization, Roles, Audit Log, Appearance, Danger Zone, Sign out).
 *
 * It is mounted once in app/layout.tsx and shows itself only on signed-in routes; the
 * sign-in / sign-up / reset pages are rendered bare. The sidebar's open/closed choice is
 * remembered per browser (nice-to-have only: it works without storage).
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard, Users2, ShoppingCart, Wallet, Package, Truck, UserRound, FolderKanban, FileText,
  BarChart3, Sparkles, ClipboardList, PanelLeftClose, PanelLeftOpen, Menu, X,
} from "lucide-react";
import { apiRequest, clearToken, getToken } from "@/lib/api";
import { BRAND } from "@/lib/brand";
import { GlobalSearch } from "@/components/GlobalSearch";
import { ThemeToggle } from "@/components/ThemeToggle";
import { NotificationBell } from "@/components/NotificationBell";
import { ProfileMenu } from "@/components/ProfileMenu";

export type CurrentUser = {
  id: string;
  name: string;
  email: string;
  org_id: string;
  status: string;
  email_verified: boolean;
  is_admin?: boolean;
  role_name?: string | null;
  org_name?: string | null;
  permissions?: string[];
};

type Ctx = { user: CurrentUser | null; can: (module: string, action?: string) => boolean; signOut: () => void };
const UserContext = createContext<Ctx>({ user: null, can: () => false, signOut: () => {} });
export const useCurrentUser = () => useContext(UserContext);

const PUBLIC_PREFIXES = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email", "/accept-invite"];
const isPublic = (path: string) => path === "/" || PUBLIC_PREFIXES.some((p) => path === p || path.startsWith(p + "/"));

const NAV: { name: string; href: string; module: string; icon: typeof Users2 }[] = [
  { name: "Home", href: "/dashboard", module: "dashboard", icon: LayoutDashboard },
  { name: "CRM", href: "/crm", module: "crm", icon: Users2 },
  { name: "Sales", href: "/sales", module: "sales", icon: ShoppingCart },
  { name: "Workpage", href: "/workpage", module: "workpage", icon: ClipboardList },
  { name: "Procurement", href: "/procurement", module: "procurement", icon: Truck },
  { name: "Inventory", href: "/inventory", module: "inventory", icon: Package },
  { name: "Finance", href: "/finance", module: "finance", icon: Wallet },
  { name: "HR", href: "/hr", module: "hr", icon: UserRound },
  { name: "Projects", href: "/projects", module: "projects", icon: FolderKanban },
  { name: "Documents", href: "/documents", module: "documents", icon: FileText },
  { name: "Reports", href: "/reports", module: "reports", icon: BarChart3 },
  { name: "Ask Data", href: "/intelligence", module: "intelligence", icon: Sparkles },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const publicPage = isPublic(pathname);

  // remember the sidebar choice (storage may be blocked: ignore)
  useEffect(() => {
    try { setCollapsed(localStorage.getItem("erp_sidebar") === "closed"); } catch { /* ignore */ }
  }, []);
  function toggleCollapsed() {
    setCollapsed((c) => {
      try { localStorage.setItem("erp_sidebar", c ? "open" : "closed"); } catch { /* ignore */ }
      return !c;
    });
  }

  useEffect(() => { setMobileOpen(false); }, [pathname]);

  useEffect(() => {
    if (publicPage) { setUser(null); setSignedIn(false); return; }
    if (!getToken()) { setSignedIn(false); return; }
    setSignedIn(true);
    if (user) return;
    apiRequest<CurrentUser>("/api/auth/me", { auth: true })
      .then(setUser)
      .catch(() => { clearToken(); setSignedIn(false); router.push("/login"); });
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  function signOut() {
    clearToken();
    setUser(null);
    setSignedIn(false);
    router.push("/login");
  }
  const perms = new Set(user?.permissions ?? []);
  const can = (module: string, action = "view") => !user ? false : (user.is_admin || perms.has(`${module}:${action}`));
  const ctx: Ctx = { user, can, signOut };

  if (publicPage || signedIn === false) return <UserContext.Provider value={ctx}>{children}</UserContext.Provider>;

  const items = user ? NAV.filter((n) => can(n.module)) : [];   // until /me answers show placeholders, never links the person may not have
  const isActive = (href: string) => (href === "/dashboard" ? pathname === "/dashboard" : pathname === href || pathname.startsWith(href + "/"));

  const sidebar = (compact: boolean) => (
    <nav aria-label="Modules" className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
      {!user && Array.from({ length: 7 }).map((_, i) => <div key={i} className="h-9 rounded-lg bg-slate-100 dark:bg-zinc-800 animate-pulse" />)}
      {items.map((n) => {
        const Icon = n.icon;
        const active = isActive(n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            title={compact ? n.name : undefined}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${compact ? "justify-center px-2" : ""} ${
              active
                ? "bg-slate-800 text-white dark:bg-zinc-100 dark:text-zinc-950 font-medium"
                : "text-slate-600 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            <Icon size={18} className="shrink-0" />
            {!compact && <span className="truncate">{n.name}</span>}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <UserContext.Provider value={ctx}>
      <div className="min-h-screen flex">
        {/* desktop sidebar */}
        <aside
          data-testid="sidebar"
          data-collapsed={collapsed}
          className={`hidden md:flex flex-col sticky top-0 h-screen shrink-0 border-r border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 transition-[width] duration-200 ${collapsed ? "w-16" : "w-56"}`}
        >
          <div className={`h-14 flex items-center border-b border-slate-200 dark:border-zinc-800 ${collapsed ? "justify-center" : "px-4 justify-between"}`}>
            {!collapsed && <Link href="/dashboard" className="font-semibold text-slate-800 dark:text-white truncate">{BRAND.productName}</Link>}
            <button
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Open sidebar" : "Close sidebar"}
              aria-expanded={!collapsed}
              data-testid="sidebar-toggle"
              className="p-1.5 rounded-lg text-slate-500 dark:text-zinc-400 hover:bg-slate-100 dark:hover:bg-zinc-800"
            >
              {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
          </div>
          {sidebar(collapsed)}
        </aside>

        {/* mobile drawer */}
        {mobileOpen && (
          <div className="md:hidden fixed inset-0 z-40 flex">
            <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
            <aside className="relative w-64 max-w-[80%] flex flex-col bg-white dark:bg-zinc-950 border-r border-slate-200 dark:border-zinc-800">
              <div className="h-14 px-4 flex items-center justify-between border-b border-slate-200 dark:border-zinc-800">
                <span className="font-semibold text-slate-800 dark:text-white">{BRAND.productName}</span>
                <button onClick={() => setMobileOpen(false)} aria-label="Close menu" className="p-1.5 rounded-lg text-slate-500 dark:text-zinc-400 hover:bg-slate-100 dark:hover:bg-zinc-800"><X size={18} /></button>
              </div>
              {sidebar(false)}
            </aside>
          </div>
        )}

        <div className="flex-1 min-w-0 flex flex-col">
          <header className="sticky top-0 z-30 h-14 flex items-center gap-3 px-4 border-b border-slate-200 dark:border-zinc-800 bg-white/90 dark:bg-zinc-950/90 backdrop-blur">
            <button onClick={() => setMobileOpen(true)} aria-label="Open menu" className="md:hidden p-1.5 rounded-lg text-slate-600 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800"><Menu size={20} /></button>
            <div className="flex-1 min-w-0"><GlobalSearch /></div>
            <div className="flex items-center gap-1">
              <ThemeToggle />
              <NotificationBell />
              <ProfileMenu />
            </div>
          </header>
          <div className="flex-1 min-w-0">{children}</div>
        </div>
      </div>
    </UserContext.Provider>
  );
}
