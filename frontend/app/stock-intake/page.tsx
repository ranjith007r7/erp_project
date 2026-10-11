"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiRequest, apiUpload, apiDownload } from "@/lib/api";
import { PageHeader, Button } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { SkeletonList } from "@/components/Skeleton";

type Product = { id: string; name: string; sku: string | null };
type SummaryRow = { product_id: string; product_name: string; sku: string | null; on_hand: number; priced: number; unpriced: number; usable: number; expired: number; value_at_cost: number };
type Summary = { products: SummaryRow[]; vendor_names: string[]; totals: { units_priced: number; units_unpriced: number; value_at_cost: number } };
type Batch = {
  id: string; product_id: string; product_name: string | null; sku: string | null; vendor_name: string; vendor_amount: number;
  mrp: number; max_discount_percent: number; lowest_selling_price: number; quantity_in: number; quantity_remaining: number;
  inward_date: string; manufacture_month: string | null; expiry_date: string | null; expired: boolean; expiring_soon: boolean;
  source: string; note: string | null; sold_below_cost_warning?: boolean;
};

const inr = (n: number) => "Rs. " + Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const field = "w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm";
const label = "block text-xs font-medium text-slate-600 dark:text-zinc-400 mb-1";
const today = () => new Date().toISOString().slice(0, 10);
const EMPTY = { product_id: "", quantity: "", vendor_name: "", vendor_amount: "", mrp: "", max_discount_percent: "", inward_date: today(), manufacture_month: "", expiry_date: "", already_in_inventory: false, note: "" };

