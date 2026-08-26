"use client";

import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";
import { PageHeader, Button, Input, Select, Card } from "@/components/ui";
import { ConfirmModal } from "@/components/Modal";

type Role = { id: string; org_id: string; name: string };
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
  "finance", "hr", "projects", "documents", "reports", "custom_fields",
];
const ACTIONS = ["view", "create", "edit", "delete", "approve"] as const;

export default function RolesSettingsPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [permissionsLoading, setPermissionsLoading] = useState(false);
  const [showManageAccessConfirm, setShowManageAccessConfirm] = useState(false);

  const [roleForm, setRoleForm] = useState({ name: "" });
  const [userForm, setUserForm] = useState({ name: "", email: "", password: "", role_id: "" });
  const [inviteForm, setInviteForm] = useState({ name: "", email: "", role_id: "" });
  const [addUserMode, setAddUserMode] = useState<"invite" | "password">("invite");
  const [resendStatus, setResendStatus] = useState<Record<string, "idle" | "sending" | "sent">>({});

  function loadRoles() {
    apiRequest<Role[]>("/api/core/roles", { auth: true })
      .then(setRoles)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load roles"));
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
  }, []);

  useEffect(() => {
    if (selectedRoleId) loadPermissions(selectedRoleId);
    else setPermissions([]);
  }, [selectedRoleId]);

  async function handleCreateRole(e: React.FormEvent) {
    e.preventDefault();
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

  async function handleChangeUserRole(userId: string, roleId: string) {
    setError(null);
    try {
      await apiRequest(`/api/core/users/${userId}/role`, {
        method: "PATCH", auth: true, body: { role_id: roleId || null },
      });
      loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change user's role");
    }
  }

  const selectedRole = roles.find((r) => r.id === selectedRoleId);

  return (
    <main className="min-h-screen p-8">
      <PageHeader
        title="Roles & Permissions"
        actions={
          <a href="/settings/custom-fields" className="text-sm text-slate-500 underline hover:text-slate-700">
            Custom Fields
          </a>
        }
      />

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Roles */}
        <Card className="p-4">
          <h2 className="font-semibold text-slate-700 text-sm mb-3">Roles</h2>
          <form onSubmit={handleCreateRole} className="flex gap-2 mb-4">
            <Input
              placeholder="e.g. Sales Executive"
              value={roleForm.name}
              onChange={(e) => setRoleForm({ name: e.target.value })}
              required
            />
            <Button type="submit" size="sm">Add</Button>
          </form>

          <div className="divide-y">
            {roles.map((role) => (
              <button
                key={role.id}
                onClick={() => setSelectedRoleId(role.id)}
                className={`w-full text-left py-2 px-2 text-sm rounded-lg ${
                  selectedRoleId === role.id ? "bg-slate-100 font-medium text-slate-800" : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {role.name}
              </button>
            ))}
            {roles.length === 0 && <p className="text-sm text-slate-400 py-2">No roles yet.</p>}
          </div>
        </Card>

        {/* Permission matrix for the selected role */}
        <Card className="p-4">
          <h2 className="font-semibold text-slate-700 text-sm mb-3">
            {selectedRole ? `Permissions — ${selectedRole.name}` : "Select a role to manage its permissions"}
          </h2>

          {!selectedRole && (
            <p className="text-sm text-slate-400">Pick a role on the left, then toggle what it can do below.</p>
          )}

          {selectedRole && permissionsLoading && <p className="text-sm text-slate-400">Loading…</p>}

          {selectedRole && !permissionsLoading && (
            <div
              className={`mb-4 p-3 rounded-lg border-2 flex justify-between items-center ${
                hasManageAccess() ? "bg-amber-50 border-amber-300" : "bg-slate-50 border-slate-200"
              }`}
            >
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  {hasManageAccess() ? "⚠️ " : ""}Manage Roles &amp; Permissions
                </p>
                <p className="text-xs text-slate-600 mt-0.5 max-w-md">
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
                  <tr className="text-left text-xs text-slate-400 uppercase">
                    <th className="py-1 pr-2">Module</th>
                    {ACTIONS.map((action) => (
                      <th key={action} className="py-1 px-1 text-center">{action}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MODULES.map((module) => (
                    <tr key={module} className="border-t border-slate-100">
                      <td className="py-1.5 pr-2 text-slate-700">{module}</td>
                      {ACTIONS.map((action) => (
                        <td key={action} className="py-1.5 px-1 text-center">
                          <input
                            type="checkbox"
                            checked={!!hasPermission(module, action)}
                            onChange={() => togglePermission(module, action)}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {/* Users */}
      <Card className="p-4 max-w-3xl">
        <div className="flex justify-between items-center mb-3">
          <h2 className="font-semibold text-slate-700 text-sm">Users</h2>
          <div className="flex text-xs rounded-lg overflow-hidden border border-slate-300">
            <button
              onClick={() => setAddUserMode("invite")}
              className={`px-3 py-1.5 ${addUserMode === "invite" ? "bg-slate-800 text-white" : "bg-white text-slate-600"}`}
            >
              Send Invite
            </button>
            <button
              onClick={() => setAddUserMode("password")}
              className={`px-3 py-1.5 ${addUserMode === "password" ? "bg-slate-800 text-white" : "bg-white text-slate-600"}`}
            >
              Set Password Directly
            </button>
          </div>
        </div>

        {addUserMode === "invite" ? (
          <form onSubmit={handleSendInvite} className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
            <p className="text-xs text-slate-500 sm:col-span-2">
              Sends a real email with a link — they'll set their own password. Nothing to type in
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
              {roles.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
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
              {roles.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </Select>
            <Button type="submit" className="sm:col-span-2">Add User</Button>
          </form>
        )}

        <div className="divide-y">
          {users.map((u) => (
            <div key={u.id} className="py-2 flex justify-between items-center text-sm">
              <div>
                <p className="text-slate-800 font-medium">
                  {u.name}
                  {u.status === "invited" && (
                    <span className="ml-2 text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full align-middle">
                      Invite pending
                    </span>
                  )}
                </p>
                <p className="text-xs text-slate-500">{u.email}</p>
              </div>
              <div className="flex items-center gap-2">
                {u.status === "invited" && (
                  <button
                    onClick={() => handleResendInvite(u.id)}
                    disabled={resendStatus[u.id] === "sending"}
                    className="text-xs text-slate-500 underline hover:text-slate-700 disabled:opacity-50 whitespace-nowrap"
                  >
                    {resendStatus[u.id] === "sending"
                      ? "Sending..."
                      : resendStatus[u.id] === "sent"
                      ? "Sent"
                      : "Resend invite"}
                  </button>
                )}
                <Select
                  value={u.role_id ?? ""}
                  onChange={(e) => handleChangeUserRole(u.id, e.target.value)}
                  className="w-48"
                >
                  <option value="">No role assigned</option>
                  {roles.map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </Select>
              </div>
            </div>
          ))}
          {users.length === 0 && <p className="text-sm text-slate-400 py-2">No users yet.</p>}
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
