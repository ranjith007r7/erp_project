"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiRequest } from "@/lib/api";

function VerifyEmailStatus() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"verifying" | "success" | "error">("verifying");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setError("This link is missing its verification token.");
      return;
    }
    apiRequest("/api/auth/verify-email", { method: "POST", body: { token } })
      .then(() => setStatus("success"))
      .catch((err) => {
        setStatus("error");
        setError(err instanceof Error ? err.message : "Verification failed.");
      });
  }, [token]);

  if (status === "verifying") {
    return <p className="text-sm text-slate-500">Verifying your email…</p>;
  }

  if (status === "success") {
    return (
      <div className="space-y-4">
        <p className="text-sm text-slate-600">Your email is verified. You can log in now.</p>
        <Link href="/login" className="block text-center text-sm bg-slate-800 text-white rounded-lg py-2 font-medium hover:bg-slate-700">
          Go to login
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-red-600">{error}</p>
      <p className="text-sm text-slate-500">
        The link may have expired (links are valid for 24 hours) or already been used.
      </p>
      <Link href="/login" className="block text-center text-sm text-slate-800 underline">
        Back to login
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-sm w-full bg-white p-8 rounded-xl shadow-sm space-y-4">
        <h1 className="text-2xl font-bold text-slate-800">Email Verification</h1>
        <Suspense fallback={<p className="text-sm text-slate-400">Loading…</p>}>
          <VerifyEmailStatus />
        </Suspense>
      </div>
    </main>
  );
}
