"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiRequest, clearToken, getToken } from "@/lib/api";

type CurrentUser = {
  id: string;
  name: string;
  email: string;
  org_id: string;
  status: string;
};

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }

    apiRequest<CurrentUser>("/api/auth/me", { auth: true })
      .then(setUser)
      .catch((err) => {
        setError(err.message);
        clearToken();
        router.push("/login");
      });
  }, [router]);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  if (error) return <p className="p-8 text-red-600">{error}</p>;
  if (!user) return <p className="p-8 text-slate-500">Loading...</p>;

  return (
    <main className="min-h-screen p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-2xl font-bold text-slate-800">Dashboard</h1>
        <button
          onClick={handleLogout}
          className="text-sm text-slate-500 underline hover:text-slate-700"
        >
          Log out
        </button>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-6 max-w-md">
        <p className="text-slate-500 text-sm mb-1">Logged in as</p>
        <p className="text-lg font-medium text-slate-800">{user.name}</p>
        <p className="text-slate-500">{user.email}</p>
        <hr className="my-4" />
        <p className="text-xs text-slate-400">Organization ID: {user.org_id}</p>
        <p className="text-xs text-slate-400">Status: {user.status}</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-8 max-w-3xl">
        {["CRM", "Sales", "Procurement", "Inventory", "Finance", "HR", "Projects", "Documents", "Reports"].map(
          (module) => (
            <div
              key={module}
              className="bg-white rounded-lg shadow-sm p-4 text-center text-slate-400 text-sm"
            >
              {module}
              <div className="text-xs mt-1">(coming next)</div>
            </div>
          )
        )}
      </div>
    </main>
  );
}
