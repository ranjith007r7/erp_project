"use client";

import { Suspense, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, Lock, TriangleAlert } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthButton } from "@/components/auth/AuthButton";

const alertClasses =
  "flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 motion-safe:animate-shake dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300";

// useSearchParams() requires a Suspense boundary in the Next.js App
// Router (otherwise the production build fails static generation for
// this page) - the actual form lives in an inner component wrapped by
// the default export below, rather than reading search params directly
// in the page component itself.
function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    if (!token) {
      setError("This reset link is missing its token — please use the link from your email directly.");
      return;
    }

    setLoading(true);
    try {
      await apiRequest("/api/auth/reset-password", {
        method: "POST",
        body: { token, new_password: newPassword },
      });
      setSuccess(true);
      setTimeout(() => router.push("/login"), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="space-y-4">
        <p role="alert" className={alertClasses}>
          <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            This link is missing a reset token. Please use the link from your password reset email directly, or request a new one.
          </span>
        </p>
        <Link href="/forgot-password" className="block text-center text-sm font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
          Request a new reset link
        </Link>
      </div>
    );
  }

  if (success) {
    return (
      <div className="space-y-3 text-center" role="status">
        <CheckCircle2 className="mx-auto text-emerald-500" size={44} aria-hidden />
        <p className="text-sm text-slate-600 dark:text-zinc-300">Password updated. Redirecting you to login…</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <AuthField
        label="New password"
        type="password"
        name="new_password"
        icon={Lock}
        autoComplete="new-password"
        autoFocus
        required
        minLength={8}
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        hint="At least 8 characters."
      />
      <AuthField
        label="Confirm new password"
        type="password"
        name="confirm_password"
        icon={Lock}
        autoComplete="new-password"
        required
        minLength={8}
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
      />

      {error && (
        <div role="alert" className={alertClasses}>
          <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      )}

      <AuthButton type="submit" loading={loading} loadingLabel="Resetting…">
        Reset password
      </AuthButton>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <AuthShell title="Set a new password" subtitle="Choose a new password for your account.">
      <Suspense fallback={<p className="text-sm text-slate-400 dark:text-zinc-500">Loading…</p>}>
        <ResetPasswordForm />
      </Suspense>
    </AuthShell>
  );
}
