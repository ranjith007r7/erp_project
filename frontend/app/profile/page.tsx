"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { PageHeader, Button, Card } from "@/components/ui";
import { useToast } from "@/components/Toast";

type Employee = {
  employee_code: string | null; name: string; department_name: string | null; designation: string | null;
  employment_type: string | null; joining_date: string | null; salary: string | number; status: string;
  phone: string | null; personal_email: string | null; date_of_birth: string | null; gender: string | null;
  address: string | null; emergency_contact_name: string | null; emergency_contact_phone: string | null;
};
type Me = {
  user: { name: string; email: string; role_name: string | null; is_admin: boolean };
  organization: { id: string; name: string };
  employee: Employee | null;
  editable_fields: string[];
  otp_sent_to: string;
};

const inputCls =
  "w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-zinc-500 rounded-lg px-3 py-2 text-sm";

const EDIT: { key: keyof Employee | "name"; label: string; type?: string; wide?: boolean }[] = [
  { key: "name", label: "Full name" },
  { key: "phone", label: "Mobile number", type: "tel" },
  { key: "personal_email", label: "Personal email", type: "email" },
  { key: "date_of_birth", label: "Date of birth", type: "date" },
  { key: "gender", label: "Gender", type: "gender" },
  { key: "address", label: "Address", type: "textarea", wide: true },
  { key: "emergency_contact_name", label: "Emergency contact name" },
  { key: "emergency_contact_phone", label: "Emergency contact phone", type: "tel" },
];

const pretty = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v).replace(/_/g, " "));

