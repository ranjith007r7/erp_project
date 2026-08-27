/**
 * The shared component set the roadmap's "consistent design pass" asked
 * for. Before this, every page hand-rolled its own button/input classes —
 * 87 separate instances across 13 pages, with drifting padding (px-3 py-1
 * vs px-4 py-2), inconsistent disabled states, and three different
 * "primary action" treatments. These primitives are the fix: one
 * definition per semantic type, used everywhere instead of copy-pasted.
 *
 * Every primitive here carries real dark: variants - found through
 * actual use that adding a dark-mode-aware page background globally,
 * without dark: classes on the shared primitives every page is built
 * from, produced BROKEN pages (illegible near-invisible text), not just
 * inconsistent-looking ones. Fixing dark mode here is the highest-
 * leverage single change available, since most of the app's 23 pages
 * build their headers/cards/buttons/inputs from these exact functions.
 *
 * Deliberately NOT "use client" — these are plain functions with no
 * hooks, so they work in both server and client components.
 */
import type { ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes } from "react";
import { LayoutDashboard } from "lucide-react";
import Link from "next/link";

const BUTTON_VARIANTS = {
  primary: "bg-slate-800 dark:bg-zinc-100 text-white dark:text-zinc-950 hover:bg-slate-700 dark:hover:bg-zinc-300",
  secondary: "bg-white dark:bg-zinc-800 text-slate-700 dark:text-white border border-slate-300 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-700",
  danger: "bg-red-600 text-white hover:bg-red-700",
  ghost: "text-slate-500 dark:text-zinc-500 hover:text-slate-700 dark:hover:text-zinc-100 underline",
} as const;

const BUTTON_SIZES = {
  sm: "text-xs px-3 py-1.5",
  md: "text-sm px-4 py-2",
} as const;

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof BUTTON_VARIANTS;
  size?: keyof typeof BUTTON_SIZES;
};

export function Button({ variant = "primary", size = "md", className = "", ...props }: ButtonProps) {
  const base = variant === "ghost" ? "" : "rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors";
  const sizeClass = variant === "ghost" ? "text-sm" : BUTTON_SIZES[size];
  return (
    <button
      className={`${base} ${sizeClass} ${BUTTON_VARIANTS[variant]} ${className}`.trim()}
      {...props}
    />
  );
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & { label?: string };

export function Input({ label, className = "", id, ...props }: InputProps) {
  const input = (
    <input
      id={id}
      className={`w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-zinc-500 rounded-lg px-3 py-2 text-sm ${className}`.trim()}
      {...props}
    />
  );
  if (!label) return input;
  return (
    <label htmlFor={id} className="block text-sm text-slate-600 dark:text-zinc-300">
      {label}
      <div className="mt-1">{input}</div>
    </label>
  );
}

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { label?: string };

export function Select({ label, className = "", id, children, ...props }: SelectProps) {
  const select = (
    <select
      id={id}
      className={`w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm ${className}`.trim()}
      {...props}
    >
      {children}
    </select>
  );
  if (!label) return select;
  return (
    <label htmlFor={id} className="block text-sm text-slate-600 dark:text-zinc-300">
      {label}
      <div className="mt-1">{select}</div>
    </label>
  );
}

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`bg-white dark:bg-zinc-900 rounded-xl shadow-sm dark:shadow-none dark:border dark:border-zinc-800 ${className}`.trim()}>{children}</div>;
}

/**
 * The "<h1> + back link" header every page repeats. Takes an optional
 * `actions` slot for page-specific buttons (NotificationBell, Settings
 * link, etc.) so it doesn't force a rigid layout onto pages that need
 * more than a title and a back link.
 */
export function PageHeader({
  title,
  description,
  backHref = "/dashboard",
  backLabel = "← Dashboard",
  actions,
}: {
  title: string;
  description?: string;
  backHref?: string;
  backLabel?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex justify-between items-start mb-6 flex-wrap gap-2">
      <div>
        <h1 className="text-2xl font-bold text-slate-800 dark:text-white">{title}</h1>
        {description && <p className="text-sm text-slate-500 dark:text-zinc-500 mt-1 max-w-xl">{description}</p>}
      </div>
      <div className="flex items-center gap-2">
        {actions}
        <Link
          href={backHref}
          className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm text-slate-600 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 hover:text-slate-800 dark:hover:text-white transition-colors"
        >
          <LayoutDashboard size={16} /> {backLabel === "← Dashboard" ? "Dashboard" : backLabel}
        </Link>
      </div>
    </div>
  );
}
