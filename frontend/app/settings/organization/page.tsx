"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader, Button, Card } from "@/components/ui";
import { useToast } from "@/components/Toast";

type Profile = Record<string, string | number | boolean | null> & {
  id: string; name: string; subdomain: string; plan: string; can_edit: boolean; created_at: string;
};

type Field = {
  key: string; label: string; type?: "text" | "email" | "tel" | "date" | "url" | "textarea" | "select" | "month";
  options?: [string, string][]; hint?: string; wide?: boolean;
};

const SIZES: [string, string][] = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"].map((s) => [s, s + " people"]);
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const SECTIONS: { title: string; note?: string; fields: Field[] }[] = [
  { title: "Company", fields: [
    { key: "name", label: "Organization name", hint: "Shown across the app" },
    { key: "legal_name", label: "Legal / registered name" },
    { key: "industry", label: "Industry" },
    { key: "company_size", label: "Company size", type: "select", options: SIZES },
    { key: "founded_on", label: "Founded on", type: "date" },
    { key: "website", label: "Website", type: "url" },
    { key: "description", label: "About the company", type: "textarea", wide: true },
  ] },
  { title: "Owner / primary contact", fields: [
    { key: "owner_name", label: "Owner name" },
    { key: "owner_designation", label: "Designation" },
    { key: "owner_email", label: "Owner email", type: "email" },
    { key: "owner_phone", label: "Owner mobile number", type: "tel" },
  ] },
  { title: "Company contacts", fields: [
    { key: "company_email", label: "Company email", type: "email" },
    { key: "company_phone", label: "Company phone", type: "tel" },
    { key: "support_email", label: "Support email", type: "email" },
    { key: "support_phone", label: "Support phone", type: "tel" },
  ] },
  { title: "Address", fields: [
    { key: "address_line1", label: "Address line 1", wide: true },
    { key: "address_line2", label: "Address line 2", wide: true },
    { key: "city", label: "City" },
    { key: "state", label: "State" },
    { key: "postal_code", label: "PIN / postal code" },
    { key: "country", label: "Country" },
  ] },
  { title: "Tax and registration", fields: [
    { key: "gstin", label: "GSTIN", hint: "15 characters" },
    { key: "pan", label: "PAN", hint: "10 characters" },
    { key: "cin", label: "CIN", hint: "21 characters" },
    { key: "registration_number", label: "Other registration number" },
  ] },
  { title: "Regional settings", fields: [
    { key: "fiscal_year_start_month", label: "Financial year starts in", type: "month" },
    { key: "currency", label: "Currency (3-letter code)" },
    { key: "timezone", label: "Time zone", hint: "e.g. Asia/Kolkata" },
  ] },
];

const inputCls =
  "w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-zinc-500 rounded-lg px-3 py-2 text-sm";

function show(f: Field, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (f.type === "month") return MONTHS[Number(v) - 1] ?? String(v);
  if (f.type === "select") return f.options?.find(([k]) => k === v)?.[1] ?? String(v);
  return String(v);
}

export default function OrganizationProfilePage() {
  const { showToast } = useToast();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    apiRequest<Profile>("/api/organizations/profile", { auth: true })
      .then((p) => { setProfile(p); setDraft({}); })
      .catch((e) => setErrors(e instanceof Error ? e.message : "Could not load"));
  }
  useEffect(load, []);

  if (!profile) return <div className="max-w-4xl mx-auto p-6 text-sm text-slate-500 dark:text-zinc-400">{errors ?? "Loading…"}</div>;

  const canEdit = profile.can_edit;
  const dirty = Object.keys(draft).length > 0;
  const value = (k: string) => (k in draft ? draft[k] : profile[k] == null ? "" : String(profile[k]));

  async function save() {
    setSaving(true);
    setErrors(null);
    const body: Record<string, string | number | null> = {};
    for (const [k, v] of Object.entries(draft)) body[k] = k === "fiscal_year_start_month" ? (v ? Number(v) : null) : v === "" ? null : v;
    try {
      await apiRequest("/api/organizations/profile", { method: "PATCH", auth: true, body });
      showToast("Organization profile saved.", "success");
      load();
    } catch (e) {
      setErrors(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <PageHeader
        title="Organization Profile"
        description={canEdit ? "Your company's details. Only administrators can change them; everyone else can view." : "Your company's details. Only administrators can change them."}
      />

      <Card>
        <div className="grid gap-3 sm:grid-cols-2 text-sm" data-testid="org-identity">
          <div><p className="text-xs text-slate-500 dark:text-zinc-500">Organization</p><p className="font-medium text-slate-900 dark:text-white">{profile.name}</p></div>
          <div><p className="text-xs text-slate-500 dark:text-zinc-500">Organization ID</p><p className="font-mono text-xs text-slate-700 dark:text-zinc-300 break-all">{profile.id}</p></div>
          <div><p className="text-xs text-slate-500 dark:text-zinc-500">Sub-domain (used to identify the company, cannot be changed)</p><p className="text-slate-900 dark:text-white">{profile.subdomain}</p></div>
          <div><p className="text-xs text-slate-500 dark:text-zinc-500">Plan · member since</p><p className="text-slate-900 dark:text-white capitalize">{profile.plan} · {new Date(profile.created_at).toLocaleDateString()}</p></div>
        </div>
      </Card>

      {SECTIONS.map((sec) => (
        <Card key={sec.title}>
          <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">{sec.title}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {sec.fields.map((f) => (
              <div key={f.key} className={f.wide ? "sm:col-span-2" : ""}>
                <label htmlFor={"f-" + f.key} className="block text-xs font-medium text-slate-600 dark:text-zinc-400 mb-1">{f.label}</label>
                {!canEdit ? (
                  <p data-testid={"view-" + f.key} className="text-sm text-slate-900 dark:text-white whitespace-pre-wrap">{show(f, profile[f.key])}</p>
                ) : f.type === "textarea" ? (
                  <textarea id={"f-" + f.key} rows={3} className={inputCls} value={value(f.key)} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
                ) : f.type === "select" ? (
                  <select id={"f-" + f.key} className={inputCls} value={value(f.key)} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}>
                    <option value="">Not set</option>
                    {f.options!.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                ) : f.type === "month" ? (
                  <select id={"f-" + f.key} className={inputCls} value={value(f.key)} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}>
                    {MONTHS.map((m, i) => <option key={m} value={String(i + 1)}>{m}</option>)}
                  </select>
                ) : (
                  <input id={"f-" + f.key} type={f.type ?? "text"} className={inputCls} value={value(f.key)} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
                )}
                {canEdit && f.hint && <p className="mt-1 text-xs text-slate-400 dark:text-zinc-500">{f.hint}</p>}
              </div>
            ))}
          </div>
        </Card>
      ))}

      {canEdit && (
        <div className="sticky bottom-4 flex items-center gap-3 rounded-xl border border-slate-200 bg-white/95 p-3 shadow-lg backdrop-blur dark:border-zinc-700 dark:bg-zinc-900/95">
          <Button onClick={save} disabled={!dirty || saving} data-testid="save-org">{saving ? "Saving…" : "Save changes"}</Button>
          {dirty && <button type="button" onClick={() => setDraft({})} className="text-sm text-slate-500 underline dark:text-zinc-400">Discard</button>}
          {errors && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{errors}</p>}
        </div>
      )}
      {!canEdit && errors && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{errors}</p>}
    </div>
  );
}
