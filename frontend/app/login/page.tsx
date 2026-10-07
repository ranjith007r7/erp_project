import Link from "next/link";
import { ChevronRight, ShieldCheck, UserRound } from "lucide-react";
import { AuthShell } from "@/components/auth/AuthShell";

const card =
  "group flex items-center gap-4 rounded-xl border border-slate-200 bg-white px-4 py-4 transition hover:border-indigo-400 hover:shadow-md dark:border-white/10 dark:bg-zinc-900 dark:hover:border-indigo-400";

export default function LoginChooserPage() {
  return (
    <AuthShell
      title="Welcome back"
      subtitle="Choose how you want to sign in."
      footer={
        <>
          New here?{" "}
          <Link href="/signup" className="font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
            Create your organization
          </Link>
        </>
      }
    >
      <div className="space-y-3">
        <Link href="/login/admin" className={card} data-testid="choose-admin">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">
            <ShieldCheck size={20} aria-hidden />
          </span>
          <span className="flex-1">
            <span className="block font-medium text-slate-900 dark:text-white">Sign in as Admin</span>
            <span className="block text-xs text-slate-500 dark:text-zinc-400">Organization owners and administrators</span>
          </span>
          <ChevronRight size={18} className="text-slate-400 transition group-hover:translate-x-0.5" aria-hidden />
        </Link>
        <Link href="/login/employee" className={card} data-testid="choose-employee">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300">
            <UserRound size={20} aria-hidden />
          </span>
          <span className="flex-1">
            <span className="block font-medium text-slate-900 dark:text-white">Sign in as Employee</span>
            <span className="block text-xs text-slate-500 dark:text-zinc-400">Staff with an account created by their admin</span>
          </span>
          <ChevronRight size={18} className="text-slate-400 transition group-hover:translate-x-0.5" aria-hidden />
        </Link>
      </div>
    </AuthShell>
  );
}
