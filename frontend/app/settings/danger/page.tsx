"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { RotateCcw, Trash2, TriangleAlert } from "lucide-react";
import { apiRequest, clearToken } from "@/lib/api";
import { PageHeader, Button, Input, Card } from "@/components/ui";

type Status = { org_name: string; subdomain: string; email_hint: string; totp_enabled: boolean };
type Mode = "reset" | "delete";

export default function DangerZonePage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [password, setPassword] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [typed, setTyped] = useState("");
  const [totp, setTotp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<Status>("/api/organizations/danger/status", { auth: true })
      .then(setStatus)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  }, []);

  function choose(m: Mode) {
    setMode(m);
    setPassword("");
    setSentTo(null);
    setCode("");
    setTyped("");
    setTotp("");
    setError(null);
  }

  async function sendCode() {
    if (!mode) return;
    setBusy(true);
    setError(null);
    try {
      const r = await apiRequest<{ sent_to: string }>("/api/organizations/danger/request-code", {
        method: "POST",
        auth: true,
        body: { purpose: mode, password },
      });
      setSentTo(r.sent_to);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the code");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!mode || !status) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "reset") {
        await apiRequest("/api/organizations/danger/reset", {
          method: "POST",
          auth: true,
          body: { code, confirm_text: typed, totp_code: totp || null },
        });
        setDone("All business data has been removed. Your staff, roles and HR structure were kept.");
        setMode(null);
      } else {
        await apiRequest("/api/organizations/danger/delete", {
          method: "POST",
          auth: true,
          body: { code, subdomain: typed, totp_code: totp || null },
        });
        clearToken();
        router.push("/signup?deleted=1");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const expected = mode === "reset" ? "RESET" : status?.subdomain ?? "";
  const ready = code.length === 6 && typed.trim() === expected && (!status?.totp_enabled || totp.length >= 6);

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <PageHeader title="Danger Zone" description="Irreversible actions for the whole organization. Administrators only." />

      {done && (
        <p role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
          {done}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <div className="space-y-3">
            <RotateCcw className="text-amber-600" size={22} aria-hidden />
            <h2 className="font-semibold text-slate-900 dark:text-white">Reset organization data</h2>
            <p className="text-sm text-slate-600 dark:text-zinc-400">
              Removes customers, orders, invoices, stock, projects, documents and other records so you can start fresh.
              Staff accounts, roles, departments and employees stay.
            </p>
            <Button variant="secondary" onClick={() => choose("reset")} data-testid="choose-reset">Reset data…</Button>
          </div>
        </Card>
        <Card>
          <div className="space-y-3">
            <Trash2 className="text-red-600" size={22} aria-hidden />
            <h2 className="font-semibold text-slate-900 dark:text-white">Delete permanently</h2>
            <p className="text-sm text-slate-600 dark:text-zinc-400">
              Erases the entire organization: all data, every staff login and uploaded files. It cannot be recovered.
              You can sign up again later with the same email.
            </p>
            <Button variant="danger" onClick={() => choose("delete")} data-testid="choose-delete">Delete organization…</Button>
          </div>
        </Card>
      </div>

      {mode && status && (
        <Card>
          <div className="space-y-4" data-testid="danger-wizard">
            <h3 className="flex items-center gap-2 font-semibold text-red-700 dark:text-red-400">
              <TriangleAlert size={18} aria-hidden />
              {mode === "reset" ? "Reset all data" : `Permanently delete ${status.org_name}`}
            </h3>

            <p className="text-sm font-medium text-slate-700 dark:text-zinc-300">Step 1 — confirm your password</p>
            <div className="flex gap-2">
              <Input type="password" placeholder="Your password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={!!sentTo} />
              <Button onClick={sendCode} disabled={busy || !password || !!sentTo} data-testid="send-code">
                {sentTo ? "Code sent" : "Email me a code"}
              </Button>
            </div>

            {sentTo && (
              <>
                <p className="text-sm font-medium text-slate-700 dark:text-zinc-300">
                  Step 2 — enter the 6-digit code emailed to {sentTo} (valid 15 minutes)
                </p>
                <Input inputMode="numeric" maxLength={6} placeholder="123456" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} data-testid="email-code" />

                <p className="text-sm font-medium text-slate-700 dark:text-zinc-300">
                  Step 3 — type <code className="rounded bg-slate-100 px-1 dark:bg-zinc-800">{expected}</code> to confirm
                  {status.totp_enabled ? ", and enter your authenticator code" : ""}
                </p>
                <Input placeholder={expected} value={typed} onChange={(e) => setTyped(e.target.value)} data-testid="typed-confirm" />
                {status.totp_enabled && (
                  <Input inputMode="numeric" placeholder="Authenticator code" value={totp} onChange={(e) => setTotp(e.target.value)} data-testid="totp-code" />
                )}
                <Button variant="danger" onClick={confirm} disabled={busy || !ready} data-testid="confirm-danger">
                  {mode === "reset" ? "Reset data now" : "Delete everything permanently"}
                </Button>
              </>
            )}

            {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
            <button type="button" onClick={() => setMode(null)} className="text-xs text-slate-500 underline dark:text-zinc-400">Cancel</button>
          </div>
        </Card>
      )}
      {!mode && error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
