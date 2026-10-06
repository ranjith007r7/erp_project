"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Mail, MailCheck, TriangleAlert } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthButton } from "@/components/auth/AuthButton";

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

  const backToLogin = (
    <Link href="/login" className="inline-flex items-center gap-1.5 font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
      <ArrowLeft size={14} aria-hidden /> Back to login
    </Link>
  );

  return (
    <AuthShell
      title={submitted ? "Check your inbox" : "Forgot your password?"}
      subtitle={submitted ? undefined : "Enter the email you signed up with, and we'll send you a link to reset your password."}
      footer={backToLogin}
    >
      {submitted ? (
        <div className="space-y-4 text-center" role="status">
          <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300">
            <MailCheck size={30} aria-hidden />
          </span>
          <p className="text-sm text-slate-600 dark:text-zinc-300">
            If an account exists for <span className="font-medium">{email}</span>, a password reset link has been sent.
            Check your inbox (and spam folder). The link expires in 1 hour.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <AuthField
            label="Email"
            type="email"
            name="email"
            icon={Mail}
            autoComplete="email"
            autoFocus
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 motion-safe:animate-shake dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
              <span>{error}</span>
            </div>
          )}

          <AuthButton type="submit" loading={loading} loadingLabel="Sending…">
            Send reset link
          </AuthButton>
        </form>
      )}
    </AuthShell>
  );
}
