"use client";

/**
 * Goods receiving. The receiver physically checks the goods, then picks one
 * of two outcomes. Each requires its proof files BEFORE the confirm button
 * enables: good = vendor invoice + POD; bad = invoice + POD + defect photo(s).
 */
import { useState } from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui";
import { apiUpload } from "@/lib/api";
import type { PurchaseOrder } from "./types";

function FilePick({ label, id, accept, multiple, files, onChange }: {
  label: string; id: string; accept: string; multiple?: boolean; files: File[]; onChange: (f: File[]) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm text-slate-600 dark:text-zinc-300 mb-1">{label}</label>
      <input id={id} type="file" accept={accept} multiple={multiple}
        onChange={(e) => onChange(Array.from(e.target.files || []))}
        className="block w-full text-sm text-slate-700 dark:text-zinc-200 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:text-white dark:file:bg-zinc-200 dark:file:text-zinc-900 file:px-3 file:py-1.5 file:text-xs" />
      {files.length > 0 && <p className="text-xs text-emerald-700 dark:text-emerald-400 mt-1">✓ {files.map((f) => f.name).join(", ")}</p>}
    </div>
  );
}

export function ReceiveModal({ po, onClose, onReceived }: {
  po: PurchaseOrder;
  onClose: () => void;
  onReceived: (updated: PurchaseOrder, condition: "good" | "bad") => void;
}) {
  const [mode, setMode] = useState<"choose" | "good" | "bad">("choose");
  const [invoice, setInvoice] = useState<File[]>([]);
  const [pod, setPod] = useState<File[]>([]);
  const [defect, setDefect] = useState<File[]>([]);
  const [notes, setNotes] = useState("");
  const open = po.items.filter((i) => (i.outstanding_qty ?? i.qty) > 0);
  const outstanding = (i: (typeof open)[number]) => i.outstanding_qty ?? i.qty;
  // defective units per line; by default every outstanding unit (the whole consignment is bad), the receiver lowers it
  const [bad, setBad] = useState<Record<string, string>>(() => Object.fromEntries(open.map((i) => [i.id, String(outstanding(i))])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const badNum = (i: (typeof open)[number]) => Math.min(Math.max(parseInt(bad[i.id] || "0", 10) || 0, 0), outstanding(i));
  const totalBad = open.reduce((n, i) => n + badNum(i), 0);
  const totalGood = open.reduce((n, i) => n + outstanding(i) - badNum(i), 0);
  const ready = invoice.length > 0 && pod.length > 0 && (mode === "good" || (defect.length > 0 && totalBad > 0));

  async function submit() {
    setBusy(true); setError(null);
    const fd = new FormData();
    fd.append("invoice", invoice[0]);
    fd.append("pod", pod[0]);
    if (notes.trim()) fd.append("notes", notes.trim());
    if (mode === "bad") {
      defect.forEach((f) => fd.append("defect", f));
      fd.append("lines", JSON.stringify(open.map((i) => ({ item_id: i.id, defective_qty: badNum(i) }))));
    }
    try {
      const updated = await apiUpload<PurchaseOrder>(
        `/api/procurement/purchase-orders/${po.id}/${mode === "good" ? "receive-good" : "receive-bad"}`, fd);
      onReceived(updated, mode as "good" | "bad");
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed"); }
    setBusy(false);
  }

  return (
    <Modal title={`Receive goods · ${po.po_number || ""}`} onClose={onClose}>
      <p className="text-sm text-slate-500 dark:text-zinc-400 mb-3">
        {po.vendor_name} · {po.items.map((i) => `${i.product_name} × ${i.qty}${(i.received_qty ?? 0) > 0 ? ` (${i.received_qty} already received, ${outstanding(i)} outstanding)` : ""}`).join(", ")}
      </p>
      {error && <p className="text-red-600 dark:text-red-400 text-sm mb-3">{error}</p>}

      {mode === "choose" && (
        <div className="space-y-2">
          <p className="text-sm text-slate-700 dark:text-zinc-200">Check the goods by hand, then choose:</p>
          <Button className="w-full" onClick={() => setMode("good")}>Goods are in good condition</Button>
          <Button className="w-full" variant="danger" onClick={() => setMode("bad")}>Goods are in bad condition</Button>
        </div>
      )}

      {mode !== "choose" && (
        <div className="space-y-3">
          <FilePick label="1. Original invoice from vendor (PDF or image)" id="f-invoice" accept="application/pdf,image/png,image/jpeg,image/webp" files={invoice} onChange={setInvoice} />
          <FilePick label="2. POD copy (courier invoice, for tracking)" id="f-pod" accept="application/pdf,image/png,image/jpeg,image/webp" files={pod} onChange={setPod} />
          {mode === "bad" && (
            <>
              <div data-testid="defect-qty" className="rounded-lg border border-slate-200 dark:border-zinc-700 p-3">
                <p className="text-sm text-slate-700 dark:text-zinc-200 mb-2">How many units are defective? The rest are accepted into stock.</p>
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-slate-500 dark:text-zinc-400"><th className="py-1">Item</th><th>Outstanding</th><th>Defective (send back)</th><th>Good (to stock)</th></tr></thead>
                  <tbody>
                    {open.map((i) => (
                      <tr key={i.id} className="border-t border-slate-100 dark:border-zinc-800">
                        <td className="py-1.5 pr-2 text-slate-800 dark:text-zinc-100">{i.product_name}</td>
                        <td>{outstanding(i)}</td>
                        <td><input type="number" min={0} max={outstanding(i)} aria-label={`Defective quantity ${i.product_name}`} value={bad[i.id] ?? ""}
                          onChange={(e) => setBad({ ...bad, [i.id]: e.target.value })}
                          className="w-20 border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-2 py-1 text-sm" /></td>
                        <td className="font-semibold text-emerald-700 dark:text-emerald-400">{outstanding(i) - badNum(i)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {totalBad === 0 && <p className="text-xs text-red-600 dark:text-red-400 mt-2">Enter at least one defective unit, or go back and choose good condition.</p>}
              </div>
              <FilePick label="3. Defect image(s)" id="f-defect" accept="image/png,image/jpeg,image/webp" multiple files={defect} onChange={setDefect} />
              <label className="block text-sm text-slate-600 dark:text-zinc-300">
                What is wrong? (goes into the notice)
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
                  className="mt-1 w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm" />
              </label>
            </>
          )}
          <p className="text-xs text-slate-500 dark:text-zinc-400">
            {mode === "good" ? "Stock increases only when you confirm."
              : totalGood > 0 ? `${totalGood} good unit(s) will be added to stock now; ${totalBad} defective unit(s) stay outstanding on this order until the vendor's replacement arrives (receive it on this same order). You will preview the defect notice next.`
              : "Stock will NOT increase. You will preview the defect notice for the vendor next."}
          </p>
          <div className="flex justify-between gap-2">
            <Button variant="secondary" onClick={() => setMode("choose")}>Back</Button>
            <Button variant={mode === "bad" ? "danger" : "primary"} disabled={!ready || busy} onClick={submit}>
              {busy ? "Saving…" : mode === "good" ? "Goods received in good condition" : "Confirm bad condition"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
