"use client";

import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader, Button, Card } from "@/components/ui";
import { useToast } from "@/components/Toast";

type Balance = { code: string; name: string; paid: boolean; note: string | null; entitlement: string | null; approved: string; pending: string; remaining: string | null };
type Req = { id: string; leave_type: string; start_date: string; end_date: string; status: string; days: number; reason: string | null; decision_note: string | null };
type Data = { year: number; employee_name: string; balances: Balance[]; requests: Req[] };
type Att = { month: number; year: number; days: { date: string; status: string | null; from_approved_leave: boolean }[]; counts: Record<string, number>; not_marked: number };

const inputCls =
  "w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-zinc-500 rounded-lg px-3 py-2 text-sm";
const today = () => new Date().toISOString().slice(0, 10);
const STATUS_STYLE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300",
  cancelled: "bg-slate-100 text-slate-600 dark:bg-zinc-800 dark:text-zinc-400",
};
const ATT_STYLE: Record<string, string> = {
  present: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
  absent: "bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300",
  half_day: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
  leave: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300",
};
const num = (v: string | null) => (v === null ? null : Number(v));

export default function MyLeavesPage() {
  const { showToast } = useToast();
  const [data, setData] = useState<Data | null>(null);
  const [att, setAtt] = useState<Att | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [type, setType] = useState("");
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [reason, setReason] = useState("");
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));

  function load() {
    apiRequest<Data>("/api/me/leaves", { auth: true })
      .then((d) => { setData(d); setType((t) => t || d.balances[0]?.name || ""); })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  }
  useEffect(load, []);
  useEffect(() => {
    const [y, m] = month.split("-");
    apiRequest<Att>(`/api/me/attendance?month=${Number(m)}&year=${Number(y)}`, { auth: true }).then(setAtt).catch(() => setAtt(null));
  }, [month]);

  const days = useMemo(() => (start && end && end >= start ? Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86400000) + 1 : 0), [start, end]);
  const chosen = data?.balances.find((b) => b.name === type);
  const remaining = chosen ? num(chosen.remaining) : null;
  const tooMany = remaining !== null && days > remaining;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setFormError(null);
    try {
      await apiRequest("/api/me/leaves", { method: "POST", auth: true, body: { leave_type: type, start_date: start, end_date: end, reason: reason || null } });
      showToast("Leave request sent for approval.", "success");
      setReason("");
      load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not send the request");
    } finally { setBusy(false); }
  }

  async function cancel(id: string) {
    try {
      await apiRequest(`/api/me/leaves/${id}/cancel`, { method: "POST", auth: true });
      showToast("Request cancelled.", "success");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel");
    }
  }

  if (!data) return <div className="max-w-4xl mx-auto p-6 text-sm text-slate-500 dark:text-zinc-400">{error ?? "Loading…"}</div>;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <PageHeader title="My Leaves" description={`${data.employee_name} · leave balance for ${data.year}, applications and attendance`} />
      {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="balances">
        {data.balances.map((b) => (
          <Card key={b.code}>
            <p className="text-sm font-medium text-slate-900 dark:text-white">{b.name} {!b.paid && <span className="ml-1 text-[10px] rounded-full bg-red-100 px-1.5 py-0.5 text-red-700 dark:bg-red-950/60 dark:text-red-300">unpaid</span>}</p>
            <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white" data-testid={"remaining-" + b.code}>{b.remaining === null ? "No limit" : `${num(b.remaining)} left`}</p>
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              {b.entitlement !== null ? `of ${num(b.entitlement)} · ` : ""}{num(b.approved)} taken · {num(b.pending)} pending
            </p>
          </Card>
        ))}
      </section>

      <Card>
        <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">Apply for leave</h2>
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="lv-type" className="block text-xs font-medium text-slate-600 dark:text-zinc-400 mb-1">Leave type</label>
            <select id="lv-type" className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
              {data.balances.map((b) => <option key={b.code} value={b.name}>{b.name}</option>)}
            </select>
            {chosen?.note && <p className="mt-1 text-xs text-slate-400 dark:text-zinc-500">{chosen.note}</p>}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="lv-start" className="block text-xs font-medium text-slate-600 dark:text-zinc-400 mb-1">From</label>
              <input id="lv-start" type="date" required className={inputCls} value={start} onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} />
            </div>
            <div>
              <label htmlFor="lv-end" className="block text-xs font-medium text-slate-600 dark:text-zinc-400 mb-1">To</label>
              <input id="lv-end" type="date" required min={start} className={inputCls} value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="lv-reason" className="block text-xs font-medium text-slate-600 dark:text-zinc-400 mb-1">Reason (optional)</label>
            <textarea id="lv-reason" rows={2} maxLength={500} className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={busy || days === 0 || !type} data-testid="apply-leave">{busy ? "Sending…" : "Send for approval"}</Button>
            <span className="text-sm text-slate-600 dark:text-zinc-300" data-testid="day-count">{days > 0 ? `${days} day${days === 1 ? "" : "s"} (weekends included)` : "Choose valid dates"}</span>
            {tooMany && <span className="text-sm text-amber-700 dark:text-amber-400">More than the {remaining} day(s) left. Consider Loss of Pay for the rest.</span>}
          </div>
          {formError && <p role="alert" className="sm:col-span-2 text-sm text-red-600 dark:text-red-400">{formError}</p>}
        </form>
      </Card>

      <Card>
        <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">My requests</h2>
        <div className="divide-y divide-slate-100 dark:divide-zinc-800" data-testid="my-requests">
          {data.requests.map((r) => (
            <div key={r.id} className="py-3 flex flex-wrap items-start justify-between gap-2 text-sm">
              <div>
                <p className="font-medium text-slate-900 dark:text-white">{r.leave_type} · {r.days} day{r.days === 1 ? "" : "s"}</p>
                <p className="text-xs text-slate-500 dark:text-zinc-400">{r.start_date} → {r.end_date}</p>
                {r.reason && <p className="text-xs text-slate-500 dark:text-zinc-400">Reason: {r.reason}</p>}
                {r.decision_note && <p className="text-xs text-slate-600 dark:text-zinc-300">Note from approver: {r.decision_note}</p>}
              </div>
              <div className="flex items-center gap-3">
                <span className={`rounded-full px-2 py-0.5 text-xs capitalize ${STATUS_STYLE[r.status] ?? ""}`} data-testid={"status-" + r.id}>{r.status}</span>
                {r.status === "pending" && <button type="button" onClick={() => cancel(r.id)} className="text-xs text-slate-500 underline dark:text-zinc-400" data-testid={"cancel-" + r.id}>Cancel</button>}
              </div>
            </div>
          ))}
          {data.requests.length === 0 && <p className="py-2 text-sm text-slate-400 dark:text-zinc-500">No requests yet.</p>}
        </div>
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold text-slate-900 dark:text-white">My attendance</h2>
          <input type="month" aria-label="Month" className={inputCls + " max-w-[10rem]"} value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        </div>
        <p className="mb-3 text-xs text-slate-500 dark:text-zinc-400">Marked by your administrator. You can view it but not change it. Approved leave days show as Leave.</p>
        {att && (
          <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs" data-testid="att-counts">
              {(["present", "absent", "half_day", "leave"] as const).map((k) => (
                <span key={k} className={`rounded-full px-2 py-0.5 ${ATT_STYLE[k]}`}>{k.replace("_", " ")}: {att.counts[k]}</span>
              ))}
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600 dark:bg-zinc-800 dark:text-zinc-400">not marked: {att.not_marked}</span>
            </div>
            <div className="flex flex-wrap gap-1.5" data-testid="att-days">
              {att.days.map((x) => (
                <span key={x.date} title={`${x.date}: ${x.status ?? "not marked"}`} className={`flex h-8 w-8 items-center justify-center rounded text-xs ${x.status ? ATT_STYLE[x.status] : "bg-slate-100 text-slate-400 dark:bg-zinc-800 dark:text-zinc-500"}`}>
                  {Number(x.date.slice(8))}
                </span>
              ))}
              {att.days.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">Nothing to show for this month yet.</p>}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
