"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest } from "@/lib/api";
import { ConfirmModal } from "@/components/Modal";

type CustomField = {
  id: string;
  module: string;
  entity_type: string;
  field_name: string;
  field_type: string;
  options: string | null;
  is_required: boolean;
  is_active: boolean;
  display_order: number;
};

// The proof-of-mechanism scope for Phase 9 (Roadmap §"Custom Fields, made
// real") — Inventory's Product and CRM's Lead. Adding a third entry here
// is the ENTIRE cost of extending this to a new module; nothing else in
// this file, the backend routes, or CustomFieldsSection changes.
const ENTITY_OPTIONS = [
  { module: "inventory", entity_type: "product", label: "Inventory — Product" },
  { module: "crm", entity_type: "lead", label: "CRM — Lead" },
];

const FIELD_TYPES = ["text", "number", "date", "dropdown"];

export default function CustomFieldsSettingsPage() {
  const [fields, setFields] = useState<CustomField[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [deletingField, setDeletingField] = useState<CustomField | null>(null);
  const [form, setForm] = useState({
    module: ENTITY_OPTIONS[0].module,
    entity_type: ENTITY_OPTIONS[0].entity_type,
    field_name: "",
    field_type: "text",
    options: "",
    is_required: false,
  });

  function loadFields() {
    apiRequest<CustomField[]>("/api/custom-fields?include_inactive=true", { auth: true })
      .then(setFields)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load custom fields"));
  }

  useEffect(loadFields, []);

  function handleEntityChange(label: string) {
    const opt = ENTITY_OPTIONS.find((o) => o.label === label)!;
    setForm({ ...form, module: opt.module, entity_type: opt.entity_type });
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await apiRequest("/api/custom-fields", {
        method: "POST",
        auth: true,
        body: {
          module: form.module,
          entity_type: form.entity_type,
          field_name: form.field_name,
          field_type: form.field_type,
          options: form.field_type === "dropdown" ? form.options : null,
          is_required: form.is_required,
        },
      });
      setForm({ ...form, field_name: "", options: "", is_required: false });
      loadFields();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create field");
    }
  }

  async function toggleActive(field: CustomField) {
    await apiRequest(`/api/custom-fields/${field.id}`, {
      method: "PATCH",
      auth: true,
      body: { is_active: !field.is_active },
    }).catch((err) => setError(err instanceof Error ? err.message : "Failed to update field"));
    loadFields();
  }

  async function handleDelete(field: CustomField) {
    await apiRequest(`/api/custom-fields/${field.id}`, { method: "DELETE", auth: true })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to delete field"));
    loadFields();
  }

  return (
    <main className="min-h-screen p-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Custom Fields</h1>
          <p className="text-sm text-slate-500 mt-1">
            Define extra fields for your organization — they'll appear on the matching record's form automatically.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/settings/roles" className="text-sm text-slate-500 underline hover:text-slate-700">
            Roles & Permissions
          </Link>
          <Link href="/dashboard" className="text-sm text-slate-500 underline">
            ← Dashboard
          </Link>
        </div>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <form onSubmit={handleCreate} className="bg-white rounded-xl shadow-sm p-4 mb-8 max-w-2xl space-y-2">
        <h2 className="font-semibold text-slate-700 text-sm">Add a Field</h2>

        <select
          value={ENTITY_OPTIONS.find((o) => o.module === form.module && o.entity_type === form.entity_type)?.label}
          onChange={(e) => handleEntityChange(e.target.value)}
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
        >
          {ENTITY_OPTIONS.map((o) => (
            <option key={o.label} value={o.label}>{o.label}</option>
          ))}
        </select>

        <input
          placeholder="Field name (e.g. Batch Number)"
          required
          value={form.field_name}
          onChange={(e) => setForm({ ...form, field_name: e.target.value })}
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <select
            value={form.field_type}
            onChange={(e) => setForm({ ...form, field_type: e.target.value })}
            className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
          >
            {FIELD_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          <label className="flex items-center gap-2 text-sm text-slate-600 px-1">
            <input
              type="checkbox"
              checked={form.is_required}
              onChange={(e) => setForm({ ...form, is_required: e.target.checked })}
            />
            Required
          </label>
        </div>

        {form.field_type === "dropdown" && (
          <input
            placeholder="Options, comma-separated (e.g. Small,Medium,Large)"
            required
            value={form.options}
            onChange={(e) => setForm({ ...form, options: e.target.value })}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
        )}

        <button className="w-full bg-slate-800 text-white rounded-lg py-2 text-sm font-medium hover:bg-slate-700">
          Add Field
        </button>
      </form>

      <div className="max-w-2xl">
        <h2 className="font-semibold text-slate-700 mb-3">Existing Fields</h2>
        <div className="bg-white rounded-lg shadow-sm divide-y">
          {fields.map((f) => (
            <div key={f.id} className="p-3 flex justify-between items-center text-sm">
              <div>
                <p className={f.is_active ? "text-slate-800 font-medium" : "text-slate-400 font-medium line-through"}>
                  {f.field_name}
                </p>
                <p className="text-xs text-slate-500">
                  {ENTITY_OPTIONS.find((o) => o.module === f.module && o.entity_type === f.entity_type)?.label || `${f.module} — ${f.entity_type}`}
                  {" · "}{f.field_type}
                  {f.is_required && " · required"}
                  {!f.is_active && " · inactive"}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => toggleActive(f)}
                  className="text-xs text-slate-500 underline hover:text-slate-700"
                >
                  {f.is_active ? "Deactivate" : "Activate"}
                </button>
                <button
                  onClick={() => setDeletingField(f)}
                  className="text-xs text-red-500 underline hover:text-red-700"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
          {fields.length === 0 && <p className="p-3 text-sm text-slate-400">No custom fields defined yet.</p>}
        </div>
      </div>

      {deletingField && (
        <ConfirmModal
          title="Delete Custom Field"
          message={`Delete "${deletingField.field_name}"? This also deletes every saved value for it.`}
          confirmLabel="Delete"
          danger
          onConfirm={() => handleDelete(deletingField)}
          onClose={() => setDeletingField(null)}
        />
      )}
    </main>
  );
}
