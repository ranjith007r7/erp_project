"use client";

/** The right-hand avatar menu (GitHub style): who you are, your profile, settings, sign out. */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { UserCircle, CalendarDays, Building2, Settings2, Shield, ScrollText, Palette, TriangleAlert, LogOut, ChevronDown } from "lucide-react";
import { useCurrentUser } from "@/components/AppShell";

export function ProfileMenu() {
  const { user, can, signOut } = useCurrentUser();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function outside(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); }
    function esc(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", esc); };
  }, []);

  const initial = (user?.name || "?").trim().charAt(0).toUpperCase();
  const close = () => setOpen(false);
  const item = "flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 dark:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800";

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Open profile menu"
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="profile-menu-button"
        className="flex items-center gap-1 pl-1 pr-1.5 py-1 rounded-full hover:bg-slate-100 dark:hover:bg-zinc-800"
      >
        <span className="h-8 w-8 rounded-full bg-slate-800 dark:bg-zinc-100 text-white dark:text-zinc-950 grid place-items-center text-sm font-semibold">{initial}</span>
        <ChevronDown size={14} className="text-slate-500 dark:text-zinc-400" />
      </button>
      {open && (
        <div role="menu" data-testid="profile-menu" className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-lg py-1 z-50">
          <div className="px-3 py-3 border-b border-slate-200 dark:border-zinc-800">
            <p className="text-sm font-semibold text-slate-800 dark:text-white truncate">{user?.name ?? "…"}</p>
            <p className="text-xs text-slate-500 dark:text-zinc-400 truncate">{user?.email}</p>
            {user?.org_name && <p className="text-xs text-slate-500 dark:text-zinc-400 truncate mt-0.5" data-testid="org-name">{user.org_name}{user.role_name ? ` · ${user.role_name}` : ""}</p>}
          </div>
          <Link role="menuitem" href="/profile" onClick={close} className={item}><UserCircle size={16} /> My Profile</Link>
          <Link role="menuitem" href="/profile/leaves" onClick={close} className={item}><CalendarDays size={16} /> My Leaves</Link>
          <div className="my-1 border-t border-slate-200 dark:border-zinc-800" />
          <Link role="menuitem" href="/settings/organization" onClick={close} className={item}><Building2 size={16} /> Organization</Link>
          {can("custom_fields") && <Link role="menuitem" href="/settings/custom-fields" onClick={close} className={item}><Settings2 size={16} /> Custom Fields</Link>}
          {can("core") && <Link role="menuitem" href="/settings/roles" onClick={close} className={item}><Shield size={16} /> Roles & Permissions</Link>}
          {can("core") && <Link role="menuitem" href="/settings/audit-log" onClick={close} className={item}><ScrollText size={16} /> Audit Log</Link>}
          <Link role="menuitem" href="/settings/appearance" onClick={close} className={item}><Palette size={16} /> Appearance</Link>
          {user?.is_admin && (
            <Link role="menuitem" href="/settings/danger" onClick={close} className="flex items-center gap-2.5 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40"><TriangleAlert size={16} /> Danger Zone</Link>
          )}
          <div className="my-1 border-t border-slate-200 dark:border-zinc-800" />
          <button role="menuitem" onClick={() => { close(); signOut(); }} className={`${item} w-full text-left`} data-testid="sign-out"><LogOut size={16} /> Sign out</button>
        </div>
      )}
    </div>
  );
}
