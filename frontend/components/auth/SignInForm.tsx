"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { QRCodeSVG } from "qrcode.react";
import { ArrowLeft, Copy, KeyRound, Lock, Mail, ShieldCheck, TriangleAlert } from "lucide-react";
import { apiRequest, setToken } from "@/lib/api";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthButton } from "@/components/auth/AuthButton";

export type Portal = "admin" | "employee";

// Mirrors RESEND_VERIFICATION_COOLDOWN_SECONDS in app/api/routes/auth.py (UI only; the server enforces it).
const RESEND_COOLDOWN_SECONDS = 60;
const SUCCESS_PAUSE_MS = 450;

type LoginResponse = {
  access_token: string | null;
  requires_totp: boolean;
  requires_totp_setup: boolean;
  challenge_token: string | null;
};
type Step = "credentials" | "totp" | "setup" | "recovery";

const alertClasses =
  "space-y-2.5 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 motion-safe:animate-shake dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300";

export function SignInForm({ portal }: { portal: Portal }) {
  const router = useRouter();
  const isAdmin = portal === "admin";
  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [errorCount, setErrorCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [isUnverifiedError, setIsUnverifiedError] = useState(false);
  const [resendStatus, setResendStatus] = useState<"idle" | "sending" | "cooldown">("idle");
  const [resendSecondsLeft, setResendSecondsLeft] = useState(0);
  const [saved, setSaved] = useState(false);
  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (resendStatus !== "cooldown") return;
    if (resendSecondsLeft <= 0) {
      setResendStatus("idle");
      return;
    }
    const t = setTimeout(() => setResendSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendStatus, resendSecondsLeft]);

  useEffect(() => () => {
    if (redirectTimer.current) clearTimeout(redirectTimer.current);
  }, []);

  function fail(err: unknown) {
    const message = err instanceof Error ? err.message : "Something went wrong";
    setError(message);
    setErrorCount((n) => n + 1);
    setIsUnverifiedError(message.includes("verify your email"));
  }

  function finish(token: string) {
    setToken(token);
    setSuccess(true);
    redirectTimer.current = setTimeout(() => router.push("/dashboard"), SUCCESS_PAUSE_MS);
  }

  async function startSetup(ch: string) {
    const data = await apiRequest<{ secret: string; otpauth_uri: string }>("/api/auth/totp/setup/start", {
      method: "POST",
      body: { challenge_token: ch },
    });
    setSecret(data.secret);
    setUri(data.otpauth_uri);
    setStep("setup");
  }

  async function submitCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsUnverifiedError(false);
    setLoading(true);
    try {
      const data = await apiRequest<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: { email, password, portal },
      });
      if (data.access_token) {
        finish(data.access_token);
      } else if (data.requires_totp && data.challenge_token) {
        setChallenge(data.challenge_token);
        setCode("");
        setStep("totp");
      } else if (data.requires_totp_setup && data.challenge_token) {
        setChallenge(data.challenge_token);
        setCode("");
        await startSetup(data.challenge_token);
      } else {
        throw new Error("Unexpected response from the server.");
      }
    } catch (err) {
      fail(err);
    } finally {
      setLoading(false);
    }
  }

  async function submitTotp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await apiRequest<{ access_token: string }>("/api/auth/totp/verify", {
        method: "POST",
        body: { challenge_token: challenge, code: code.trim() },
      });
      finish(data.access_token);
    } catch (err) {
      fail(err);
    } finally {
      setLoading(false);
    }
  }

  async function submitSetup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await apiRequest<{ access_token: string; recovery_codes: string[] }>("/api/auth/totp/setup/confirm", {
        method: "POST",
        body: { challenge_token: challenge, code: code.trim() },
      });
      setToken(data.access_token);
      setRecoveryCodes(data.recovery_codes);
      setStep("recovery");
    } catch (err) {
      fail(err);
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

  const errorBox = error && (
    <div key={errorCount} role="alert" className={alertClasses}>
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
          {resendStatus === "sending" ? "Sending..." : resendStatus === "cooldown" ? `Resend in ${resendSecondsLeft}s` : "Resend verification email"}
        </button>
      )}
    </div>
  );

  const other = isAdmin ? { href: "/login/employee", label: "Employee sign-in" } : { href: "/login/admin", label: "Admin sign-in" };
  const footer = (
    <div className="space-y-1.5">
      <div>
        <Link href="/login" className="inline-flex items-center gap-1 font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
          <ArrowLeft size={14} aria-hidden /> Back to sign-in options
        </Link>
        {" · "}
        <Link href={other.href} className="font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
          {other.label}
        </Link>
      </div>
      {isAdmin && (
        <div>
          New here?{" "}
          <Link href="/signup" className="font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
            Create your organization
          </Link>
        </div>
      )}
    </div>
  );

  if (step === "recovery") {
    return (
      <AuthShell title="Save your recovery codes" subtitle="Use one of these if you ever lose your phone. Each works once. They are shown only now." footer={footer}>
        <div className="space-y-4">
          <div data-testid="recovery-codes" className="grid grid-cols-2 gap-2 rounded-xl bg-slate-100 p-4 font-mono text-sm text-slate-900 dark:bg-zinc-800 dark:text-zinc-100">
            {recoveryCodes.map((c) => (
              <span key={c}>{c}</span>
            ))}
          </div>
          <button
            type="button"
            onClick={() => navigator.clipboard?.writeText(recoveryCodes.join("\n"))}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            <Copy size={14} aria-hidden /> Copy all
          </button>
          <label className="flex items-start gap-2 text-sm text-slate-700 dark:text-zinc-300">
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="mt-0.5" />
            I have saved these codes somewhere safe.
          </label>
          <AuthButton type="button" onClick={() => router.push("/dashboard")} disabled={!saved}>
            Continue to dashboard
          </AuthButton>
        </div>
      </AuthShell>
    );
  }

  if (step === "setup") {
    return (
      <AuthShell title="Set up your authenticator" subtitle="Admin accounts need a second step. Use Microsoft Authenticator, Google Authenticator or any TOTP app." footer={footer}>
        <form onSubmit={submitSetup} className="space-y-4">
          <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-600 dark:text-zinc-300">
            <li>Open the app and add an account by scanning this code.</li>
            <li>Enter the 6-digit code the app shows.</li>
          </ol>
          <div className="flex justify-center rounded-xl bg-white p-4 ring-1 ring-slate-200">
            <QRCodeSVG value={uri} size={176} />
          </div>
          <p className="text-xs text-slate-500 dark:text-zinc-400">
            Can&apos;t scan? Enter this key manually:{" "}
            <code data-testid="totp-secret" className="break-all rounded bg-slate-100 px-1.5 py-0.5 text-slate-800 dark:bg-zinc-800 dark:text-zinc-200">{secret}</code>
          </p>
          <AuthField label="6-digit code" name="code" icon={ShieldCheck} inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} />
          {errorBox}
          <AuthButton type="submit" loading={loading} loadingLabel="Checking…">Confirm and continue</AuthButton>
        </form>
      </AuthShell>
    );
  }

  if (step === "totp") {
    return (
      <AuthShell title="Two-step verification" subtitle={useRecovery ? "Enter one of your saved recovery codes." : "Enter the 6-digit code from your authenticator app."} footer={footer}>
        <form onSubmit={submitTotp} className="space-y-4">
          <AuthField
            label={useRecovery ? "Recovery code" : "6-digit code"}
            name="code"
            icon={useRecovery ? KeyRound : ShieldCheck}
            inputMode={useRecovery ? "text" : "numeric"}
            autoComplete="one-time-code"
            autoFocus
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <button
            type="button"
            onClick={() => { setUseRecovery((v) => !v); setCode(""); setError(null); }}
            className="text-xs font-medium text-slate-500 underline-offset-4 hover:text-indigo-600 hover:underline dark:text-zinc-400"
          >
            {useRecovery ? "Use my authenticator app instead" : "Lost your phone? Use a recovery code"}
          </button>
          {errorBox}
          <AuthButton type="submit" loading={loading} loadingLabel="Verifying…" success={success} successLabel="Signed in">Verify</AuthButton>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={isAdmin ? "Admin sign-in" : "Employee sign-in"}
      subtitle={isAdmin ? "For organization administrators. You will be asked for an authenticator code." : "Sign in with the account your administrator created for you."}
      footer={footer}
    >
      <form onSubmit={submitCredentials} className="space-y-4">
        <AuthField label="Email" type="email" name="email" icon={Mail} autoComplete="email" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} />
        <div>
          <AuthField label="Password" type="password" name="password" icon={Lock} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          <div className="mt-2 text-right">
            <Link href="/forgot-password" className="text-xs font-medium text-slate-500 underline-offset-4 hover:text-indigo-600 hover:underline dark:text-zinc-400 dark:hover:text-indigo-400">
              Forgot password?
            </Link>
          </div>
        </div>
        {errorBox}
        <AuthButton type="submit" loading={loading} loadingLabel="Signing in…" success={success} successLabel="Signed in">
          Sign in
        </AuthButton>
      </form>
    </AuthShell>
  );
}
