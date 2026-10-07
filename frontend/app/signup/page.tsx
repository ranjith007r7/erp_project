"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Building2, Check, Globe, KeyRound, Lock, Mail, TriangleAlert, User } from "lucide-react";
import { apiRequest } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { AuthShell } from "@/components/auth/AuthShell";
import { AuthField } from "@/components/auth/AuthField";
import { AuthButton } from "@/components/auth/AuthButton";
import { isValidSubdomain, sanitizeSubdomain, slugify } from "@/lib/slug";
import { MIN_PASSWORD_LENGTH, passwordStrength } from "@/lib/passwordStrength";

type Form = {
  org_name: string;
  subdomain: string;
  admin_name: string;
  admin_email: string;
  admin_password: string;
};
type Errors = Partial<Record<keyof Form, string>>;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// These mirror the server's rules (OrganizationSignup) so mistakes are caught before a round trip.
// The server remains the authority and still validates everything.
function organizationErrors(f: Form): Errors {
  const e: Errors = {};
  if (f.org_name.trim().length < 2) e.org_name = "Enter your company name (at least 2 characters).";
  if (!isValidSubdomain(f.subdomain)) {
    e.subdomain = f.subdomain.length < 2 ? "Use at least 2 characters." : "Lowercase letters, numbers and hyphens only.";
  }
  return e;
}

function accountErrors(f: Form): Errors {
  const e: Errors = {};
  if (f.admin_name.trim().length < 2) e.admin_name = "Enter your name (at least 2 characters).";
  if (!EMAIL_PATTERN.test(f.admin_email.trim())) e.admin_email = "Enter a valid email address.";
  if (f.admin_password.length < MIN_PASSWORD_LENGTH) e.admin_password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  return e;
}

const STRENGTH_COLORS = ["bg-slate-200 dark:bg-zinc-800", "bg-red-500", "bg-amber-500", "bg-lime-500", "bg-emerald-500"];

