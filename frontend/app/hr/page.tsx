"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, apiDownload, apiUpload } from "@/lib/api";
import { Modal } from "@/components/Modal";
import { NotificationBell } from "@/components/NotificationBell";
import { PageHeader, Button } from "@/components/ui";
import { usePagination, PaginationControls } from "@/components/Pagination";
import { SkeletonList } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";

type Department = { id: string; name: string };
type Employee = {
  id: string; employee_code: string | null; name: string; designation: string | null; salary: string; department_id: string | null;
  department_name: string | null; joining_date: string | null; employment_type: string | null; phone: string | null; personal_email: string | null;
  date_of_birth: string | null; gender: string | null; address: string | null; emergency_contact_name: string | null; emergency_contact_phone: string | null;
  login_status: string | null; login_email: string | null; access_role_name: string | null;
};
type LeaveRequest = { id: string; employee_id: string; leave_type: string; start_date: string; end_date: string; status: string; days?: number; reason?: string | null; decision_note?: string | null };
type Payslip = {
  employee_id: string; gross: string; deductions: string; net_pay: string; pf_amount: string; insurance_amount: string;
  tds_amount: string; leave_deduction: string; lop_days: string;
};
type PayrollRun = { id: string; month: number; year: number; status: string; payslips: Payslip[]; employees_without_deductions?: number };

