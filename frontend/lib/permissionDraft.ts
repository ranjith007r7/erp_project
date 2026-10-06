/**
 * Staged (unsaved) permission edits for the Roles & Permissions grid.
 *
 * A checkbox click no longer calls the API. It records what the admin WANTS in a
 * "draft", and nothing is saved until they press Save. The draft holds ONLY the
 * cells that differ from what is saved, so ticking a box and un-ticking it again
 * leaves no change behind and the Save button disappears.
 *
 * Kept free of React and of the network on purpose, so the rules are testable.
 */
export type SavedPermission = { id: string; module: string; action: string };

/** "module:action" -> the state wanted (true = should exist). Only differing cells are stored. */
export type Draft = Record<string, boolean>;

export function keyOf(module: string, action: string): string {
  return `${module}:${action}`;
}

function savedHas(saved: SavedPermission[], module: string, action: string): boolean {
  return saved.some((p) => p.module === module && p.action === action);
}

/** What the checkbox should show: the staged value if there is one, else what is saved. */
export function isChecked(saved: SavedPermission[], draft: Draft, module: string, action: string): boolean {
  const key = keyOf(module, action);
  return key in draft ? draft[key] : savedHas(saved, module, action);
}

export function toggleDraft(saved: SavedPermission[], draft: Draft, module: string, action: string): Draft {
  const wanted = !isChecked(saved, draft, module, action);
  const key = keyOf(module, action);
  const next = { ...draft };
  if (wanted === savedHas(saved, module, action)) delete next[key]; // back to the saved state: no change
  else next[key] = wanted;
  return next;
}

export type ChangePlan = {
  adds: { module: string; action: string }[];
  removes: SavedPermission[];
};

/** Turns the draft into the API calls needed. Anything already in the wanted state is skipped. */
export function planChanges(saved: SavedPermission[], draft: Draft): ChangePlan {
  const plan: ChangePlan = { adds: [], removes: [] };
  for (const [key, wanted] of Object.entries(draft)) {
    const split = key.lastIndexOf(":");
    const moduleName = key.slice(0, split); // not "module": Next.js forbids a variable of that name
    const action = key.slice(split + 1);
    const existing = saved.find((p) => p.module === moduleName && p.action === action);
    if (wanted && !existing) plan.adds.push({ module: moduleName, action });
    if (!wanted && existing) plan.removes.push(existing);
  }
  return plan;
}
