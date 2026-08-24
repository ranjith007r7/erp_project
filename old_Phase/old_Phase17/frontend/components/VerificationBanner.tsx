"use client";

import { useState } from "react";
import { apiRequest } from "@/lib/api";

/**
 * A persistent, dismissible-by-verifying reminder. Deliberately not a
 * one-time post-signup screen - someone can easily miss or forget a
 * single moment right after signup, but this keeps showing up on every
 * Dashboard visit until email_verified actually flips true, which is a
 * much harder thing to accidentally never do anything about.
 */
export function VerificationBanner({ email }: { email: string }) {
  const [status, setStatus] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleResend() {
    setStatus("sending");
    setError(null);
    try {
      await apiRequest("/api/auth/resend-verification", { method: "POST", body: { email } });
      setStatus("sent");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStatus("idle");
    }
  }

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
          className="text-xs bg-amber-800 text-white px-3 py-1.5 rounded-lg hover:bg-amber-700 disabled:opacity-50 whitespace-nowrap"
        >
          {status === "sending" ? "Sending..." : status === "sent" ? "Sent — check your inbox" : "Resend verification email"}
        </button>
      </div>
    </div>
  );
}
