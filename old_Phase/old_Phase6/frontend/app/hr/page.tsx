"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";

type Department = { id: string; name: string };
type Employee = { id: string; name: string; designation: string | null; salary: string; department_id: string | null };
type LeaveRequest = { id: string; employee_id: string; leave_type: string; start_date: string; end_date: string; status: string };
type Payslip = { employee_id: string; gross: string; deductions: string; net_pay: string };
type PayrollRun = { id: string; month: number; year: number; status: string; payslips: Payslip[] };

export default function HRPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [leaves, setLeaves] = useState<LeaveRequest[]>([]);
  const [payrollRuns, setPayrollRuns] = useState<PayrollRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [deptForm, setDeptForm] = useState({ name: "" });
  const [empForm, setEmpForm] = useState({ name: "", designation: "", department_id: "", salary: "" });
  const [runForm, setRunForm] = useState({ month: String(new Date().getMonth() + 1), year: String(new Date().getFullYear()) });

  function loadAll() {
    apiRequest<Department[]>("/api/hr/departments", { auth: true }).then(setDepartments).catch(() => {});
    apiRequest<Employee[]>("/api/hr/employees", { auth: true }).then(setEmployees).catch((e) => setError(e.message));
    apiRequest<LeaveRequest[]>("/api/hr/leave-requests", { auth: true }).then(setLeaves).catch(() => {});
    apiRequest<PayrollRun[]>("/api/hr/payroll-runs", { auth: true }).then(setPayrollRuns).catch(() => {});
  }

  useEffect(loadAll, []);

  function employeeName(id: string) {
    return employees.find((e) => e.id === id)?.name || id.slice(0, 8);
  }

  async function addDepartment(e: React.FormEvent) {
    e.preventDefault();
    await apiRequest("/api/hr/departments", { method: "POST", auth: true, body: deptForm }).catch((err) => setError(err.message));
    setDeptForm({ name: "" });
    loadAll();
  }

  async function addEmployee(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/hr/employees", {
        method: "POST",
        auth: true,
        body: {
          name: empForm.name,
          designation: empForm.designation || null,
          department_id: empForm.department_id || null,
          salary: Number(empForm.salary),
        },
      });
      setEmpForm({ name: "", designation: "", department_id: "", salary: "" });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add employee");
    }
  }

  async function updateLeaveStatus(id: string, status: string) {
    await apiRequest(`/api/hr/leave-requests/${id}/status`, { method: "PATCH", auth: true, body: { status } }).catch((err) => setError(err.message));
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
      await apiRequest(`/api/hr/payroll-runs/${id}/process`, { method: "POST", auth: true });
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process payroll run");
    }
  }

  return (
    <main className="min-h-screen p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-slate-800">HR & Payroll</h1>
        <Link href="/dashboard" className="text-sm text-slate-500 underline">
          ← Dashboard
        </Link>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid md:grid-cols-2 gap-6 mb-8">
        <form onSubmit={addDepartment} className="bg-white rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 text-sm">Add Department</h2>
          <input
            placeholder="Department name"
            required
            value={deptForm.name}
            onChange={(e) => setDeptForm({ name: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
          <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
            Add Department
          </button>
        </form>

        <form onSubmit={addEmployee} className="bg-white rounded-xl shadow-sm p-4 space-y-2">
          <h2 className="font-semibold text-slate-700 text-sm">Add Employee</h2>
          <input
            placeholder="Name"
            required
            value={empForm.name}
            onChange={(e) => setEmpForm({ ...empForm, name: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              placeholder="Designation"
              value={empForm.designation}
              onChange={(e) => setEmpForm({ ...empForm, designation: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder="Monthly salary"
              type="number"
              required
              value={empForm.salary}
              onChange={(e) => setEmpForm({ ...empForm, salary: e.target.value })}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <select
            value={empForm.department_id}
            onChange={(e) => setEmpForm({ ...empForm, department_id: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">No department</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
          <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
            Add Employee
          </button>
        </form>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        <section>
          <h2 className="font-semibold text-slate-700 mb-3">Employees</h2>
          <div className="bg-white rounded-lg shadow-sm divide-y">
            {employees.map((e) => (
              <div key={e.id} className="p-3 text-sm">
                <p className="text-slate-800 font-medium">{e.name}</p>
                <p className="text-xs text-slate-500">{e.designation || "—"} · ₹{Number(e.salary).toLocaleString("en-IN")}/mo</p>
              </div>
            ))}
            {employees.length === 0 && <p className="p-3 text-sm text-slate-400">No employees yet.</p>}
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 mb-3">Leave Requests</h2>
          <div className="space-y-2">
            {leaves.map((l) => (
              <div key={l.id} className="bg-white rounded-lg shadow-sm p-3 text-sm">
                <p className="text-slate-800 font-medium">{employeeName(l.employee_id)}</p>
                <p className="text-xs text-slate-500">{l.leave_type} · {l.start_date} → {l.end_date} · {l.status}</p>
                {l.status === "pending" && (
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={() => updateLeaveStatus(l.id, "approved")}
                      className="text-xs bg-slate-800 text-white px-3 py-1 rounded-lg hover:bg-slate-700"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => updateLeaveStatus(l.id, "rejected")}
                      className="text-xs border border-slate-300 text-slate-600 px-3 py-1 rounded-lg hover:bg-slate-100"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>
            ))}
            {leaves.length === 0 && <p className="text-sm text-slate-400">No leave requests yet.</p>}
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-slate-700 mb-3">Payroll</h2>
          <form onSubmit={createPayrollRun} className="bg-white rounded-xl shadow-sm p-3 space-y-2 mb-3">
            <div className="grid grid-cols-2 gap-2">
              <input
                placeholder="Month (1-12)"
                type="number"
                min={1}
                max={12}
                value={runForm.month}
                onChange={(e) => setRunForm({ ...runForm, month: e.target.value })}
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
              />
              <input
                placeholder="Year"
                type="number"
                value={runForm.year}
                onChange={(e) => setRunForm({ ...runForm, year: e.target.value })}
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
              Create Payroll Run
            </button>
          </form>

          <div className="space-y-2">
            {payrollRuns.map((run) => (
              <div key={run.id} className="bg-white rounded-lg shadow-sm p-3 text-sm">
                <div className="flex justify-between items-center">
                  <p className="text-slate-800 font-medium">{run.month}/{run.year}</p>
                  <span className="text-xs text-slate-500">{run.status}</span>
                </div>
                {run.status !== "processed" ? (
                  <button
                    onClick={() => processPayrollRun(run.id)}
                    className="mt-2 text-xs bg-slate-800 text-white px-3 py-1.5 rounded-lg hover:bg-slate-700"
                  >
                    Process Payroll
                  </button>
                ) : (
                  <div className="mt-2 space-y-1">
                    {run.payslips.map((p, i) => (
                      <p key={i} className="text-xs text-slate-500 flex justify-between">
                        <span>{employeeName(p.employee_id)}</span>
                        <span>Net ₹{Number(p.net_pay).toLocaleString("en-IN")}</span>
                      </p>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {payrollRuns.length === 0 && <p className="text-sm text-slate-400">No payroll runs yet.</p>}
          </div>
        </section>
      </div>
    </main>
  );
}