function StrengthMeter({ password }: { password: string }) {
  const s = passwordStrength(password);
  return (
    <div className="mt-2.5" aria-live="polite">
      <div className="flex gap-1.5" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${i <= s.score ? STRENGTH_COLORS[s.score] : STRENGTH_COLORS[0]}`}
          />
        ))}
      </div>
      <div className="mt-1.5 flex items-center justify-between text-xs">
        <span className={`flex items-center gap-1 ${s.meetsMinimum ? "text-emerald-600 dark:text-emerald-400" : "text-slate-500 dark:text-zinc-500"}`}>
          {s.meetsMinimum && <Check size={12} aria-hidden />} At least {MIN_PASSWORD_LENGTH} characters
        </span>
        <span className="font-medium text-slate-600 dark:text-zinc-300">{s.label}</span>
      </div>
      {s.meetsMinimum && s.score < 4 && (
        <p className="mt-1 text-xs text-slate-500 dark:text-zinc-500">Tip: mix upper and lower case, add a number and a symbol.</p>
      )}
    </div>
  );
}

export default function SignupPage() {
  const { showToast } = useToast();
  const [accessCodeRequired, setAccessCodeRequired] = useState(false);
  const [accessCode, setAccessCode] = useState("");
  const [verifyRequired, setVerifyRequired] = useState(false);
  useEffect(() => {
    apiRequest<{ access_code_required: boolean }>("/api/auth/signup-config")
      .then((c) => setAccessCodeRequired(c.access_code_required))
      .catch(() => {});
  }, []);
  const [form, setForm] = useState<Form>({ org_name: "", subdomain: "", admin_name: "", admin_email: "", admin_password: "" });
  const [step, setStep] = useState<1 | 2>(1);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const [subdomainEdited, setSubdomainEdited] = useState(false); // once typed by hand, stop auto-suggesting
  const [showOrgErrors, setShowOrgErrors] = useState(false);
  const [showAccountErrors, setShowAccountErrors] = useState(false);
  const [serverErrors, setServerErrors] = useState<Errors>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const orgErrs = showOrgErrors ? organizationErrors(form) : {};
  const acctErrs = showAccountErrors ? accountErrors(form) : {};

  function setField(name: keyof Form, value: string) {
    setForm((f) => ({ ...f, [name]: value }));
    setServerErrors((s) => (s[name] ? { ...s, [name]: undefined } : s));
  }

  function handleCompanyChange(value: string) {
    setForm((f) => ({ ...f, org_name: value, subdomain: subdomainEdited ? f.subdomain : slugify(value) }));
  }

  function handleSubdomainChange(value: string) {
    // The box is allowed to be EMPTY while the person edits it. (An earlier version refilled it
    // with the suggestion the instant it was cleared, so "select all, delete, type my own"
    // produced the suggestion with their text glued on.)
    const clean = sanitizeSubdomain(value);
    setSubdomainEdited(clean !== "");
    setForm((f) => ({ ...f, subdomain: clean }));
    setServerErrors((s) => ({ ...s, subdomain: undefined }));
  }

  // Leaving the box empty hands control back to the suggestion.
  function handleSubdomainBlur() {
    if (form.subdomain === "") {
      setSubdomainEdited(false);
      setForm((f) => ({ ...f, subdomain: slugify(f.org_name) }));
    }
  }

  function goToAccountStep(e: React.FormEvent) {
    e.preventDefault();
    setShowOrgErrors(true);
    if (Object.keys(organizationErrors(form)).length > 0) return;
    setDirection("forward");
    setStep(2);
  }

  function goBack() {
    setDirection("back");
    setError(null);
    setStep(1);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setShowAccountErrors(true);
    if (Object.keys(accountErrors(form)).length > 0) return;
    setLoading(true);
    try {
      const data = await apiRequest<{ access_token: string; email_verification_required: boolean }>("/api/auth/signup", {
        method: "POST",
        body: {
          org_name: form.org_name.trim(),
          subdomain: form.subdomain,
          admin_name: form.admin_name.trim(),
          admin_email: form.admin_email.trim(),
          admin_password: form.admin_password,
          access_code: accessCode.trim() || undefined,
        },
      });
      // No automatic sign-in: administrators sign in on the Admin page (with their authenticator app).
      setVerifyRequired(data.email_verification_required);
      showToast(`Welcome, ${form.admin_name.trim()}! Your organization is ready.`, "success");
      // A real gap this fixes, found through actual use: signup used to
      // redirect INSTANTLY with zero visible confirmation, which is
      // exactly why a genuinely successful signup got mistaken for "it
      // didn't work" and retried - producing a confusing "already
      // registered" error on the second attempt. This brief success
      // state, before the redirect, is the fix - not just the toast
      // alone, since a toast can still be missed if it fires the same
      // instant the page navigates away.
      setSuccess(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      // Put a taken subdomain / taken email next to the field that caused it.
      if (/subdomain/i.test(message)) {
        setServerErrors({ subdomain: message });
        setDirection("back");
        setStep(1);
      } else if (/access code/i.test(message)) {
        setError(message);
      } else if (/email/i.test(message)) {
        setServerErrors({ admin_email: message });
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  }

  if (success) {
    return (
      <AuthShell title="Organization created" subtitle="One more step before you sign in.">
        <div className="space-y-5 py-2 text-center" role="status">
          <span className="relative mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500 shadow-lg shadow-emerald-500/30">
            <svg viewBox="0 0 24 24" className="h-8 w-8" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M5 12.5l4.5 4.5L19 7.5" strokeDasharray="26" className="motion-safe:animate-draw-check" />
            </svg>
          </span>
          {verifyRequired ? (
            <p className="text-sm text-slate-600 dark:text-zinc-300" data-testid="signup-next">
              We sent a verification link to <b>{form.admin_email.trim()}</b>. Click it first, then sign in as Admin.
              The first time you will be asked to link an authenticator app such as Microsoft Authenticator.
            </p>
          ) : (
            <p className="text-sm text-slate-600 dark:text-zinc-300" data-testid="signup-next">
              Sign in as Admin to continue. The first time you will be asked to link an authenticator app such as Microsoft Authenticator.
            </p>
          )}
          <Link href="/login/admin" className="block rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500">
            Go to Admin sign-in
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Create your organization"
      subtitle="Set up your workspace in two quick steps."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400">
            Sign in
          </Link>
        </>
      }
    >
      {/* progress */}
      <div className="mb-6">
        <div className="flex items-center justify-between text-xs font-medium text-slate-500 dark:text-zinc-400">
          <span>Step {step} of 2</span>
          <span>{step === 1 ? "Your organization" : "Your admin account"}</span>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2" aria-hidden>
          <span className="h-1.5 rounded-full bg-indigo-600" />
          <span className={`h-1.5 rounded-full transition-colors duration-500 ${step === 2 ? "bg-indigo-600" : "bg-slate-200 dark:bg-zinc-800"}`} />
        </div>
      </div>

      <div key={step} className={direction === "forward" ? "motion-safe:animate-slide-in-right" : "motion-safe:animate-slide-in-left"}>
        {step === 1 ? (
          <form onSubmit={goToAccountStep} noValidate className="space-y-4">
            <AuthField
              label="Company name"
              name="org_name"
              icon={Building2}
              autoComplete="organization"
              autoFocus
              value={form.org_name}
              onChange={(e) => handleCompanyChange(e.target.value)}
              error={orgErrs.org_name}
            />
            <AuthField
              label="Subdomain"
              name="subdomain"
              icon={Globe}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              value={form.subdomain}
              onChange={(e) => handleSubdomainChange(e.target.value)}
              onBlur={handleSubdomainBlur}
              error={orgErrs.subdomain || serverErrors.subdomain}
              hint="Suggested from your company name. Lowercase letters, numbers and hyphens only."
            />
            <AuthButton type="submit" className="mt-2">
              Continue <ArrowRight size={16} aria-hidden />
            </AuthButton>
          </form>
        ) : (
          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <AuthField
              label="Your name"
              name="admin_name"
              icon={User}
              autoComplete="name"
              autoFocus
              value={form.admin_name}
              onChange={(e) => setField("admin_name", e.target.value)}
              error={acctErrs.admin_name}
            />
            <AuthField
              label="Your email"
              type="email"
              name="admin_email"
              icon={Mail}
              autoComplete="email"
              value={form.admin_email}
              onChange={(e) => setField("admin_email", e.target.value)}
              error={acctErrs.admin_email || serverErrors.admin_email}
            />
            <div>
              <AuthField
                label="Password"
                type="password"
                name="admin_password"
                icon={Lock}
                autoComplete="new-password"
                value={form.admin_password}
                onChange={(e) => setField("admin_password", e.target.value)}
                error={acctErrs.admin_password}
              />
              <StrengthMeter password={form.admin_password} />
              {accessCodeRequired && (
                <div className="mt-4">
                  <AuthField
                    label="Access code"
                    name="access_code"
                    icon={KeyRound}
                    autoComplete="off"
                    required
                    value={accessCode}
                    onChange={(e) => setAccessCode(e.target.value)}
                  />
                  <p className="mt-1.5 text-xs text-slate-500 dark:text-zinc-400">Sign-ups are invitation only. Use the code you were given.</p>
                </div>
              )}
            </div>

            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 motion-safe:animate-shake dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
              >
                <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
                <span>{error}</span>
              </div>
            )}

            <div className="flex gap-3 pt-1">
              <button
                type="button"
                onClick={goBack}
                disabled={loading}
                className="flex shrink-0 items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
              >
                <ArrowLeft size={16} aria-hidden /> Back
              </button>
              <AuthButton type="submit" loading={loading} loadingLabel="Creating…">
                Create organization
              </AuthButton>
            </div>
          </form>
        )}
      </div>
    </AuthShell>
  );
}
