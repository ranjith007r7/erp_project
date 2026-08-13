/**
 * The shared component set the roadmap's "consistent design pass" asked
 * for. Before this, every page hand-rolled its own button/input classes —
 * 87 separate instances across 13 pages, with drifting padding (px-3 py-1
 * vs px-4 py-2), inconsistent disabled states, and three different
 * "primary action" treatments. These primitives are the fix: one
 * definition per semantic type, used everywhere instead of copy-pasted.
 *
 * Deliberately NOT "use client" — these are plain functions with no
 * hooks, so they work in both server and client components.
 */
import type { ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes } from "react";
import Link from "next/link";

const BUTTON_VARIANTS = {
  primary: "bg-slate-800 text-white hover:bg-slate-700",
  secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50",
  danger: "bg-red-600 text-white hover:bg-red-700",
  ghost: "text-slate-500 hover:text-slate-700 underline",
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
  const base = variant === "ghost" ? "" : "rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed";
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
      className={`w-full border border-slate-300 rounded-lg px-3 py-2 text-sm ${className}`.trim()}
      {...props}
    />
  );
  if (!label) return input;
  return (
    <label htmlFor={id} className="block text-sm text-slate-600">
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
      className={`w-full border border-slate-300 rounded-lg px-3 py-2 text-sm ${className}`.trim()}
      {...props}
    >
      {children}
    </select>
  );
  if (!label) return select;
  return (
    <label htmlFor={id} className="block text-sm text-slate-600">
      {label}
      <div className="mt-1">{select}</div>
    </label>
  );
}

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`bg-white rounded-xl shadow-sm ${className}`.trim()}>{children}</div>;
}

/**
 * The "<h1> + back link" header every page repeats. Takes an optional
 * `actions` slot for page-specific buttons (NotificationBell, Settings
 * link, etc.) so it doesn't force a rigid layout onto pages that need
 * more than a title and a back link.
 */
export function PageHeader({
  title,
  backHref = "/dashboard",
  backLabel = "← Dashboard",
  actions,
}: {
  title: string;
  backHref?: string;
  backLabel?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex justify-between items-center mb-6">
      <h1 className="text-2xl font-bold text-slate-800">{title}</h1>
      <div className="flex items-center gap-4">
        {actions}
        <Link href={backHref} className="text-sm text-slate-500 underline hover:text-slate-700">
          {backLabel}
        </Link>
      </div>
    </div>
  );
}
