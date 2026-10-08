"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader, Button, Input, Select, Card } from "@/components/ui";
import { ConfirmModal } from "@/components/Modal";
import { useToast } from "@/components/Toast";
import { NavLink } from "@/components/NavLink";
import { Palette, Settings2, ChevronDown, ChevronRight } from "lucide-react";
import { isChecked, toggleDraft, planChanges, type Draft } from "@/lib/permissionDraft";

type Role = { id: string; org_id: string; name: string };
type TreePosition = { position_id: string; title: string; role_id: string; role_name: string; user_count: number; employee_count: number };
type TreeDept = { id: string; name: string; positions: TreePosition[] };
type RoleTree = { departments: TreeDept[]; other_roles: { id: string; name: string; user_count: number }[] };
type Permission = { id: string; role_id: string; module: string; action: string };
type ManagedUser = {
  id: string;
  name: string;
  email: string;
  role_id: string | null;
  role_name: string | null;
  status: string;
  created_at: string;
};

// Same module list signup seeds a brand-new Admin role with (see
// app/api/routes/auth.py) — kept in sync so this screen never offers a
// module the backend doesn't actually recognize.
const MODULES = [
  "core", "dashboard", "crm", "sales", "procurement", "inventory",
  "finance", "hr", "projects", "documents", "reports", "custom_fields", "intelligence", "workpage",
];
const ACTIONS = ["view", "create", "edit", "delete", "approve"] as const;
// Ask Data only uses two of the five ticks; the other three are meaningless for it, so they are not offered.
const ASK_DATA_ACTIONS: readonly string[] = ["view", "approve"];