export default function StockIntakePage() {
  const { showToast } = useToast();
  const [products, setProducts] = useState<Product[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Batch | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [importResult, setImportResult] = useState<{ imported: number; failed: number; errors: { row: number; reason: string }[] } | null>(null);

  const load = useCallback(() => {
    Promise.all([
      apiRequest<Product[]>("/api/stockin/products", { auth: true }),
      apiRequest<Summary>("/api/stockin/summary", { auth: true }),
      apiRequest<Batch[]>("/api/stockin/batches", { auth: true }),
    ])
      .then(([p, s, b]) => { setProducts(p); setSummary(s); setBatches(b); })
      .catch((e: Error) => { if (/does not have|permission|403|forbidden|No role/i.test(e.message)) setDenied(true); else showToast(e.message, "error"); })
      .finally(() => setLoading(false));
  }, [showToast]);
  useEffect(load, [load]);

  const f = (k: keyof typeof EMPTY, v: string | boolean) => setForm((s) => ({ ...s, [k]: v }));
  const floor = useMemo(() => {
    const m = Number(form.mrp), d = Number(form.max_discount_percent);
    return m > 0 && form.max_discount_percent !== "" && d >= 0 && d <= 100 ? m * (100 - d) / 100 : null;
  }, [form.mrp, form.max_discount_percent]);
  const belowCost = floor !== null && form.vendor_amount !== "" && floor < Number(form.vendor_amount);
  const picked = summary?.products.find((p) => p.product_id === form.product_id);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await apiRequest("/api/stockin/batches", {
        method: "POST", auth: true,
        body: {
          product_id: form.product_id, quantity: Number(form.quantity), vendor_name: form.vendor_name.trim(),
          vendor_amount: Number(form.vendor_amount), mrp: Number(form.mrp), max_discount_percent: Number(form.max_discount_percent),
          inward_date: form.inward_date || null, manufacture_month: form.manufacture_month || null, expiry_date: form.expiry_date || null,
          already_in_inventory: form.already_in_inventory, note: form.note.trim() || null,
        },
      });
      showToast(form.already_in_inventory ? "Rates saved for stock already in Inventory" : "Stock added to Inventory", "success");
      setForm({ ...EMPTY, inward_date: today(), vendor_name: form.vendor_name });
      load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not save", "error");
    } finally { setSaving(false); }
  }

  function startEdit(b: Batch) {
    setEditing(b);
    setEdit({
      vendor_name: b.vendor_name, vendor_amount: String(b.vendor_amount), mrp: String(b.mrp), max_discount_percent: String(b.max_discount_percent),
      inward_date: b.inward_date, manufacture_month: b.manufacture_month ? b.manufacture_month.slice(0, 7) : "", expiry_date: b.expiry_date ?? "", note: b.note ?? "",
    });
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    try {
      await apiRequest(`/api/stockin/batches/${editing.id}`, {
        method: "PATCH", auth: true,
        body: {
          vendor_name: edit.vendor_name, vendor_amount: Number(edit.vendor_amount), mrp: Number(edit.mrp), max_discount_percent: Number(edit.max_discount_percent),
          inward_date: edit.inward_date || null, manufacture_month: edit.manufacture_month || "", expiry_date: edit.expiry_date || null, note: edit.note,
        },
      });
      showToast("Batch updated", "success");
      setEditing(null);
      load();
    } catch (err) { showToast(err instanceof Error ? err.message : "Could not update", "error"); }
  }
  async function remove(b: Batch) {
    if (!confirm(`Undo this entry? ${b.quantity_in} unit(s) of ${b.product_name} will be taken back out of Inventory.`)) return;
    try {
      await apiRequest(`/api/stockin/batches/${b.id}`, { method: "DELETE", auth: true });
      showToast("Entry removed", "success");
      load();
    } catch (err) { showToast(err instanceof Error ? err.message : "Could not delete", "error"); }
  }
  async function importFile(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await apiUpload<{ imported: number; failed: number; errors: { row: number; reason: string }[] }>("/api/stockin/import", fd);
      setImportResult(r);
      showToast(`${r.imported} batch(es) imported${r.failed ? `, ${r.failed} row(s) need fixing` : ""}`, r.failed ? "info" : "success");
      load();
    } catch (err) { showToast(err instanceof Error ? err.message : "Import failed", "error"); }
  }

  const shown = batches.filter((b) => {
    const q = search.trim().toLowerCase();
    return !q || [b.product_name, b.sku, b.vendor_name].some((x) => (x ?? "").toLowerCase().includes(q));
  });

  if (denied) return <main className="p-8"><PageHeader title="Stock Intake" /><p className="text-sm text-slate-600 dark:text-zinc-400">Stock Intake is for managers and admins. Ask an admin to tick Stock Intake on your role.</p></main>;

  return (
    <main className="min-h-screen p-4 sm:p-8">
      <PageHeader title="Stock Intake" description="Record stock the company already holds, or new stock arriving. Every lot carries its buying rate, selling price and maximum discount so employees never type an amount when they take stock for a work." />
      {loading ? <SkeletonList rows={4} /> : (
        <>
          {summary && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
              <Stat t="Units with rates" v={String(summary.totals.units_priced)} />
              <Stat t="Units without rates" v={String(summary.totals.units_unpriced)} warn={summary.totals.units_unpriced > 0} hint="In Inventory but not priced. Enter them below with 'already in Inventory' ticked." />
              <Stat t="Stock value at cost" v={inr(summary.totals.value_at_cost)} />
              <Stat t="Lots on hand" v={String(batches.filter((b) => b.quantity_remaining > 0).length)} />
            </div>
          )}

          <div className="grid xl:grid-cols-3 gap-6 mb-8">
            <form onSubmit={submit} className="xl:col-span-2 bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-3">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Add stock</h2>
              <div className="grid sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2">
                  <label className={label}>Product *</label>
                  <select required className={field} value={form.product_id} onChange={(e) => f("product_id", e.target.value)}>
                    <option value="">Select product…</option>
                    {products.map((p) => <option key={p.id} value={p.id}>{p.name}{p.sku ? ` (${p.sku})` : ""}</option>)}
                  </select>
                  {picked && picked.unpriced > 0 && <p className="text-xs text-amber-600 mt-1">{picked.unpriced} unit(s) of this product are in Inventory without rates.</p>}
                </div>
                <div><label className={label}>Quantity *</label><input required type="number" min={1} className={field} value={form.quantity} onChange={(e) => f("quantity", e.target.value)} /></div>
                <div className="sm:col-span-3">
                  <label className={label}>Vendor name *</label>
                  <input required list="vendor-names" className={field} value={form.vendor_name} onChange={(e) => f("vendor_name", e.target.value)} />
                  <datalist id="vendor-names">{summary?.vendor_names.map((v) => <option key={v} value={v} />)}</datalist>
                </div>
                <div><label className={label}>Vendor amount - rate bought at, per unit *</label><input required type="number" min={0} step="0.01" className={field} value={form.vendor_amount} onChange={(e) => f("vendor_amount", e.target.value)} /></div>
                <div><label className={label}>MRP - can be sold at, per unit *</label><input required type="number" min={0.01} step="0.01" className={field} value={form.mrp} onChange={(e) => f("mrp", e.target.value)} /></div>
                <div><label className={label}>Max discount for this part (%) *</label><input required type="number" min={0} max={100} step="0.01" className={field} value={form.max_discount_percent} onChange={(e) => f("max_discount_percent", e.target.value)} /></div>
                <div><label className={label}>Date of inward</label><input type="date" max={today()} className={field} value={form.inward_date} onChange={(e) => f("inward_date", e.target.value)} /></div>
                <div><label className={label}>Month of manufacture</label><input type="month" className={field} value={form.manufacture_month} onChange={(e) => f("manufacture_month", e.target.value)} /></div>
                <div><label className={label}>Expiry date</label><input type="date" className={field} value={form.expiry_date} onChange={(e) => f("expiry_date", e.target.value)} /></div>
                <div className="sm:col-span-3"><label className={label}>Note</label><input className={field} value={form.note} onChange={(e) => f("note", e.target.value)} /></div>
              </div>
              <label className="flex items-start gap-2 text-sm text-slate-700 dark:text-zinc-300">
                <input type="checkbox" className="mt-1" checked={form.already_in_inventory} onChange={(e) => f("already_in_inventory", e.target.checked)} />
                <span>These units are <b>already counted</b> in Inventory - only attach the rates (does not add to the stock count).</span>
              </label>
              {floor !== null && (
                <p className={`text-xs ${belowCost ? "text-red-600" : "text-slate-500 dark:text-zinc-500"}`}>
                  Lowest allowed selling price: <b>{inr(floor)}</b> per unit.{belowCost && " This is below your buying rate - billing at the floor would lose money."}
                </p>
              )}
              <Button type="submit" disabled={saving}>{saving ? "Saving…" : form.already_in_inventory ? "Save rates" : "Add to Inventory"}</Button>
            </form>

            <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 space-y-3 h-fit">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Bulk import (CSV)</h2>
              <p className="text-xs text-slate-500 dark:text-zinc-500">One row per lot. Products must already exist in Inventory. Good rows are saved; bad rows are listed with the reason.</p>
              <Button variant="secondary" size="sm" type="button" onClick={() => apiDownload("/api/stockin/import-template", "stock_intake_template.csv").catch((e) => showToast(e.message, "error"))}>Download template</Button>
              <input type="file" accept=".csv,text/csv" className="block text-xs" onChange={(e) => { const x = e.target.files?.[0]; if (x) importFile(x); e.target.value = ""; }} />
              {importResult && (
                <div className="text-xs">
                  <p className="font-medium">{importResult.imported} imported, {importResult.failed} failed</p>
                  <ul className="list-disc ml-4 text-red-600 mt-1 max-h-40 overflow-auto">{importResult.errors.map((x) => <li key={x.row}>Row {x.row}: {x.reason}</li>)}</ul>
                </div>
              )}
            </div>
          </div>

          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4 mb-8">
            <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm mb-3">Stock by product</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-500 border-b border-slate-200 dark:border-zinc-800"><th className="py-2 pr-3">Product</th><th className="pr-3">In Inventory</th><th className="pr-3">With rates</th><th className="pr-3">Without rates</th><th className="pr-3">Expired</th><th>Value at cost</th></tr></thead>
                <tbody>
                  {summary?.products.filter((p) => p.on_hand > 0 || p.priced > 0).map((p) => (
                    <tr key={p.product_id} className="border-b border-slate-100 dark:border-zinc-800">
                      <td className="py-2 pr-3">{p.product_name}{p.sku && <span className="text-slate-400"> · {p.sku}</span>}</td>
                      <td className="pr-3">{p.on_hand}</td><td className="pr-3">{p.priced}</td>
                      <td className={`pr-3 ${p.unpriced ? "text-amber-600 font-medium" : ""}`}>{p.unpriced}</td>
                      <td className={`pr-3 ${p.expired ? "text-red-600" : ""}`}>{p.expired}</td><td>{inr(p.value_at_cost)}</td>
                    </tr>
                  ))}
                  {summary && !summary.products.some((p) => p.on_hand > 0 || p.priced > 0) && <tr><td colSpan={6} className="py-4 text-slate-500">No stock recorded yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-4">
            <div className="flex justify-between items-center mb-3 gap-2 flex-wrap">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">All lots</h2>
              <input placeholder="Search product, SKU or vendor" className={`${field} max-w-xs`} value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-500 border-b border-slate-200 dark:border-zinc-800">
                  <th className="py-2 pr-3">Product</th><th className="pr-3">Vendor</th><th className="pr-3">Left / in</th><th className="pr-3">Cost</th><th className="pr-3">MRP</th><th className="pr-3">Max disc.</th><th className="pr-3">Floor</th><th className="pr-3">Inward</th><th className="pr-3">Mfg</th><th className="pr-3">Expiry</th><th></th></tr></thead>
                <tbody>
                  {shown.map((b) => (
                    <tr key={b.id} className="border-b border-slate-100 dark:border-zinc-800 align-top">
                      <td className="py-2 pr-3">{b.product_name}<div className="text-xs text-slate-400">{b.source.replace("_", " ")}</div></td>
                      <td className="pr-3">{b.vendor_name}</td>
                      <td className="pr-3">{b.quantity_remaining} / {b.quantity_in}</td>
                      <td className="pr-3">{inr(b.vendor_amount)}</td><td className="pr-3">{inr(b.mrp)}</td>
                      <td className="pr-3">{b.max_discount_percent}%</td>
                      <td className={`pr-3 ${b.sold_below_cost_warning ? "text-red-600" : ""}`} title={b.sold_below_cost_warning ? "Floor is below cost" : ""}>{inr(b.lowest_selling_price)}</td>
                      <td className="pr-3">{b.inward_date}</td>
                      <td className="pr-3">{b.manufacture_month ? b.manufacture_month.slice(0, 7) : "-"}</td>
                      <td className={`pr-3 ${b.expired ? "text-red-600 font-medium" : b.expiring_soon ? "text-amber-600" : ""}`}>{b.expiry_date ? b.expiry_date + (b.expired ? " (expired)" : "") : "-"}</td>
                      <td className="whitespace-nowrap"><button className="text-xs underline mr-2" onClick={() => startEdit(b)}>Edit</button>
                        {b.source !== "purchase_order" && b.quantity_remaining === b.quantity_in && <button className="text-xs underline text-red-600" onClick={() => remove(b)}>Undo</button>}</td>
                    </tr>
                  ))}
                  {!shown.length && <tr><td colSpan={11} className="py-4 text-slate-500">No lots found.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {editing && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50" onClick={() => setEditing(null)}>
          <form onSubmit={saveEdit} onClick={(e) => e.stopPropagation()} className="bg-white dark:bg-zinc-900 rounded-xl p-5 w-full max-w-lg space-y-3 max-h-[90vh] overflow-auto">
            <h3 className="font-semibold">Edit lot - {editing.product_name}</h3>
            <p className="text-xs text-slate-500">Quantity cannot be edited (it has stock movements). Works that already took units keep the rates they were billed with.</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2"><label className={label}>Vendor name</label><input required className={field} value={edit.vendor_name} onChange={(e) => setEdit({ ...edit, vendor_name: e.target.value })} /></div>
              <div><label className={label}>Vendor amount</label><input required type="number" step="0.01" min={0} className={field} value={edit.vendor_amount} onChange={(e) => setEdit({ ...edit, vendor_amount: e.target.value })} /></div>
              <div><label className={label}>MRP</label><input required type="number" step="0.01" min={0.01} className={field} value={edit.mrp} onChange={(e) => setEdit({ ...edit, mrp: e.target.value })} /></div>
              <div><label className={label}>Max discount %</label><input required type="number" step="0.01" min={0} max={100} className={field} value={edit.max_discount_percent} onChange={(e) => setEdit({ ...edit, max_discount_percent: e.target.value })} /></div>
              <div><label className={label}>Date of inward</label><input type="date" className={field} value={edit.inward_date} onChange={(e) => setEdit({ ...edit, inward_date: e.target.value })} /></div>
              <div><label className={label}>Month of manufacture</label><input type="month" className={field} value={edit.manufacture_month} onChange={(e) => setEdit({ ...edit, manufacture_month: e.target.value })} /></div>
              <div><label className={label}>Expiry date</label><input type="date" className={field} value={edit.expiry_date} onChange={(e) => setEdit({ ...edit, expiry_date: e.target.value })} /></div>
              <div className="col-span-2"><label className={label}>Note</label><input className={field} value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} /></div>
            </div>
            <div className="flex gap-2 justify-end"><Button variant="secondary" type="button" onClick={() => setEditing(null)}>Cancel</Button><Button type="submit">Save</Button></div>
          </form>
        </div>
      )}
    </main>
  );
}

function Stat({ t, v, warn, hint }: { t: string; v: string; warn?: boolean; hint?: string }) {
  return (
    <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm p-3" title={hint}>
      <p className="text-xs text-slate-500 dark:text-zinc-500">{t}</p>
      <p className={`text-lg font-semibold ${warn ? "text-amber-600" : "text-slate-800 dark:text-white"}`}>{v}</p>
    </div>
  );
}
