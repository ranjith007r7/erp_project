"use client";

import { Suspense, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Lock, TriangleAlert } from "lucide-react";
import { apiRequest, setToken } from "@/lib/api";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthButton } from "@/components/auth/AuthButton";

const alertClasses =
  "flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 motion-safe:animate-shake dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300";

// Same Suspense-boundary requirement as reset-password/verify-email -
// useSearchParams() needs it for the production build's static
// generation to succeed.
function AcceptInviteForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    if (!token) {
      setError("This invite link is missing its token — please use the link from your email directly.");
      return;
    }

    setLoading(true);
    try {
      const data = await apiRequest<{ access_token: string }>("/api/auth/accept-invite", {
        method: "POST",
        body: { token, password },
      });
      // Same auto-login pattern as signup - accepting an invite counts
      // as email verification too (a real clicked link already proves
      // inbox ownership), so there's no separate verify step to gate on.
      setToken(data.access_token);
      router.push("/dashboard");
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
          <span>This link is missing an invite token. Please use the link from your invitation email directly.</span>
        </p>
        <Link href="/login" className="block text-center text-sm font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
          Back to login
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <AuthField
        label="Password"
        type="password"
        name="password"
        icon={Lock}
        autoComplete="new-password"
        autoFocus
        required
        minLength={8}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        hint="At least 8 characters."
      />
      <AuthField
        label="Confirm password"
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

      <AuthButton type="submit" loading={loading} loadingLabel="Setting up…">
        Activate account
      </AuthButton>
    </form>
  );
}

export default function AcceptInvitePage() {
  return (
    <AuthShell title="Welcome aboard" subtitle="Set a password to activate your account.">
      <Suspense fallback={<p className="text-sm text-slate-400 dark:text-zinc-500">Loading…</p>}>
        <AcceptInviteForm />
      </Suspense>
    </AuthShell>
  );
}
