"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest, setToken } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    org_name: "",
    subdomain: "",
    admin_name: "",
    admin_email: "",
    admin_password: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setForm({ ...form, [e.target.name]: e.target.value });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await apiRequest<{ access_token: string }>("/api/auth/signup", {
        method: "POST",
        body: form,
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
        className="max-w-md w-full bg-white p-8 rounded-xl shadow-sm space-y-4"
      >
        <h1 className="text-2xl font-bold text-slate-800">Create your organization</h1>

        <div>
          <label className="block text-sm font-medium text-slate-600 mb-1">
            Company name
          </label>
          <input
            name="org_name"
            value={form.org_name}
            onChange={handleChange}
            required
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
            placeholder="Acme Corp"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-600 mb-1">
            Subdomain
          </label>
          <input
            name="subdomain"
            value={form.subdomain}
            onChange={handleChange}
            required
            pattern="[a-z0-9-]+"
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
            placeholder="acme (lowercase letters, numbers, hyphens only)"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-600 mb-1">
            Your name
          </label>
          <input
            name="admin_name"
            value={form.admin_name}
            onChange={handleChange}
            required
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-600 mb-1">
            Your email
          </label>
          <input
            type="email"
            name="admin_email"
            value={form.admin_email}
            onChange={handleChange}
            required
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-600 mb-1">
            Password
          </label>
          <input
            type="password"
            name="admin_password"
            value={form.admin_password}
            onChange={handleChange}
            required
            minLength={8}
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
          />
        </div>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-slate-800 text-white rounded-lg py-2 font-medium hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? "Creating..." : "Create Organization"}
        </button>
      </form>
    </main>
  );
}
