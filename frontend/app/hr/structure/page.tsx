"use client";

/**
 * Departments & Roles: set up once by someone with approval authority. Each
 * role (position) carries its fixed monthly salary and, optionally, the login
 * access role people in it receive. HR then only picks department -> role when
 * hiring; the salary follows automatically.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { SkeletonList } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";

type Department = { id: string; name: string };
type Position = { id: string; department_id: string; department_name: string | null; title: string; base_salary: string; access_role_id: string | null; access_role_name: string | null; employee_count: number };
type AccessRole = { id: string; name: string };

const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN")}`;

export default function StructurePage() {
  const { showToast } = useToast();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [roles, setRoles] = useState<AccessRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [deptName, setDeptName] = useState("");
  const [form, setForm] = useState({ department_id: "", title: "", base_salary: "", access_role_id: "" });
  const [editing, setEditing] = useState<Position | null>(null);
  const [edit, setEdit] = useState({ title: "", base_salary: "", access_role_id: "", apply: false });

  function loadAll() {
    Promise.allSettled([
      apiRequest<Department[]>("/api/hr/departments", { auth: true }).then(setDepartments),
      apiRequest<Position[]>("/api/hr/positions", { auth: true }).then(setPositions),
      apiRequest<AccessRole[]>("/api/core/roles", { auth: true }).then(setRoles).catch(() => setRoles([])),
    ]).finally(() => setLoading(false));
  }
  useEffect(loadAll, []);

  const fail = (e: unknown, d: string) => showToast(e instanceof Error ? e.message : d, "error");

  async function addDepartment(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/hr/departments", { method: "POST", auth: true, body: { name: deptName } });
      setDeptName(""); showToast("Department added", "success"); loadAll();
    } catch (err) { fail(err, "Could not add department"); }
  }

  async function addPosition(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/hr/positions", {
        method: "POST", auth: true,
        body: { department_id: form.department_id, title: form.title, base_salary: Number(form.base_salary), access_role_id: form.access_role_id || null },
      });
      setForm({ ...form, title: "", base_salary: "", access_role_id: "" });
      showToast("Role added", "success"); loadAll();
    } catch (err) { fail(err, "Could not add role"); }
  }

  function openEdit(p: Position) {
    setEditing(p);
    setEdit({ title: p.title, base_salary: String(Number(p.base_salary)), access_role_id: p.access_role_id || "", apply: false });
  }

  async function saveEdit() {
    if (!editing) return;
    try {
      await apiRequest(`/api/hr/positions/${editing.id}`, {
        method: "PATCH", auth: true,
        body: {
          title: edit.title, base_salary: Number(edit.base_salary),
          access_role_id: edit.access_role_id || null, clear_access_role: !edit.access_role_id,
          apply_to_existing: edit.apply,
        },
      });
      setEditing(null); showToast("Role updated", "success"); loadAll();
    } catch (err) { fail(err, "Could not save"); }
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Departments & Roles" description="Set these up first. Each role has a fixed monthly salary, so HR never types a salary when hiring." backHref="/hr" backLabel="← HR" />

      {loading ? <SkeletonList rows={3} /> : (
        <>
          <div className="grid md:grid-cols-2 gap-6 mb-8">
            <Card className="p-4">
              <form onSubmit={addDepartment} className="space-y-2">
                <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">1. Add department</h2>
                <Input placeholder="e.g. Sales, Operations, Finance" required value={deptName} onChange={(e) => setDeptName(e.target.value)} />
                <Button className="w-full">Add department</Button>
              </form>
            </Card>
            <Card className="p-4">
              <form onSubmit={addPosition} className="space-y-2">
                <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">2. Add a role inside a department</h2>
                <Select required aria-label="Department" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })}>
                  <option value="">Select department...</option>
                  {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </Select>
                <div className="grid sm:grid-cols-2 gap-2">
                  <Input placeholder="Role title, e.g. Sales Executive" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                  <Input placeholder="Monthly salary" type="number" min={0} required value={form.base_salary} onChange={(e) => setForm({ ...form, base_salary: e.target.value })} />
                </div>
                <Select aria-label="Login access role" value={form.access_role_id} onChange={(e) => setForm({ ...form, access_role_id: e.target.value })}>
                  <option value="">Create its own permission role automatically (recommended)</option>
                  {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </Select>
                <p className="text-xs text-slate-500 dark:text-zinc-400">Every role appears under its department in Settings &gt; Roles &amp; Permissions, where you tick what it can access. Choose an existing permission role here only if several roles should share the same access.</p>
                <Button className="w-full">Add role</Button>
              </form>
            </Card>
          </div>

          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {departments.map((d) => {
              const list = positions.filter((p) => p.department_id === d.id);
              return (
                <Card key={d.id} className="p-4" >
                  <div data-testid={`dept-${d.name}`}>
                    <h3 className="font-semibold text-slate-800 dark:text-white mb-2">{d.name}</h3>
                    <ul className="divide-y divide-slate-100 dark:divide-zinc-800">
                      {list.map((p) => (
                        <li key={p.id} className="py-2 flex justify-between items-start gap-2">
                          <div>
                            <p className="text-sm font-medium text-slate-800 dark:text-white">{p.title}</p>
                            <p className="text-xs text-slate-500 dark:text-zinc-400">{inr(p.base_salary)}/mo · {p.employee_count} employee{p.employee_count === 1 ? "" : "s"}</p>
                            <p className="text-xs text-slate-500 dark:text-zinc-400">
                              Login access: {p.access_role_name || "not set"}
                              {p.access_role_id && <> · <Link className="underline" href={`/settings/roles?role=${p.access_role_id}`}>Set permissions</Link></>}
                            </p>
                          </div>
                          <Button size="sm" variant="secondary" onClick={() => openEdit(p)}>Edit</Button>
                        </li>
                      ))}
                      {list.length === 0 && <li className="py-2 text-sm text-slate-400 dark:text-zinc-500">No roles yet.</li>}
                    </ul>
                  </div>
                </Card>
              );
            })}
            {departments.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No departments yet. Add the first one above.</p>}
          </div>
        </>
      )}

      {editing && (
        <Modal title={`Edit ${editing.title}`} onClose={() => setEditing(null)}>
          <div className="space-y-3">
            <Input label="Role title" value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} />
            <Input label="Monthly salary" type="number" min={0} value={edit.base_salary} onChange={(e) => setEdit({ ...edit, base_salary: e.target.value })} />
            <Select label="Login access role" value={edit.access_role_id} onChange={(e) => setEdit({ ...edit, access_role_id: e.target.value })}>
              <option value="">None</option>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </Select>
            <label className="flex items-start gap-2 text-sm text-slate-700 dark:text-zinc-200">
              <input type="checkbox" checked={edit.apply} onChange={(e) => setEdit({ ...edit, apply: e.target.checked })} className="mt-1" />
              Also move the {editing.employee_count} current employee(s) to this salary. Leave unticked to apply it to new hires only.
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button>
              <Button onClick={saveEdit}>Save</Button>
            </div>
          </div>
        </Modal>
      )}
    </main>
  );
}
