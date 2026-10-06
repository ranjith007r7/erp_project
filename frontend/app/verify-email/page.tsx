"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, TriangleAlert } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { AuthShell } from "@/components/auth/AuthShell";
import { Shimmer, Spinner, authButtonClasses } from "@/components/auth/AuthButton";

function VerifyEmailStatus() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"verifying" | "success" | "error">("verifying");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setError("This link is missing its verification token.");
      return;
    }
    apiRequest("/api/auth/verify-email", { method: "POST", body: { token } })
      .then(() => setStatus("success"))
      .catch((err) => {
        setStatus("error");
        setError(err instanceof Error ? err.message : "Verification failed.");
      });
  }, [token]);

  if (status === "verifying") {
    return (
      <p className="flex items-center gap-3 text-sm text-slate-500 dark:text-zinc-400" role="status">
        <Spinner className="text-indigo-500" /> Verifying your email…
      </p>
    );
  }

  if (status === "success") {
    return (
      <div className="space-y-5 text-center" role="status">
        <CheckCircle2 className="mx-auto text-emerald-500" size={48} aria-hidden />
        <p className="text-sm text-slate-600 dark:text-zinc-300">Your email is verified. You can log in now.</p>
        <Link href="/login" className={authButtonClasses("primary")}>
          <Shimmer />
          <span className="relative">Go to login</span>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
        <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
        <span>{error}</span>
      </p>
      <p className="text-sm text-slate-500 dark:text-zinc-400">
        The link may have expired (links are valid for 24 hours) or already been used.
      </p>
      <Link href="/login" className="block text-center text-sm font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
        Back to login
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <AuthShell title="Email verification">
      <Suspense fallback={<p className="text-sm text-slate-400 dark:text-zinc-500">Loading…</p>}>
        <VerifyEmailStatus />
      </Suspense>
    </AuthShell>
  );
}
