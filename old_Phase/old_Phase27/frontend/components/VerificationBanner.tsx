"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";

// Must match RESEND_VERIFICATION_COOLDOWN_SECONDS in
// app/api/routes/auth.py - if that value ever changes, this needs to
// change with it, since this is purely a UI countdown mirroring a real
// server-side rule, not the actual enforcement (the backend still
// rejects an early request regardless of what this shows).
const RESEND_COOLDOWN_SECONDS = 60;

/**
 * A persistent, dismissible-by-verifying reminder. Deliberately not a
 * one-time post-signup screen - someone can easily miss or forget a
 * single moment right after signup, but this keeps showing up on every
 * Dashboard visit until email_verified actually flips true, which is a
 * much harder thing to accidentally never do anything about.
 *
 * The countdown also fixes a real latent bug found while adding it: the
 * previous version set status to "sent" after a successful resend and
 * never had any code path that reset it back to "idle" - the button
 * stayed permanently disabled for the rest of that page session, even
 * long after the real 60-second cooldown had passed.
 */
export function VerificationBanner({ email }: { email: string }) {
  const [status, setStatus] = useState<"idle" | "sending" | "cooldown">("idle");
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "cooldown") return;
    if (secondsLeft <= 0) {
      setStatus("idle");
      return;
    }
    const timer = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [status, secondsLeft]);

  async function handleResend() {
    setStatus("sending");
    setError(null);
    try {
      await apiRequest("/api/auth/resend-verification", { method: "POST", body: { email } });
      setStatus("cooldown");
      setSecondsLeft(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStatus("idle");
    }
  }

  const buttonLabel =
    status === "sending" ? "Sending..." : status === "cooldown" ? `Resend in ${secondsLeft}s` : "Resend verification email";

  return (
    <div className="bg-amber-50 border border-amber-300 rounded-lg p-3 mb-6 flex justify-between items-center flex-wrap gap-2">
      <p className="text-sm text-amber-800">
        <span className="font-medium">Verify your email</span> — check your inbox for a link sent to{" "}
        {email}. Some features may be limited until you verify.
      </p>
      <div className="flex items-center gap-2">
        {error && <p className="text-xs text-red-600">{error}</p>}
        <button
          onClick={handleResend}
          disabled={status !== "idle"}
          className="text-xs bg-amber-800 text-white dark:text-zinc-900 px-3 py-1.5 rounded-lg hover:bg-amber-700 disabled:opacity-50 whitespace-nowrap"
        >
          {buttonLabel}
        </button>
      </div>
    </div>
  );
}
