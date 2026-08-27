"use client";

import { useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // The backend always returns the same generic message whether or
      // not the email exists - deliberate, to avoid letting this page
      // be used to check which emails have accounts. The UI mirrors
      // that: it always shows success, never "email not found".
      await apiRequest("/api/auth/forgot-password", { method: "POST", body: { email } });
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-sm w-full bg-white dark:bg-zinc-900 p-8 rounded-xl shadow-sm space-y-4">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-white">Forgot password</h1>

        {submitted ? (
          <div className="space-y-4">
            <p className="text-sm text-slate-600 dark:text-zinc-300">
              If an account exists for <span className="font-medium">{email}</span>, a password
              reset link has been sent. Check your inbox (and spam folder) — the link expires in
              1 hour.
            </p>
            <Link href="/login" className="block text-center text-sm text-slate-800 dark:text-white underline">
              Back to login
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <p className="text-sm text-slate-500 dark:text-zinc-500">
              Enter the email you signed up with, and we'll send you a link to reset your password.
            </p>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-zinc-300 mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-3 py-2"
              />
            </div>

            {error && <p className="text-red-600 text-sm">{error}</p>}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 font-medium hover:bg-slate-700 dark:hover:bg-zinc-300 disabled:opacity-50"
            >
              {loading ? "Sending..." : "Send Reset Link"}
            </button>

            <p className="text-sm text-slate-500 dark:text-zinc-500 text-center">
              <Link href="/login" className="text-slate-800 dark:text-white underline">
                Back to login
              </Link>
            </p>
          </form>
        )}
      </div>
    </main>
  );
}
