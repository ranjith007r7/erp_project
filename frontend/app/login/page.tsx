"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Lock, Mail, TriangleAlert } from "lucide-react";
import { apiRequest, setToken } from "@/lib/api";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthButton } from "@/components/auth/AuthButton";

// Must match RESEND_VERIFICATION_COOLDOWN_SECONDS in
// app/api/routes/auth.py - a UI mirror of a real server-side rule, not
// the actual enforcement (the backend still rejects an early request
// no matter what this shows).
const RESEND_COOLDOWN_SECONDS = 60;

// How long the "Signed in" confirmation shows before navigating. Long enough to be seen,
// short enough not to feel like a delay.
const SUCCESS_PAUSE_MS = 450;

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [errorCount, setErrorCount] = useState(0); // a new key each failure re-triggers the shake
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [isUnverifiedError, setIsUnverifiedError] = useState(false);
  const [resendStatus, setResendStatus] = useState<"idle" | "sending" | "cooldown">("idle");
  const [resendSecondsLeft, setResendSecondsLeft] = useState(0);
  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (resendStatus !== "cooldown") return;
    if (resendSecondsLeft <= 0) {
      setResendStatus("idle");
      return;
    }
    const timer = setTimeout(() => setResendSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendStatus, resendSecondsLeft]);

  useEffect(() => () => {
    if (redirectTimer.current) clearTimeout(redirectTimer.current);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsUnverifiedError(false);
    setLoading(true);
    try {
      const data = await apiRequest<{ access_token: string }>("/api/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setToken(data.access_token);
      setSuccess(true);
      redirectTimer.current = setTimeout(() => router.push("/dashboard"), SUCCESS_PAUSE_MS);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      setError(message);
      setErrorCount((n) => n + 1);
      // Detected by the distinctive text in the backend's specific
      // 403 for this case (see app/api/routes/auth.py's login route) -
      // not a generic "any 403" check, since other 403s (disabled
      // account, rate limit) shouldn't offer a resend button.
      setIsUnverifiedError(message.includes("verify your email"));
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    setResendStatus("sending");
    try {
      await apiRequest("/api/auth/resend-verification", { method: "POST", body: { email } });
      setResendStatus("cooldown");
      setResendSecondsLeft(RESEND_COOLDOWN_SECONDS);
    } catch {
      setResendStatus("idle");
    }
  }

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your workspace to continue."
      footer={
        <>
          New here?{" "}
          <Link href="/signup" className="font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
            Create your organization
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="motion-safe:animate-fade-up" style={{ animationDelay: "120ms" }}>
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
        </div>

        <div className="motion-safe:animate-fade-up" style={{ animationDelay: "190ms" }}>
          <AuthField
            label="Password"
            type="password"
            name="password"
            icon={Lock}
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <div className="mt-2 text-right">
            <Link
              href="/forgot-password"
              className="text-xs font-medium text-slate-500 underline-offset-4 hover:text-indigo-600 hover:underline dark:text-zinc-400 dark:hover:text-indigo-400"
            >
              Forgot password?
            </Link>
          </div>
        </div>

        {error && (
          <div
            key={errorCount}
            role="alert"
            className="space-y-2.5 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 motion-safe:animate-shake dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
          >
            <p className="flex items-start gap-2">
              <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
              <span>{error}</span>
            </p>
            {isUnverifiedError && (
              <button
                type="button"
                onClick={handleResend}
                disabled={resendStatus !== "idle"}
                className="rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm ring-1 ring-red-200 transition hover:bg-red-50 disabled:opacity-60 dark:bg-zinc-900 dark:text-zinc-200 dark:ring-red-500/30 dark:hover:bg-zinc-800"
              >
                {resendStatus === "sending"
                  ? "Sending..."
                  : resendStatus === "cooldown"
                  ? `Resend in ${resendSecondsLeft}s`
                  : "Resend verification email"}
              </button>
            )}
          </div>
        )}

        <div className="pt-1 motion-safe:animate-fade-up" style={{ animationDelay: "260ms" }}>
          <AuthButton type="submit" loading={loading} loadingLabel="Signing in…" success={success} successLabel="Signed in">
            Sign in
          </AuthButton>
        </div>
      </form>
    </AuthShell>
  );
}
