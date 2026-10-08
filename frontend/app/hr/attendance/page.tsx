"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader, Button, Card } from "@/components/ui";
import { useToast } from "@/components/Toast";

type Row = { employee_id: string; employee_code: string | null; name: string; department_name: string | null; status: string | null; marked: boolean; on_approved_leave: boolean };
type Summary = { employee_id: string; employee_code: string | null; name: string; present: number; absent: number; half_day: number; leave: number };
const OPTIONS: [string, string][] = [["present", "Present"], ["absent", "Absent"], ["half_day", "Half day"], ["leave", "Leave"]];
const today = () => new Date().toISOString().slice(0, 10);
const inputCls =
  "border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm";

export default function AttendancePage() {
  const { showToast } = useToast();
  const [day, setDay] = useState(today());
  const [rows, setRows] = useState<Row[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [month, setMonth] = useState(() => today().slice(0, 7));
  const [summary, setSummary] = useState<Summary[]>([]);

  useEffect(() => {
    apiRequest<{ is_admin: boolean }>("/api/auth/me", { auth: true }).then((m) => setIsAdmin(!!m.is_admin)).catch(() => {});
  }, []);

  const loadDay = useCallback(() => {
    setError(null);
    apiRequest<{ employees: Row[] }>(`/api/hr/attendance/day?date=${day}`, { auth: true })
      .then((r) => { setRows(r.employees); setDraft({}); })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load"));
  }, [day]);
  useEffect(loadDay, [loadDay]);

  const loadSummary = useCallback(() => {
    const [y, m] = month.split("-");
    apiRequest<Summary[]>(`/api/hr/attendance/summary?month=${Number(m)}&year=${Number(y)}`, { auth: true }).then(setSummary).catch(() => setSummary([]));
  }, [month]);
  useEffect(loadSummary, [loadSummary]);

  const shown = (r: Row) => draft[r.employee_id] ?? r.status ?? (r.on_approved_leave ? "leave" : "");
  const changes = Object.keys(draft).length;

  function markAllPresent() {
    const next: Record<string, string> = { ...draft };
    for (const r of rows) if (!shown(r)) next[r.employee_id] = "present";
    setDraft(next);
  }

  async function save() {
    setSaving(true); setError(null);
    const entries = rows.filter((r) => shown(r)).map((r) => ({ employee_id: r.employee_id, status: shown(r) }));
    try {
      await apiRequest("/api/hr/attendance/bulk", { method: "POST", auth: true, body: { date: day, entries } });
      showToast(`Attendance saved for ${entries.length} employee(s).`, "success");
      loadDay(); loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally { setSaving(false); }
  }

  const unmarked = rows.filter((r) => !shown(r)).length;
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <PageHeader title="Attendance" backHref="/hr" backLabel="← HR" description={isAdmin ? "Mark who was in on a given day. Only administrators can mark attendance." : "Only administrators can mark attendance. You can view it here."} />

      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="text-sm text-slate-600 dark:text-zinc-300" htmlFor="att-day">Date</label>
          <input id="att-day" type="date" className={inputCls} value={day} max={today()} onChange={(e) => e.target.value && setDay(e.target.value)} />
          {isAdmin && <Button variant="secondary" onClick={markAllPresent} disabled={unmarked === 0} data-testid="all-present">Mark unmarked as present</Button>}
          <span className="text-xs text-slate-500 dark:text-zinc-400">Records can be added or corrected for the last 60 days.</span>
        </div>
        <div className="divide-y divide-slate-100 dark:divide-zinc-800" data-testid="att-rows">
          {rows.map((r) => (
            <div key={r.employee_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
              <div>
                <p className="font-medium text-slate-900 dark:text-white">{r.name} <span className="text-xs font-normal text-slate-400">{r.employee_code}</span></p>
                <p className="text-xs text-slate-500 dark:text-zinc-400">{r.department_name ?? "No department"}{r.on_approved_leave && !r.marked ? " · approved leave today" : ""}</p>
              </div>
              {isAdmin ? (
                <select aria-label={`Attendance for ${r.name}`} className={inputCls} value={shown(r)} onChange={(e) => setDraft({ ...draft, [r.employee_id]: e.target.value })} data-testid={"att-" + r.employee_id}>
                  <option value="">Not marked</option>
                  {OPTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              ) : (
                <span className="text-slate-700 dark:text-zinc-300">{OPTIONS.find(([k]) => k === shown(r))?.[1] ?? "Not marked"}</span>
              )}
            </div>
          ))}
          {rows.length === 0 && !error && <p className="py-2 text-sm text-slate-400 dark:text-zinc-500">No active employees.</p>}
        </div>
        {isAdmin && (
          <div className="mt-4 flex items-center gap-3">
            <Button onClick={save} disabled={saving || changes === 0} data-testid="save-attendance">{saving ? "Saving…" : "Save attendance"}</Button>
            {changes > 0 && <span className="text-xs text-slate-500 dark:text-zinc-400">{changes} unsaved change(s)</span>}
          </div>
        )}
        {error && <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold text-slate-900 dark:text-white">Monthly summary</h2>
          <input type="month" aria-label="Month" className={inputCls} value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="att-summary">
            <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-400"><th className="py-1 pr-3">Employee</th><th className="px-2">Present</th><th className="px-2">Absent</th><th className="px-2">Half day</th><th className="px-2">Leave</th></tr></thead>
            <tbody className="text-slate-800 dark:text-zinc-200">
              {summary.map((s) => (
                <tr key={s.employee_id} className="border-t border-slate-100 dark:border-zinc-800"><td className="py-1.5 pr-3">{s.name} <span className="text-xs text-slate-400">{s.employee_code}</span></td><td className="px-2">{s.present}</td><td className="px-2">{s.absent}</td><td className="px-2">{s.half_day}</td><td className="px-2">{s.leave}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
