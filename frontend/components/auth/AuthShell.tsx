"use client";

import type { ReactNode } from "react";
import { BRAND } from "@/lib/brand";
import { ThemeToggle } from "@/components/ThemeToggle";
import { BrandMark } from "./BrandMark";
import { BrandPanel } from "./BrandPanel";

/**
 * The shared frame for every signed-out screen (home, log in, sign up, forgot/reset password,
 * accept invite, verify email): a brand panel on the left on large screens, and the form card on
 * the right. On phones the panel is dropped and a compact brand header takes its place.
 */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-black lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <BrandPanel />

      <div
        className="relative flex min-h-screen flex-col"
        style={{ backgroundImage: "radial-gradient(640px 320px at 85% 0%, rgba(99,102,241,0.07), transparent 70%)" }}
      >
        <div className="flex items-center justify-between px-5 py-4 sm:px-8">
          <div className="flex items-center gap-2.5 lg:hidden">
            <BrandMark size={34} />
            <span className="font-semibold tracking-tight text-slate-800 dark:text-white">{BRAND.productName}</span>
          </div>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>

        <main className="flex flex-1 items-center justify-center px-5 pb-10 sm:px-8">
          <div className="w-full max-w-md">
            <div className="rounded-2xl bg-white/85 p-7 shadow-xl shadow-indigo-900/5 ring-1 ring-slate-200/80 backdrop-blur motion-safe:animate-fade-up dark:bg-zinc-900/80 dark:shadow-none dark:ring-white/10 sm:p-9">
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h1>
              {subtitle && <p className="mt-1.5 text-sm text-slate-500 dark:text-zinc-400">{subtitle}</p>}
              <div className="mt-7">{children}</div>
            </div>
            {footer && (
              <div
                className="mt-6 text-center text-sm text-slate-500 motion-safe:animate-fade-up dark:text-zinc-400"
                style={{ animationDelay: "180ms" }}
              >
                {footer}
              </div>
            )}
          </div>
        </main>

        <p className="px-8 pb-6 text-center text-xs text-slate-400 dark:text-zinc-600 lg:hidden">
          © {new Date().getFullYear()} {BRAND.companyName}. All rights reserved.
        </p>
      </div>
    </div>
  );
}
