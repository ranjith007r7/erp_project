"use client";

import { Suspense, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { apiRequest, setToken } from "@/lib/api";

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
        <p className="text-sm text-red-600">
          This link is missing an invite token. Please use the link from your invitation email
          directly.
        </p>
        <Link href="/login" className="block text-center text-sm text-slate-800 underline">
          Back to login
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-slate-500">Set a password to activate your account.</p>
      <div>
        <label className="block text-sm font-medium text-slate-600 mb-1">Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          className="w-full border border-slate-300 rounded-lg px-3 py-2"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-slate-600 mb-1">Confirm password</label>
        <input
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
          minLength={8}
          className="w-full border border-slate-300 rounded-lg px-3 py-2"
        />
      </div>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-slate-800 text-white rounded-lg py-2 font-medium hover:bg-slate-700 disabled:opacity-50"
      >
        {loading ? "Setting up..." : "Activate Account"}
      </button>
    </form>
  );
}

export default function AcceptInvitePage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-sm w-full bg-white p-8 rounded-xl shadow-sm space-y-4">
        <h1 className="text-2xl font-bold text-slate-800">Welcome</h1>
        <Suspense fallback={<p className="text-sm text-slate-400">Loading…</p>}>
          <AcceptInviteForm />
        </Suspense>
      </div>
    </main>
  );
}
