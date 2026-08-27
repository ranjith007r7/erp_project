"use client";

import { Suspense, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { apiRequest } from "@/lib/api";

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
        <p className="text-sm text-red-600">
          This link is missing a reset token. Please use the link from your password reset email
          directly, or request a new one.
        </p>
        <Link href="/forgot-password" className="block text-center text-sm text-slate-800 underline">
          Request a new reset link
        </Link>
      </div>
    );
  }

  if (success) {
    return (
      <p className="text-sm text-slate-600">
        Password updated. Redirecting you to login…
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-slate-600 mb-1">New password</label>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          required
          minLength={8}
          className="w-full border border-slate-300 rounded-lg px-3 py-2"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-slate-600 mb-1">Confirm new password</label>
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
        {loading ? "Resetting..." : "Reset Password"}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-sm w-full bg-white p-8 rounded-xl shadow-sm space-y-4">
        <h1 className="text-2xl font-bold text-slate-800">Reset password</h1>
        <Suspense fallback={<p className="text-sm text-slate-400">Loading…</p>}>
          <ResetPasswordForm />
        </Suspense>
      </div>
    </main>
  );
}
