"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { apiRequest, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await apiRequest<{ access_token: string }>("/api/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setToken(data.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <form
        onSubmit={handleSubmit}
        className="max-w-sm w-full bg-white p-8 rounded-xl shadow-sm space-y-4"
      >
        <h1 className="text-2xl font-bold text-slate-800">Log in</h1>

        <div>
          <label className="block text-sm font-medium text-slate-600 mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
          />
        </div>

        <div>
          <div className="flex justify-between items-center mb-1">
            <label className="block text-sm font-medium text-slate-600">Password</label>
            <Link href="/forgot-password" className="text-xs text-slate-500 underline hover:text-slate-700">
              Forgot password?
            </Link>
          </div>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
          />
        </div>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-slate-800 text-white rounded-lg py-2 font-medium hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? "Logging in..." : "Log In"}
        </button>

        <p className="text-sm text-slate-500 text-center">
          No organization yet?{" "}
          <Link href="/signup" className="text-slate-800 underline">
            Create one
          </Link>
        </p>
      </form>
    </main>
  );
}