export default function HRPage() {
  const { showToast } = useToast();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const { pageItems: pagedEmployees, page: employeePage, totalPages: employeeTotalPages, setPage: setEmployeePage } = usePagination(employees, 10);
  const [leaves, setLeaves] = useState<LeaveRequest[]>([]);
  const [payrollRuns, setPayrollRuns] = useState<PayrollRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [selected, setSelected] = useState<Employee | null>(null);
  const [runForm, setRunForm] = useState({ month: String(new Date().getMonth() + 1), year: String(new Date().getFullYear()) });
  const [empImportFile, setEmpImportFile] = useState<File | null>(null);
  const [empImporting, setEmpImporting] = useState(false);
  const [empImportResult, setEmpImportResult] = useState<{ imported: number; failed: number; errors: { row: number; reason: string }[] } | null>(null);

  function handleExportEmployeesCsv() {
    apiDownload("/api/hr/employees/export", "employees.csv").catch((err) => showToast(err instanceof Error ? err.message : "Export failed", "error"));
  }

  async function handleImportEmployeesCsv() {
    if (!empImportFile) return;
    setEmpImporting(true);
    setEmpImportResult(null);
    try {
      const formData = new FormData();
      formData.append("file", empImportFile);
      const result = await apiUpload<{ imported: number; failed: number; errors: { row: number; reason: string }[] }>(
        "/api/hr/employees/import", formData
      );
      setEmpImportResult(result);
      setEmpImportFile(null);
      loadAll();
      showToast(
        result.failed > 0 ? `Imported ${result.imported}, ${result.failed} failed.` : `Imported ${result.imported} employee(s).`,
        result.failed > 0 ? "info" : "success"
      );
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Import failed", "error");
    } finally {
      setEmpImporting(false);
    }
  }

  function loadAll() {
    Promise.allSettled([
      apiRequest<Department[]>("/api/hr/departments", { auth: true }).then(setDepartments),
      apiRequest<Employee[]>("/api/hr/employees", { auth: true }).then(setEmployees).catch((e) => setError(e.message)),
      apiRequest<LeaveRequest[]>("/api/hr/leave-requests", { auth: true }).then(setLeaves),
      apiRequest<PayrollRun[]>("/api/hr/payroll-runs", { auth: true }).then(setPayrollRuns),
    ]).finally(() => setLoading(false));
  }

  useEffect(loadAll, []);

  function employeeName(id: string) {
    return employees.find((e) => e.id === id)?.name || id.slice(0, 8);
  }

  async function updateLeaveStatus(id: string, status: string) {
    // an optional short note goes back to the employee with the decision
    const note = status === "rejected" ? window.prompt("Reason for rejecting (optional, the employee will see it):") : null;
    if (status === "rejected" && note === null) return;
    await apiRequest(`/api/hr/leave-requests/${id}/status`, { method: "PATCH", auth: true, body: { status, note: note || null } }).catch((err) => setError(err.message));
    loadAll();
  }

  async function createPayrollRun(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/hr/payroll-runs", {
        method: "POST",
        auth: true,
        body: { month: Number(runForm.month), year: Number(runForm.year) },
      });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create payroll run");
    }
  }

  async function processPayrollRun(id: string) {
    try {
      const res = await apiRequest<PayrollRun>(`/api/hr/payroll-runs/${id}/process`, { method: "POST", auth: true });
      if (res.employees_without_deductions) {
        showToast(`Processed. ${res.employees_without_deductions} employee(s) had no deductions filled in by Finance, so they were paid in full.`, "info");
      } else showToast("Payroll processed", "success");
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process payroll run");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="HR & Payroll" actions={<NotificationBell />} />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {loading ? (
        <SkeletonList rows={3} />
      ) : (
      <>
      <div className="grid md:grid-cols-2 gap-6 mb-8">
        <Link href="/hr/structure" className="block bg-white dark:bg-zinc-900 rounded-xl shadow-sm dark:shadow-none dark:border dark:border-zinc-800 p-4 hover:ring-2 hover:ring-slate-300 dark:hover:ring-zinc-600">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Departments &amp; Roles</h2>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">{departments.length} department(s). Set up departments, roles and their fixed salaries before hiring.</p>
        </Link>
        <Link href="/hr/employees/new" className="block bg-white dark:bg-zinc-900 rounded-xl shadow-sm dark:shadow-none dark:border dark:border-zinc-800 p-4 hover:ring-2 hover:ring-slate-300 dark:hover:ring-zinc-600" data-testid="new-employee-link">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">+ New employee (application form)</h2>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">Pick department and role, fill in the applicant&apos;s details, get an employee code.</p>
        </Link>
        <Link href="/hr/attendance" className="block bg-white dark:bg-zinc-900 rounded-xl shadow-sm dark:shadow-none dark:border dark:border-zinc-800 p-4 hover:ring-2 hover:ring-slate-300 dark:hover:ring-zinc-600 md:col-span-2" data-testid="attendance-link">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Attendance</h2>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">Mark who was in each day (administrators only) and see the monthly summary.</p>
        </Link>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Employees</h2>
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <Button variant="secondary" size="sm" onClick={handleExportEmployeesCsv}>Export CSV</Button>
            <input
              type="file"
              accept=".csv"
              onChange={(e) => setEmpImportFile(e.target.files?.[0] ?? null)}
              className="text-xs text-slate-600 dark:text-zinc-300"
            />
            <Button variant="secondary" size="sm" disabled={!empImportFile || empImporting} onClick={handleImportEmployeesCsv}>
              {empImporting ? "Importing…" : "Import CSV"}
            </Button>
          </div>
          {empImportResult && (
            <div className="text-xs bg-slate-50 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 rounded-lg p-2 mb-2">
              <p className="text-slate-700 dark:text-zinc-200">
                Imported {empImportResult.imported}, failed {empImportResult.failed}.
              </p>
              {empImportResult.errors.map((e) => (
                <p key={e.row} className="text-red-600 dark:text-red-400">Row {e.row}: {e.reason}</p>
              ))}
            </div>
          )}
          <div className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm divide-y divide-slate-100 dark:divide-zinc-800">
            {pagedEmployees.map((e) => (
              <button key={e.id} onClick={() => setSelected(e)} className="w-full text-left p-3 text-sm hover:bg-slate-50 dark:hover:bg-zinc-800">
                <p className="text-slate-800 dark:text-white font-medium">{e.name} <span className="text-xs font-normal text-slate-400 dark:text-zinc-500">{e.employee_code}</span></p>
                <p className="text-xs text-slate-500 dark:text-zinc-500">{e.designation || "—"}{e.department_name ? ` · ${e.department_name}` : ""} · ₹{Number(e.salary).toLocaleString("en-IN")}/mo</p>
              </button>
            ))}
            {employees.length === 0 && <p className="p-3 text-sm text-slate-400 dark:text-zinc-500">No employees yet.</p>}
          </div>
          <PaginationControls page={employeePage} totalPages={employeeTotalPages} onChange={setEmployeePage} />
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Leave Requests</h2>
          <div className="space-y-2">
            {leaves.map((l) => (
              <div key={l.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3 text-sm">
                <p className="text-slate-800 dark:text-white font-medium">{employeeName(l.employee_id)}</p>
                <p className="text-xs text-slate-500 dark:text-zinc-500">{l.leave_type} · {l.start_date} → {l.end_date}{l.days ? ` · ${l.days} day${l.days === 1 ? "" : "s"}` : ""} · {l.status}</p>
                {l.reason && <p className="text-xs text-slate-500 dark:text-zinc-500">Reason: {l.reason}</p>}
                {l.decision_note && <p className="text-xs text-slate-500 dark:text-zinc-500">Note: {l.decision_note}</p>}
                {l.status === "pending" && (
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={() => updateLeaveStatus(l.id, "approved")}
                      className="text-xs bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 px-3 py-1 rounded-lg hover:bg-slate-700 dark:hover:bg-zinc-300"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => updateLeaveStatus(l.id, "rejected")}
                      className="text-xs border border-slate-300 dark:border-zinc-700 text-slate-600 dark:text-zinc-300 px-3 py-1 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>
            ))}
            {leaves.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No leave requests yet.</p>}
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mb-3">Payroll</h2>
          <form onSubmit={createPayrollRun} className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-3 space-y-2 mb-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <input
                placeholder="Month (1-12)"
                type="number"
                min={1}
                max={12}
                value={runForm.month}
                onChange={(e) => setRunForm({ ...runForm, month: e.target.value })}
                className="border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
              />
              <input
                placeholder="Year"
                type="number"
                value={runForm.year}
                onChange={(e) => setRunForm({ ...runForm, year: e.target.value })}
                className="border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <button className="w-full bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 rounded-lg py-2 text-sm font-medium hover:bg-slate-700 dark:hover:bg-zinc-300">
              Create Payroll Run
            </button>
          </form>

          <div className="space-y-2">
            {payrollRuns.map((run) => (
              <div key={run.id} className="bg-white dark:bg-zinc-900 rounded-lg shadow-sm p-3 text-sm">
                <div className="flex justify-between items-center">
                  <p className="text-slate-800 dark:text-white font-medium">{run.month}/{run.year}</p>
                  <span className="text-xs text-slate-500 dark:text-zinc-500">{run.status}</span>
                </div>
                {run.status !== "processed" ? (
                  <>
                  <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">Finance fills each employee&apos;s PF, insurance, TDS and unpaid-leave days on the <Link href="/finance" className="underline">Finance page</Link> before you process.</p>
                  <button
                    onClick={() => processPayrollRun(run.id)}
                    className="mt-2 text-xs bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900 px-3 py-1.5 rounded-lg hover:bg-slate-700 dark:hover:bg-zinc-300"
                  >
                    Process Payroll
                  </button>
                  </>
                ) : (
                  <div className="mt-2 space-y-1">
                    {run.payslips.map((p, i) => (
                      <div key={i} className="text-xs text-slate-500 dark:text-zinc-500">
                        <p className="flex justify-between">
                          <span>{employeeName(p.employee_id)}</span>
                          <span>Net ₹{Number(p.net_pay).toLocaleString("en-IN")}</span>
                        </p>
                        <p className="text-[11px] text-slate-400 dark:text-zinc-500">
                          Gross ₹{Number(p.gross).toLocaleString("en-IN")} − PF ₹{Number(p.pf_amount).toLocaleString("en-IN")} − Insurance ₹{Number(p.insurance_amount).toLocaleString("en-IN")} − TDS ₹{Number(p.tds_amount).toLocaleString("en-IN")}
                          {Number(p.lop_days) > 0 ? ` − Unpaid leave (${Number(p.lop_days)} d) ₹${Number(p.leave_deduction).toLocaleString("en-IN")}` : ""}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {payrollRuns.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No payroll runs yet.</p>}
          </div>
        </section>
      </div>
      </>
      )}

      {selected && (
        <Modal title={`${selected.name} · ${selected.employee_code || ""}`} onClose={() => setSelected(null)}>
          <dl className="text-sm grid grid-cols-3 gap-y-2 text-slate-700 dark:text-zinc-200" data-testid="employee-detail">
            {([
              ["Department", selected.department_name], ["Role", selected.designation],
              ["Salary", `₹${Number(selected.salary).toLocaleString("en-IN")}/mo`], ["Joined", selected.joining_date],
              ["Type", selected.employment_type?.replace("_", " ")], ["Phone", selected.phone], ["Personal email", selected.personal_email],
              ["Date of birth", selected.date_of_birth], ["Gender", selected.gender], ["Address", selected.address],
              ["Emergency contact", [selected.emergency_contact_name, selected.emergency_contact_phone].filter(Boolean).join(" · ")],
              ["Login", selected.login_status ? `${selected.login_email} (${selected.login_status}) · ${selected.access_role_name || "no role"}` : "No login yet"],
            ] as [string, string | null | undefined][]).map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-slate-500 dark:text-zinc-400">{k}</dt><dd className="col-span-2">{v || "-"}</dd></div>
            ))}
          </dl>
        </Modal>
      )}
    </main>
  );
}
