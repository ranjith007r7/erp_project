"use client";

/**
 * THE customization mechanism, made visible. This component knows nothing
 * about "products" or "leads" — it only knows entityType + entityId, and
 * asks the backend "what fields exist for this entity_type, and what are
 * this specific record's current values." Every input it renders is
 * decided purely by field_type, coming from data, not from a switch
 * statement per module.
 *
 * Drop this into ANY record's row/detail view with two props and it
 * works — that's the whole point of Phase 9. Proven here on Product
 * (Inventory) and Lead (CRM); adding a third module later is a two-line
 * change at the call site, zero changes in here.
 */
import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";

type CustomFieldValue = {
  custom_field_id: string;
  field_name: string;
  field_type: "text" | "number" | "date" | "dropdown";
  value: string | null;
};

// field_type -> dropdown options come back as a comma-separated string on
// the field DEFINITION, not the value. We fetch definitions separately
// only when a dropdown needs its options rendered (values endpoint keeps
// the common-case payload small by not repeating full field metadata).
type CustomFieldDef = {
  id: string;
  field_name: string;
  field_type: string;
  options: string | null;
  is_required: boolean;
};

export function CustomFieldsSection({ entityType, entityId }: { entityType: string; entityId: string }) {
  const [values, setValues] = useState<CustomFieldValue[]>([]);
  const [defs, setDefs] = useState<Record<string, CustomFieldDef>>({});
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      apiRequest<CustomFieldValue[]>(
        `/api/custom-fields/values?entity_type=${entityType}&entity_id=${entityId}`,
        { auth: true }
      ),
      apiRequest<CustomFieldDef[]>(`/api/custom-fields?entity_type=${entityType}`, { auth: true }),
    ])
      .then(([vals, definitions]) => {
        if (cancelled) return;
        setValues(vals);
        setDefs(Object.fromEntries(definitions.map((d) => [d.id, d])));
        setDraft(Object.fromEntries(vals.map((v) => [v.custom_field_id, v.value ?? ""])));
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Failed to load custom fields"))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [entityType, entityId]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await apiRequest("/api/custom-fields/values", {
        method: "POST",
        auth: true,
        body: {
          entity_type: entityType,
          entity_id: entityId,
          values: values.map((v) => ({
            custom_field_id: v.custom_field_id,
            value: draft[v.custom_field_id] ?? "",
          })),
        },
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save custom fields");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="text-xs text-slate-400 dark:text-zinc-500 py-2">Loading custom fields…</p>;
  if (values.length === 0) return null; // no fields defined for this entity_type — render nothing, not an empty box

  return (
    <div className="border-t border-slate-100 dark:border-zinc-800 mt-3 pt-3 space-y-2">
      <p className="text-xs font-medium text-slate-500 dark:text-zinc-500 uppercase tracking-wide">Custom Fields</p>

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {values.map((v) => {
          const def = defs[v.custom_field_id];
          const current = draft[v.custom_field_id] ?? "";

          return (
            <label key={v.custom_field_id} className="text-xs text-slate-600 dark:text-zinc-300 block">
              {v.field_name}
              {def?.is_required && <span className="text-red-500"> *</span>}

              {v.field_type === "dropdown" ? (
                <select
                  value={current}
                  onChange={(e) => setDraft({ ...draft, [v.custom_field_id]: e.target.value })}
                  className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-2 py-1.5 text-sm mt-1"
                >
                  <option value="">—</option>
                  {(def?.options ?? "").split(",").filter(Boolean).map((opt) => (
                    <option key={opt} value={opt.trim()}>{opt.trim()}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={v.field_type === "number" ? "number" : v.field_type === "date" ? "date" : "text"}
                  value={current}
                  onChange={(e) => setDraft({ ...draft, [v.custom_field_id]: e.target.value })}
                  className="w-full border border-slate-300 dark:border-zinc-700 rounded-lg px-2 py-1.5 text-sm mt-1"
                />
              )}
            </label>
          );
        })}
      </div>

      <button
        onClick={handleSave}
        disabled={saving}
        className="text-xs bg-slate-700 dark:bg-zinc-300 text-white dark:text-zinc-900 px-3 py-1.5 rounded-lg hover:bg-slate-600 dark:hover:bg-zinc-700 disabled:opacity-50"
      >
        {saving ? "Saving…" : saved ? "Saved ✓" : "Save Custom Fields"}
      </button>
    </div>
  );
}
