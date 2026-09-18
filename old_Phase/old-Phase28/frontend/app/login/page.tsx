"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { apiRequest, setToken } from "@/lib/api";

// Must match RESEND_VERIFICATION_COOLDOWN_SECONDS in
// app/api/routes/auth.py - a UI mirror of a real server-side rule, not
// the actual enforcement (the backend still rejects an early request
// no matter what this shows).
const RESEND_COOLDOWN_SECONDS = 60;

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [isUnverifiedError, setIsUnverifiedError] = useState(false);
  const [resendStatus, setResendStatus] = useState<"idle" | "sending" | "cooldown">("idle");
  const [resendSecondsLeft, setResendSecondsLeft] = useState(0);

  useEffect(() => {
    if (resendStatus !== "cooldown") return;
    if (resendSecondsLeft <= 0) {
      setResendStatus("idle");
      return;
    }
    const timer = setTimeout(() => setResendSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendStatus, resendSecondsLeft]);

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
      router.push("/dashboard");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      setError(message);
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
    <main className="min-h-screen flex items-center justify-center px-4">
      <form
        onSubmit={handleSubmit}
        className="max-w-sm w-full bg-white dark:bg-zinc-900 p-8 rounded-xl shadow-sm space-y-4"
      >
        <h1 className="text-2xl font-bold text-slate-800 dark:text-white">Log in</h1>

        <div>
          <label className="block text-sm font-medium text-slate-600 dark:text-zinc-300 mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2"
          />
        </div>

        <div>
          <div className="flex justify-between items-center mb-1">
            <label className="block text-sm font-medium text-slate-600 dark:text-zinc-300">Password</label>
            <Link href="/forgot-password" className="text-xs text-slate-500 dark:text-zinc-500 underline hover:text-slate-700 dark:hover:text-white dark:text-zinc-900">
              Forgot password?
            </Link>
          </div>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2"
          />
        </div>

        {error && (
          <div className="space-y-2">
            <p className="text-red-600 text-sm">{error}</p>
            {isUnverifiedError && (
              <button
                type="button"
                onClick={handleResend}
                disabled={resendStatus !== "idle"}
                className="text-xs bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 px-3 py-1.5 rounded-lg hover:bg-slate-200 dark:hover:bg-zinc-700 disabled:opacity-50"
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

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 font-medium hover:bg-slate-700 dark:hover:bg-zinc-300 active:scale-[0.98] transition-all disabled:opacity-50"
        >
          {loading ? "Logging in..." : "Log In"}
        </button>

        <p className="text-sm text-slate-500 dark:text-zinc-500 text-center">
          No organization yet?{" "}
          <Link href="/signup" className="text-slate-800 dark:text-white underline">
            Create one
          </Link>
        </p>
      </form>
    </main>
  );
}