export default function MyProfilePage() {
  const { showToast } = useToast();
  const [me, setMe] = useState<Me | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [step, setStep] = useState<"edit" | "otp">("edit");
  const [otp, setOtp] = useState("");
  const [sentTo, setSentTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    apiRequest<Me>("/api/me/profile", { auth: true })
      .then((m) => { setMe(m); setDraft({}); setStep("edit"); setOtp(""); })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  }
  useEffect(load, []);

  if (!me) return <div className="max-w-3xl mx-auto p-6 text-sm text-slate-500 dark:text-zinc-400">{error ?? "Loading…"}</div>;

  const cur = (k: string): string => {
    if (k === "name") return me.employee?.name ?? me.user.name;
    const v = me.employee ? (me.employee as unknown as Record<string, unknown>)[k] : null;
    return v == null ? "" : String(v);
  };
  const val = (k: string) => (k in draft ? draft[k] : cur(k));
  const fields = EDIT.filter((f) => me.editable_fields.includes(f.key as string));
  const changed = Object.keys(draft).filter((k) => draft[k] !== cur(k));

  async function sendCode() {
    setBusy(true); setError(null);
    try {
      const r = await apiRequest<{ sent_to: string }>("/api/me/profile/request-otp", { method: "POST", auth: true });
      setSentTo(r.sent_to); setStep("otp");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the code");
    } finally { setBusy(false); }
  }

  async function confirm() {
    setBusy(true); setError(null);
    const body: Record<string, string | null> = { otp };
    for (const k of changed) body[k] = draft[k] === "" ? null : draft[k];
    try {
      await apiRequest("/api/me/profile", { method: "PATCH", auth: true, body });
      showToast("Profile updated.", "success");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally { setBusy(false); }
  }

  const e = me.employee;
  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <PageHeader title="My Profile" description={`${me.organization.name} · ${me.user.role_name ?? "No role"}`} />

      <Link href="/profile/leaves" className="block rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm font-medium text-indigo-700 hover:bg-indigo-100 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300" data-testid="to-leaves">
        My Leaves: apply for leave, check balances and see your attendance →
      </Link>

      <Card>
        <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">Your account</h2>
        <div className="grid gap-3 sm:grid-cols-2 text-sm">
          <div><p className="text-xs text-slate-500 dark:text-zinc-500">Login email</p><p data-testid="login-email" className="text-slate-900 dark:text-white">{me.user.email}</p></div>
          <div><p className="text-xs text-slate-500 dark:text-zinc-500">Organization</p><p className="text-slate-900 dark:text-white">{me.organization.name}</p></div>
        </div>
      </Card>

      {e ? (
        <Card>
          <h2 className="mb-1 font-semibold text-slate-900 dark:text-white">Employment details</h2>
          <p className="mb-3 text-xs text-slate-500 dark:text-zinc-500">Set by HR. Ask HR if something here is wrong.</p>
          <div className="grid gap-3 sm:grid-cols-2 text-sm">
            {[
              ["Employee code", e.employee_code], ["Department", e.department_name], ["Role", e.designation],
              ["Employment type", e.employment_type], ["Joining date", e.joining_date], ["Status", e.status],
              ["Monthly salary", e.salary == null ? null : "₹" + Number(e.salary).toLocaleString("en-IN")],
            ].map(([l, v]) => (
              <div key={l as string}><p className="text-xs text-slate-500 dark:text-zinc-500">{l}</p><p data-testid={"emp-" + (l as string).toLowerCase().replace(/ /g, "-")} className="text-slate-900 dark:text-white capitalize">{pretty(v)}</p></div>
            ))}
          </div>
        </Card>
      ) : (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
          No HR record is linked to your login yet, so only your name can be edited here. HR can link it from the employee page.
        </p>
      )}

      <Card>
        <h2 className="mb-1 font-semibold text-slate-900 dark:text-white">Personal details</h2>
        <p className="mb-4 text-xs text-slate-500 dark:text-zinc-500">You can edit these. Saving needs a one-time code emailed to your login address.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          {fields.map((f) => (
            <div key={f.key} className={f.wide ? "sm:col-span-2" : ""}>
              <label htmlFor={"p-" + f.key} className="block text-xs font-medium text-slate-600 dark:text-zinc-400 mb-1">{f.label}</label>
              {f.type === "textarea" ? (
                <textarea id={"p-" + f.key} rows={3} className={inputCls} value={val(f.key)} disabled={step === "otp"} onChange={(ev) => setDraft({ ...draft, [f.key]: ev.target.value })} />
              ) : f.type === "gender" ? (
                <select id={"p-" + f.key} className={inputCls} value={val(f.key)} disabled={step === "otp"} onChange={(ev) => setDraft({ ...draft, [f.key]: ev.target.value })}>
                  <option value="">Not set</option><option value="male">Male</option><option value="female">Female</option><option value="other">Other</option>
                </select>
              ) : (
                <input id={"p-" + f.key} type={f.type ?? "text"} className={inputCls} value={val(f.key)} disabled={step === "otp"} onChange={(ev) => setDraft({ ...draft, [f.key]: ev.target.value })} />
              )}
            </div>
          ))}
        </div>

        <div className="mt-5 space-y-3">
          {step === "edit" ? (
            <div className="flex items-center gap-3">
              <Button onClick={sendCode} disabled={busy || changed.length === 0} data-testid="send-otp">{busy ? "Sending…" : "Save changes (email me a code)"}</Button>
              {changed.length > 0 && <button type="button" onClick={() => setDraft({})} className="text-sm text-slate-500 underline dark:text-zinc-400">Discard</button>}
            </div>
          ) : (
            <div className="space-y-3 rounded-lg border border-slate-200 p-4 dark:border-zinc-700" data-testid="otp-panel">
              <p className="text-sm text-slate-700 dark:text-zinc-300">Enter the 6-digit code we emailed to <b>{sentTo}</b> (valid 15 minutes).</p>
              <div className="flex gap-2">
                <input inputMode="numeric" maxLength={6} placeholder="123456" className={inputCls + " max-w-[10rem]"} value={otp} onChange={(ev) => setOtp(ev.target.value.replace(/\D/g, ""))} data-testid="otp-input" />
                <Button onClick={confirm} disabled={busy || otp.length !== 6} data-testid="confirm-otp">{busy ? "Saving…" : "Confirm and save"}</Button>
              </div>
              <div className="flex gap-4 text-xs">
                <button type="button" onClick={sendCode} disabled={busy} className="text-slate-500 underline dark:text-zinc-400">Send a new code</button>
                <button type="button" onClick={() => { setStep("edit"); setOtp(""); setError(null); }} className="text-slate-500 underline dark:text-zinc-400">Back to editing</button>
              </div>
            </div>
          )}
          {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        </div>
      </Card>
    </div>
  );
}
