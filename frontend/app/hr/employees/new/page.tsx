"use client";

/**
 * The employee application form. HR transcribes the paper form here: picks
 * department, then a role from that department (salary shows automatically and
 * cannot be typed), and fills the personal details. On save an employee code is
 * generated; the same page then offers to create the person's login.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui";
import { useToast } from "@/components/Toast";

type Department = { id: string; name: string };
type Position = { id: string; department_id: string; title: string; base_salary: string; access_role_name: string | null };
type Employee = { id: string; employee_code: string; name: string; designation: string | null; department_name: string | null; salary: string; login_status: string | null; login_email: string | null; access_role_name: string | null };

const inr = (v: string | number) => `₹${Number(v).toLocaleString("en-IN")}`;
const blank = {
  name: "", department_id: "", position_id: "", joining_date: new Date().toISOString().slice(0, 10), employment_type: "full_time",
  date_of_birth: "", gender: "", phone: "", personal_email: "", address: "", emergency_contact_name: "", emergency_contact_phone: "",
};

export default function NewEmployeePage() {
  const { showToast } = useToast();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [f, setF] = useState(blank);
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<Employee | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);

  useEffect(() => {
    apiRequest<Department[]>("/api/hr/departments", { auth: true }).then(setDepartments).catch(() => {});
    apiRequest<Position[]>("/api/hr/positions", { auth: true }).then(setPositions).catch(() => {});
  }, []);

  const deptPositions = useMemo(() => positions.filter((p) => p.department_id === f.department_id), [positions, f.department_id]);
  const chosen = positions.find((p) => p.id === f.position_id);
  const set = (k: keyof typeof blank, v: string) => setF((cur) => ({ ...cur, [k]: v, ...(k === "department_id" ? { position_id: "" } : {}) }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const body: Record<string, unknown> = { ...f };
    for (const k of Object.keys(body)) if (body[k] === "") body[k] = null;
    try {
      const emp = await apiRequest<Employee>("/api/hr/employees", { method: "POST", auth: true, body });
      setCreated(emp);
      setLoginEmail(f.personal_email || "");
      showToast(`Employee ${emp.employee_code} created`, "success");
    } catch (err) { showToast(err instanceof Error ? err.message : "Could not save", "error"); }
    setSaving(false);
  }

  async function createLogin() {
    if (!created) return;
    setLoginBusy(true);
    try {
      const emp = await apiRequest<Employee>(`/api/hr/employees/${created.id}/create-login`, { method: "POST", auth: true, body: { email: loginEmail.trim() } });
      setCreated(emp);
      showToast("Login created. An invite email was sent.", "success");
    } catch (err) { showToast(err instanceof Error ? err.message : "Could not create login", "error"); }
    setLoginBusy(false);
  }

  if (created) {
    return (
      <main className="min-h-screen p-8 max-w-2xl">
        <PageHeader title="Employee created" backHref="/hr" backLabel="← HR" />
        <Card className="p-5 space-y-3" >
          <div data-testid="created">
            <p className="text-sm text-slate-500 dark:text-zinc-400">Employee code</p>
            <p className="text-2xl font-bold text-slate-900 dark:text-white" data-testid="emp-code">{created.employee_code}</p>
            <p className="mt-2 text-slate-800 dark:text-zinc-100">{created.name} · {created.designation} · {created.department_name}</p>
            <p className="text-sm text-slate-500 dark:text-zinc-400">Salary from the role: {inr(created.salary)}/month</p>
          </div>
          <div className="border-t border-slate-200 dark:border-zinc-700 pt-3">
            <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm mb-1">System login</h2>
            {created.login_status ? (
              <p className="text-sm text-slate-700 dark:text-zinc-200" data-testid="login-state">
                {created.login_email} · access role <b>{created.access_role_name}</b> · {created.login_status}. It appears in Settings &gt; Users.
              </p>
            ) : (
              <div className="space-y-2">
                <p className="text-xs text-slate-500 dark:text-zinc-400">Optional. Sends an invite with the access role set on this person&apos;s role. Needs the &quot;Manage Roles &amp; Permissions&quot; permission.</p>
                <Input aria-label="Login email" type="email" placeholder="work email" value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} />
                <Button onClick={createLogin} disabled={loginBusy || !loginEmail.includes("@")}>{loginBusy ? "Creating…" : "Create login & send invite"}</Button>
              </div>
            )}
          </div>
          <div className="flex gap-2 pt-2">
            <Button variant="secondary" onClick={() => { setCreated(null); setF(blank); }}>Add another employee</Button>
            <Link href="/hr" className="px-4 py-2 text-sm rounded-lg bg-slate-800 dark:bg-zinc-100 text-white dark:text-zinc-950">Back to HR</Link>
          </div>
        </Card>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-8 max-w-3xl">
      <PageHeader title="New employee" description="Copy the details from the applicant's form. The employee code is generated when you save." backHref="/hr" backLabel="← HR" />
      {departments.length === 0 && (
        <p className="text-sm rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800/60 text-amber-800 dark:text-amber-200 p-2 mb-4">
          No departments or roles exist yet. An administrator must set them up first under <Link className="underline" href="/hr/structure">Departments &amp; Roles</Link>.
        </p>
      )}
      <form onSubmit={submit} className="space-y-6">
        <Card className="p-4 space-y-3">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Position</h2>
          <div className="grid sm:grid-cols-2 gap-3">
            <Select label="Department" id="dept" required value={f.department_id} onChange={(e) => set("department_id", e.target.value)}>
              <option value="">Select department...</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
            <Select label="Role" id="role" required disabled={!f.department_id} value={f.position_id} onChange={(e) => set("position_id", e.target.value)}>
              <option value="">{f.department_id ? "Select role..." : "Choose a department first"}</option>
              {deptPositions.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </Select>
          </div>
          <div className="rounded-lg bg-slate-50 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 p-3 text-sm" data-testid="salary-box">
            <span className="text-slate-500 dark:text-zinc-400">Monthly salary (fixed by the role): </span>
            <b className="text-slate-900 dark:text-white">{chosen ? inr(chosen.base_salary) : "-"}</b>
            {chosen && <span className="text-xs text-slate-500 dark:text-zinc-400 block mt-1">Login access when created: {chosen.access_role_name || "no access role set on this role"}</span>}
          </div>
        </Card>

        <Card className="p-4 space-y-3">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Personal details</h2>
          <Input label="Full name" id="name" required value={f.name} onChange={(e) => set("name", e.target.value)} />
          <div className="grid sm:grid-cols-3 gap-3">
            <Input label="Date of birth" id="dob" type="date" value={f.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} />
            <Select label="Gender" id="gender" value={f.gender} onChange={(e) => set("gender", e.target.value)}>
              <option value="">Not stated</option><option value="male">Male</option><option value="female">Female</option><option value="other">Other</option>
            </Select>
            <Input label="Phone" id="phone" value={f.phone} onChange={(e) => set("phone", e.target.value)} />
          </div>
          <Input label="Personal email" id="pemail" type="email" value={f.personal_email} onChange={(e) => set("personal_email", e.target.value)} />
          <label className="block text-sm text-slate-600 dark:text-zinc-300">Address
            <textarea rows={2} value={f.address} onChange={(e) => set("address", e.target.value)} className="mt-1 w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm" />
          </label>
        </Card>

        <Card className="p-4 space-y-3">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Employment and emergency contact</h2>
          <div className="grid sm:grid-cols-2 gap-3">
            <Input label="Joining date" id="join" type="date" value={f.joining_date} onChange={(e) => set("joining_date", e.target.value)} />
            <Select label="Employment type" id="etype" value={f.employment_type} onChange={(e) => set("employment_type", e.target.value)}>
              <option value="full_time">Full time</option><option value="part_time">Part time</option><option value="contract">Contract</option><option value="intern">Intern</option>
            </Select>
            <Input label="Emergency contact name" id="ecn" value={f.emergency_contact_name} onChange={(e) => set("emergency_contact_name", e.target.value)} />
            <Input label="Emergency contact phone" id="ecp" value={f.emergency_contact_phone} onChange={(e) => set("emergency_contact_phone", e.target.value)} />
          </div>
        </Card>
        <Button disabled={saving || !f.position_id || !f.name.trim()} className="w-full">{saving ? "Saving…" : "Save employee & generate code"}</Button>
      </form>
    </main>
  );
}