export default function RolesSettingsPage() {
  const { showToast } = useToast();
  const [roles, setRoles] = useState<Role[]>([]);
  const [tree, setTree] = useState<RoleTree>({ departments: [], other_roles: [] });
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(new Set());
  const [bulkRoleId, setBulkRoleId] = useState("");
  const [bulkResult, setBulkResult] = useState<{ updated: string[]; skipped: { user_id: string; reason: string }[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [permissionsLoading, setPermissionsLoading] = useState(false);
  const [showManageAccessConfirm, setShowManageAccessConfirm] = useState(false);
  // STAGED edits: nothing below is saved until the admin presses Save.
  const [draft, setDraft] = useState<Draft>({});                       // permission ticks, per selected role
  const [savingPermissions, setSavingPermissions] = useState(false);
  const [pendingRoles, setPendingRoles] = useState<Record<string, string>>({}); // userId -> wanted role id ("" = none)
  const [savingRoleFor, setSavingRoleFor] = useState<string | null>(null);

  const [roleForm, setRoleForm] = useState({ name: "" });
  const [userForm, setUserForm] = useState({ name: "", email: "", password: "", role_id: "" });
  const [inviteForm, setInviteForm] = useState({ name: "", email: "", role_id: "" });
  const [addUserMode, setAddUserMode] = useState<"invite" | "password">("invite");
  const [resendStatus, setResendStatus] = useState<Record<string, "idle" | "sending" | "sent">>({});

  async function restoreDefaults() {
    try {
      const made = await apiRequest<{ departments: number; roles: number; permissions: number }>("/api/core/roles/defaults/restore", { method: "POST", auth: true });
      showToast(made.roles + made.departments === 0 ? "All standard departments and roles are already there." : `Added ${made.departments} department(s) and ${made.roles} role(s) with their starting permissions.`, "success");
      loadRoles();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not restore the defaults", "error");
    }
  }

  function loadRoles() {
    // The tree call also creates any missing access role for departments' job roles, so load it first.
    apiRequest<RoleTree>("/api/core/roles/tree", { auth: true })
      .then(setTree)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load departments"))
      .finally(() => {
        apiRequest<Role[]>("/api/core/roles", { auth: true })
          .then(setRoles)
          .catch((err) => setError(err instanceof Error ? err.message : "Failed to load roles"));
      });
  }

  // <option>s for every role picker: grouped Department > job role, then roles that belong to no department.
  function roleOptions() {
    return (
      <>
        {tree.departments.filter((d) => d.positions.length > 0).map((d) => (
          <optgroup key={d.id} label={d.name}>
            {d.positions.map((p) => (
              <option key={`${d.id}-${p.position_id}`} value={p.role_id}>{p.title}</option>
            ))}
          </optgroup>
        ))}
        {tree.other_roles.length > 0 && (
          <optgroup label="Other roles">
            {tree.other_roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </optgroup>
        )}
      </>
    );
  }

  function loadUsers() {
    apiRequest<ManagedUser[]>("/api/core/users", { auth: true })
      .then(setUsers)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load users"));
  }

  function loadPermissions(roleId: string) {
    setPermissionsLoading(true);
    apiRequest<Permission[]>(`/api/core/roles/${roleId}/permissions`, { auth: true })
      .then(setPermissions)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load permissions"))
      .finally(() => setPermissionsLoading(false));
  }

  useEffect(() => {
    loadRoles();
    loadUsers();
    try {
      const wanted = new URLSearchParams(window.location.search).get("role");
      if (wanted) setSelectedRoleId(wanted);
    } catch { /* no query string available */ }
  }, []);

  useEffect(() => {
    if (selectedRoleId) loadPermissions(selectedRoleId);
    else setPermissions([]);
  }, [selectedRoleId]);

  async function handleCreateRole(e: React.FormEvent) {
    e.preventDefault();
    if (pendingCount > 0 && !window.confirm("You have unsaved permission changes. Discard them and create the new role?")) return;
    setError(null);
    try {
      const role = await apiRequest<Role>("/api/core/roles", {
        method: "POST", auth: true, body: { name: roleForm.name },
      });
      setRoleForm({ name: "" });
      loadRoles();
      setSelectedRoleId(role.id); // jump straight to managing its permissions
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create role");
    }
  }

  function hasPermission(module: string, action: string): Permission | undefined {
    return permissions.find((p) => p.module === module && p.action === action);
  }

  function hasManageAccess(): boolean {
    return !!hasPermission("core", "manage_access");
  }

  function handleManageAccessToggle() {
    if (hasManageAccess()) {
      // Revoking is already protected server-side by the last-admin
      // guard, but still worth a confirm here since it's a real change
      // in what this role can do - not because the button needs a
      // second click to feel safe, but because undoing this by hand
      // later means re-granting it, which is exactly the mistake this
      // whole feature exists to prevent.
      togglePermission("core", "manage_access");
    } else {
      setShowManageAccessConfirm(true);
    }
  }

  async function togglePermission(module: string, action: string) {
    if (!selectedRoleId) return;
    setError(null);
    const existing = hasPermission(module, action);
    try {
      if (existing) {
        await apiRequest(`/api/core/roles/${selectedRoleId}/permissions/${existing.id}`, {
          method: "DELETE", auth: true,
        });
        setPermissions((prev) => prev.filter((p) => p.id !== existing.id));
      } else {
        const created = await apiRequest<Permission>(`/api/core/roles/${selectedRoleId}/permissions`, {
          method: "POST", auth: true, body: { module, action },
        });
        setPermissions((prev) => [...prev, created]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update permission");
    }
  }

  // ---- staged permission edits (the grid) --------------------------------------------
  const pendingCount = Object.keys(draft).length;
  const pendingRoleCount = Object.keys(pendingRoles).length;

  function stagePermission(module: string, action: string) {
    setDraft((d) => toggleDraft(permissions, d, module, action));
  }

  function discardPermissionChanges() {
    setDraft({});
  }

  async function savePermissionChanges() {
    if (!selectedRoleId) return;
    const plan = planChanges(permissions, draft);
    const total = plan.adds.length + plan.removes.length;
    if (total === 0) {
      setDraft({});
      return;
    }
    setSavingPermissions(true);
    setError(null);
    const failures: string[] = [];
    // Additions first, then removals: if something is interrupted, the role is left with
    // too much rather than too little, and the grid below always shows what is really saved.
    for (const a of plan.adds) {
      try {
        await apiRequest(`/api/core/roles/${selectedRoleId}/permissions`, {
          method: "POST", auth: true, body: { module: a.module, action: a.action },
        });
      } catch (err) {
        failures.push(`${a.module} ${a.action}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }
    for (const r of plan.removes) {
      try {
        await apiRequest(`/api/core/roles/${selectedRoleId}/permissions/${r.id}`, { method: "DELETE", auth: true });
      } catch (err) {
        failures.push(`${r.module} ${r.action}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }
    setDraft({});
    loadPermissions(selectedRoleId); // always show the server's truth, whatever happened above
    setSavingPermissions(false);
    if (failures.length === 0) {
      showToast(`Saved ${total} permission change${total === 1 ? "" : "s"}.`, "success");
    } else {
      setError(`Saved ${total - failures.length} of ${total} changes. Not saved: ${failures.join("; ")}`);
    }
  }

  function selectRole(roleId: string) {
    if (roleId === selectedRoleId) return;
    if (pendingCount > 0 && !window.confirm("You have unsaved permission changes. Discard them and switch roles?")) return;
    setDraft({});
    setSelectedRoleId(roleId);
  }

  // ---- staged role change for one user ------------------------------------------------
  function stageUserRole(user: ManagedUser, wanted: string) {
    setPendingRoles((prev) => {
      const next = { ...prev };
      if (wanted === (user.role_id ?? "")) delete next[user.id]; // back to the saved role: no change
      else next[user.id] = wanted;
      return next;
    });
  }

  function discardUserRole(userId: string) {
    setPendingRoles((prev) => {
      const next = { ...prev };
      delete next[userId];
      return next;
    });
  }

  async function saveUserRole(userId: string) {
    const wanted = pendingRoles[userId];
    if (wanted === undefined) return;
    setSavingRoleFor(userId);
    setError(null);
    try {
      await apiRequest(`/api/core/users/${userId}/role`, {
        method: "PATCH", auth: true, body: { role_id: wanted || null },
      });
      discardUserRole(userId);
      loadUsers();
      showToast("Role updated.", "success");
    } catch (err) {
      // Keep the staged choice so the admin can see what was attempted and cancel it.
      setError(err instanceof Error ? err.message : "Failed to change user's role");
    } finally {
      setSavingRoleFor(null);
    }
  }

  // Staged ticks belong to one role, so they are dropped whenever the selected role changes by any route.
  useEffect(() => {
    setDraft({});
  }, [selectedRoleId]);

  // Warn before leaving the page with anything unsaved.
  useEffect(() => {
    if (pendingCount === 0 && pendingRoleCount === 0) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [pendingCount, pendingRoleCount]);

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await apiRequest("/api/core/users", {
        method: "POST",
        auth: true,
        body: {
          name: userForm.name,
          email: userForm.email,
          password: userForm.password,
          role_id: userForm.role_id || null,
        },
      });
      setUserForm({ name: "", email: "", password: "", role_id: "" });
      loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    }
  }

  async function handleSendInvite(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await apiRequest("/api/core/invites", {
        method: "POST",
        auth: true,
        body: {
          name: inviteForm.name,
          email: inviteForm.email,
          role_id: inviteForm.role_id || null,
        },
      });
      setInviteForm({ name: "", email: "", role_id: "" });
      loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invite");
    }
  }

  async function handleResendInvite(userId: string) {
    setResendStatus((prev) => ({ ...prev, [userId]: "sending" }));
    try {
      await apiRequest(`/api/core/invites/${userId}/resend`, { method: "POST", auth: true });
      setResendStatus((prev) => ({ ...prev, [userId]: "sent" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resend invite");
      setResendStatus((prev) => ({ ...prev, [userId]: "idle" }));
    }
  }

  async function handleReset2fa(u: ManagedUser) {
    if (!window.confirm(`Reset two-step verification for ${u.email}? They will set up a new authenticator at their next Admin sign-in.`)) return;
    try {
      await apiRequest(`/api/core/users/${u.id}/reset-2fa`, { method: "POST", auth: true });
      showToast(`Authenticator reset for ${u.email}`, "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset two-step verification");
    }
  }

  function toggleUserSelection(id: string) {
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleBulkRoleAssign() {
    if (selectedUserIds.size === 0) return;
    setError(null);
    setBulkResult(null);
    try {
      const result = await apiRequest<{ updated: string[]; skipped: { user_id: string; reason: string }[] }>(
        "/api/core/users/bulk-role-assign",
        { method: "POST", auth: true, body: { user_ids: Array.from(selectedUserIds), role_id: bulkRoleId || null } }
      );
      setBulkResult(result);
      setSelectedUserIds(new Set());
      loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk role assignment failed");
    }
  }

  const selectedRole = roles.find((r) => r.id === selectedRoleId);
  const selectedLabel = (() => {
    for (const d of tree.departments) {
      const p = d.positions.find((x) => x.role_id === selectedRoleId);
      if (p) return `${d.name} › ${p.title}`;
    }
    return selectedRole?.name ?? "";
  })();

  return (
    <main className="min-h-screen p-8">
      <PageHeader
        title="Roles & Permissions"
        actions={
          <div className="flex items-center gap-2">
            <NavLink href="/settings/appearance" icon={Palette}>Appearance</NavLink>
            <NavLink href="/settings/custom-fields" icon={Settings2}>Custom Fields</NavLink>
          </div>
        }
      />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Roles: departments with their job roles (from the Departments & Roles page), then free-standing roles */}
        <Card className="p-4">
          <div className="flex items-center justify-between mb-1">
            <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Roles by department</h2>
            <NavLink href="/hr/structure" icon={Settings2}>Departments &amp; Roles</NavLink>
          </div>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mb-3">
            Every job role added under a department appears here automatically. Pick one to set what it can access.
            New organizations start with standard departments and roles with sensible starting permissions; all of it can be changed or deleted.
            {" "}<button type="button" onClick={restoreDefaults} data-testid="restore-defaults" className="underline text-indigo-600 dark:text-indigo-400">Restore any missing standard roles</button>
          </p>

          <div data-testid="role-tree" className="space-y-1 mb-4">
            {tree.departments.map((d) => {
              const open = !collapsed.has(d.id);
              return (
                <div key={d.id} data-testid={`tree-dept-${d.name}`}>
                  <button
                    type="button"
                    aria-expanded={open}
                    onClick={() => setCollapsed((prev) => { const n = new Set(prev); if (n.has(d.id)) n.delete(d.id); else n.add(d.id); return n; })}
                    className="w-full flex items-center gap-1 py-1.5 px-1 text-sm font-semibold text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-800 rounded-lg"
                  >
                    {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                    {d.name}
                    <span className="ml-auto text-xs font-normal text-slate-400 dark:text-zinc-500">{d.positions.length} role{d.positions.length === 1 ? "" : "s"}</span>
                  </button>
                  {open && (
                    <div className="ml-5 border-l border-slate-200 dark:border-zinc-700 pl-2">
                      {d.positions.map((p) => (
                        <button
                          key={p.position_id}
                          data-testid={`tree-role-${d.name}-${p.title}`}
                          onClick={() => selectRole(p.role_id)}
                          className={`w-full text-left py-1.5 px-2 text-sm rounded-lg flex items-center gap-2 ${
                            selectedRoleId === p.role_id ? "bg-slate-100 dark:bg-zinc-800 font-medium text-slate-800 dark:text-white" : "text-slate-600 dark:text-zinc-300 hover:bg-slate-50 dark:hover:bg-zinc-800"
                          }`}
                        >
                          <span>{p.title}</span>
                          <span className="ml-auto text-xs text-slate-400 dark:text-zinc-500">
                            {p.user_count} login{p.user_count === 1 ? "" : "s"}
                          </span>
                        </button>
                      ))}
                      {d.positions.length === 0 && (
                        <p className="text-xs text-slate-400 dark:text-zinc-500 py-1.5 px-2">No job roles yet. Add them on the Departments &amp; Roles page.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            {tree.departments.length === 0 && (
              <p className="text-sm text-slate-400 dark:text-zinc-500 py-1">No departments yet. Create them on the Departments &amp; Roles page.</p>
            )}
          </div>

          <h3 className="font-semibold text-slate-700 dark:text-zinc-200 text-xs uppercase tracking-wide mb-2">Other roles</h3>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mb-2">Roles that do not belong to a department, such as Admin.</p>
          <div className="divide-y mb-3" data-testid="other-roles">
            {tree.other_roles.map((role) => (
              <button
                key={role.id}
                onClick={() => selectRole(role.id)}
                className={`w-full text-left py-2 px-2 text-sm rounded-lg flex items-center ${
                  selectedRoleId === role.id ? "bg-slate-100 dark:bg-zinc-800 font-medium text-slate-800 dark:text-white" : "text-slate-600 dark:text-zinc-300 hover:bg-slate-50 dark:hover:bg-zinc-800"
                }`}
              >
                {role.name}
                <span className="ml-auto text-xs text-slate-400 dark:text-zinc-500">{role.user_count} login{role.user_count === 1 ? "" : "s"}</span>
              </button>
            ))}
            {tree.other_roles.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500 py-2">None.</p>}
          </div>
          <form onSubmit={handleCreateRole} className="flex gap-2">
            <Input
              placeholder="New standalone role, e.g. Auditor"
              aria-label="New standalone role"
              value={roleForm.name}
              onChange={(e) => setRoleForm({ name: e.target.value })}
              required
            />
            <Button type="submit" size="sm">Add</Button>
          </form>
        </Card>

        {/* Permission matrix for the selected role */}
        <Card className="p-4">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm mb-3">
            {selectedRole ? `Permissions — ${selectedLabel}` : "Select a role to manage its permissions"}
          </h2>

          {!selectedRole && (
            <p className="text-sm text-slate-400 dark:text-zinc-500">Pick a role on the left, then toggle what it can do below.</p>
          )}

          {selectedRole && permissionsLoading && <p className="text-sm text-slate-400 dark:text-zinc-500">Loading…</p>}

          {selectedRole && !permissionsLoading && (
            <div
              className={`mb-4 p-3 rounded-lg border flex justify-between items-center bg-slate-50 dark:bg-zinc-800 border-slate-200 dark:border-zinc-700 ${hasManageAccess() ? "border-l-4 border-l-amber-500" : ""}`}
            >
              <div>
                <p className="text-sm font-semibold text-slate-800 dark:text-white">
                  Manage Roles &amp; Permissions
                  {hasManageAccess() && (
                    <span className="ml-2 text-[10px] font-semibold uppercase tracking-wide bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 px-1.5 py-0.5 rounded-full align-middle">Granted</span>
                  )}
                </p>
                <p className="text-xs text-slate-600 dark:text-zinc-300 mt-0.5 max-w-md">
                  Full control over every role and user in this organization — create/change roles,
                  grant or revoke ANY permission, and assign any user (including this one) as Admin.
                  This is separate from the checkboxes below on purpose: it is not the same kind of
                  thing as editing business data.
                </p>
              </div>
              <Button
                size="sm"
                variant={hasManageAccess() ? "danger" : "primary"}
                onClick={handleManageAccessToggle}
              >
                {hasManageAccess() ? "Revoke" : "Grant"}
              </Button>
            </div>
          )}

          {selectedRole && !permissionsLoading && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-400 dark:text-zinc-500 uppercase">
                    <th className="py-1 pr-2">Module</th>
                    {ACTIONS.map((action) => (
                      <th key={action} className="py-1 px-1 text-center">{action}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MODULES.map((module) => (
                    <tr key={module} className="border-t border-slate-100 dark:border-zinc-800">
                      <td className="py-1.5 pr-2 text-slate-700 dark:text-zinc-200">{module}</td>
                      {ACTIONS.map((action) => (
                        <td key={action} className="py-1.5 px-1 text-center">
                          {module === "intelligence" && !ASK_DATA_ACTIONS.includes(action) ? (
                            <span className="text-slate-300 dark:text-zinc-700" title="Not used by Ask Data">—</span>
                          ) : (
                            <input
                              type="checkbox"
                              checked={isChecked(permissions, draft, module, action)}
                              onChange={() => stagePermission(module, action)}
                            />
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-slate-500 dark:text-zinc-500">
                <span className="font-medium">intelligence (Ask Data):</span> <b>view</b> lets this role ask about the modules it
                can already open. <b>approve</b> also lets it ask about salary and payroll, and only works together with HR access.
              </p>
            </div>
          )}

          {selectedRole && pendingCount > 0 && (
            <div
              className="sticky bottom-4 mt-4 flex items-center justify-between gap-3 rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950 px-3 py-2 shadow-md"
              role="status"
              data-testid="permission-save-bar"
            >
              <span className="text-xs text-amber-800 dark:text-amber-300">
                {pendingCount} unsaved change{pendingCount === 1 ? "" : "s"} for {selectedRole.name}
              </span>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={discardPermissionChanges} disabled={savingPermissions}>
                  Discard
                </Button>
                <Button size="sm" onClick={savePermissionChanges} disabled={savingPermissions}>
                  {savingPermissions ? "Saving…" : "Save changes"}
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Users */}
      <Card className="p-4 max-w-3xl">
        <div className="flex justify-between items-center mb-3">
          <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Users</h2>
          <div className="flex text-xs rounded-lg overflow-hidden border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white">
            <button
              onClick={() => setAddUserMode("invite")}
              className={`px-3 py-1.5 ${addUserMode === "invite" ? "bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900" : "bg-white dark:bg-zinc-900 text-slate-600 dark:text-zinc-300"}`}
            >
              Send Invite
            </button>
            <button
              onClick={() => setAddUserMode("password")}
              className={`px-3 py-1.5 ${addUserMode === "password" ? "bg-slate-800 dark:bg-zinc-200 text-white dark:text-zinc-900" : "bg-white dark:bg-zinc-900 text-slate-600 dark:text-zinc-300"}`}
            >
              Set Password Directly
            </button>
          </div>
        </div>

        {addUserMode === "invite" ? (
          <form onSubmit={handleSendInvite} className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
            <p className="text-xs text-slate-500 dark:text-zinc-500 sm:col-span-2">
              Sends a real email with a link — they&apos;ll set their own password. Nothing to type in
              for them here.
            </p>
            <Input
              placeholder="Name"
              value={inviteForm.name}
              onChange={(e) => setInviteForm({ ...inviteForm, name: e.target.value })}
              required
            />
            <Input
              type="email"
              placeholder="Email"
              value={inviteForm.email}
              onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
              required
            />
            <Select
              value={inviteForm.role_id}
              onChange={(e) => setInviteForm({ ...inviteForm, role_id: e.target.value })}
              className="sm:col-span-2"
            >
              <option value="">No role assigned</option>
              {roleOptions()}
            </Select>
            <Button type="submit" className="sm:col-span-2">Send Invite</Button>
          </form>
        ) : (
          <form onSubmit={handleCreateUser} className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
            <Input
              placeholder="Name"
              value={userForm.name}
              onChange={(e) => setUserForm({ ...userForm, name: e.target.value })}
              required
            />
            <Input
              type="email"
              placeholder="Email"
              value={userForm.email}
              onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
              required
            />
            <Input
              type="password"
              placeholder="Password (min 8 characters)"
              value={userForm.password}
              onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
              required
              minLength={8}
            />
            <Select
              value={userForm.role_id}
              onChange={(e) => setUserForm({ ...userForm, role_id: e.target.value })}
            >
              <option value="">No role assigned</option>
              {roleOptions()}
            </Select>
            <Button type="submit" className="sm:col-span-2">Add User</Button>
          </form>
        )}

        {selectedUserIds.size > 0 && (
          <div className="flex items-center gap-2 mb-3 bg-slate-50 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-800 rounded-lg p-2 flex-wrap">
            <span className="text-xs text-slate-600 dark:text-zinc-300">{selectedUserIds.size} selected</span>
            <Select value={bulkRoleId} onChange={(e) => setBulkRoleId(e.target.value)} className="w-48">
              <option value="">No role assigned</option>
              {roleOptions()}
            </Select>
            <Button size="sm" onClick={handleBulkRoleAssign}>Assign Role to Selected</Button>
          </div>
        )}

        {bulkResult && (
          <div className="text-xs bg-slate-50 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-800 rounded-lg p-2 mb-3">
            <p className="text-slate-700 dark:text-zinc-200">Updated {bulkResult.updated.length}, skipped {bulkResult.skipped.length}.</p>
            {bulkResult.skipped.map((s) => (
              <p key={s.user_id} className="text-red-600">{s.reason}</p>
            ))}
          </div>
        )}

        <div className="divide-y">
          {users.map((u) => (
            <div key={u.id} className="py-2 flex justify-between items-center text-sm">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selectedUserIds.has(u.id)}
                  onChange={() => toggleUserSelection(u.id)}
                />
                <div>
                  <p className="text-slate-800 dark:text-white font-medium">
                    {u.name}
                    {u.status === "invited" && (
                      <span className="ml-2 text-[10px] bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300 px-1.5 py-0.5 rounded-full align-middle">
                        Invite pending
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-zinc-500">{u.email}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {u.status === "invited" && (
                  <button
                    onClick={() => handleResendInvite(u.id)}
                    disabled={resendStatus[u.id] === "sending"}
                    className="text-xs text-slate-500 dark:text-zinc-500 underline hover:text-slate-700 dark:hover:text-white dark:text-zinc-900 disabled:opacity-50 whitespace-nowrap"
                  >
                    {resendStatus[u.id] === "sending"
                      ? "Sending..."
                      : resendStatus[u.id] === "sent"
                      ? "Sent"
                      : "Resend invite"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleReset2fa(u)}
                  className="text-xs text-slate-500 dark:text-zinc-500 underline hover:text-slate-700 dark:hover:text-white whitespace-nowrap"
                  title="Remove this person's authenticator (admins only)"
                >
                  Reset 2FA
                </button>
                <Select
                  value={pendingRoles[u.id] ?? u.role_id ?? ""}
                  onChange={(e) => stageUserRole(u, e.target.value)}
                  disabled={savingRoleFor === u.id}
                  className="w-48"
                >
                  <option value="">No role assigned</option>
                  {roleOptions()}
                </Select>
                {pendingRoles[u.id] !== undefined && (
                  <>
                    <Button size="sm" onClick={() => saveUserRole(u.id)} disabled={savingRoleFor === u.id}>
                      {savingRoleFor === u.id ? "Saving…" : "Save"}
                    </Button>
                    <button
                      type="button"
                      onClick={() => discardUserRole(u.id)}
                      disabled={savingRoleFor === u.id}
                      className="text-xs text-slate-500 dark:text-zinc-400 underline hover:text-slate-700 dark:hover:text-white disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
          {users.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500 py-2">No users yet.</p>}
        </div>
      </Card>

      {showManageAccessConfirm && selectedRole && (
        <ConfirmModal
          title="Grant Manage Roles & Permissions?"
          message={`"${selectedRole.name}" will be able to create/change roles, grant or revoke any permission, and make any user (including their own account) an Admin. Only grant this to someone you'd trust with full control of the system.`}
          confirmLabel="Grant Full Access Control"
          danger
          onConfirm={() => togglePermission("core", "manage_access")}
          onClose={() => setShowManageAccessConfirm(false)}
        />
      )}
    </main>
  );
}
