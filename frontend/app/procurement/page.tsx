"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, FileDown, Mail, PackageCheck, Paperclip, Plus, Trash2 } from "lucide-react";
import { apiBlob, apiRequest, openBlob, saveBlob } from "@/lib/api";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { SkeletonList } from "@/components/Skeleton";
import { useToast } from "@/components/Toast";
import { EmailPreviewModal } from "@/components/procurement/EmailPreviewModal";
import { ReceiveModal } from "@/components/procurement/ReceiveModal";
import { inr, type Product, type PurchaseOrder, type Receipt, type Vendor } from "@/components/procurement/types";

type Line = { product_id: string; qty: string; unit_price: string };
type EmailTarget = { kind: "po"; po: PurchaseOrder } | { kind: "defect"; po: PurchaseOrder; receipt: Receipt };

const APPROVAL_STYLE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300",
};
const DELIVERY_LABEL: Record<string, string> = {
  pending: "Awaiting delivery", received: "Received", defective: "Delivered defective", cancelled: "Cancelled",
};
const APPROVAL_LABEL: Record<string, string> = { pending: "Pending approval", approved: "Approved", rejected: "Rejected" };

function Badge({ cls, children }: { cls: string; children: React.ReactNode }) {
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{children}</span>;
}

export default function ProcurementPage() {
  const { showToast } = useToast();
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [vendorForm, setVendorForm] = useState({ name: "", email: "" });
  const [poVendor, setPoVendor] = useState("");
  const [lines, setLines] = useState<Line[]>([{ product_id: "", qty: "1", unit_price: "" }]);

  const [filterVendor, setFilterVendor] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [emailTarget, setEmailTarget] = useState<EmailTarget | null>(null);
  const [receiveFor, setReceiveFor] = useState<PurchaseOrder | null>(null);
  const [editEmail, setEditEmail] = useState<Vendor | null>(null);
  const [editEmailValue, setEditEmailValue] = useState("");

  function loadAll() {
    Promise.allSettled([
      apiRequest<Vendor[]>("/api/procurement/vendors", { auth: true }).then(setVendors),
      apiRequest<Product[]>("/api/sales/products", { auth: true }).then(setProducts),
      apiRequest<PurchaseOrder[]>("/api/procurement/purchase-orders", { auth: true }).then(setOrders).catch((e) => setError(e.message)),
    ]).finally(() => setLoading(false));
  }
  useEffect(loadAll, []);

  const shown = useMemo(() => (filterVendor ? orders.filter((o) => o.vendor_id === filterVendor) : orders), [orders, filterVendor]);
  const selectedVendor = vendors.find((v) => v.id === filterVendor);
  const counts = useMemo(() => ({
    pending: shown.filter((o) => o.approval_status === "pending").length,
    approved: shown.filter((o) => o.approval_status === "approved").length,
    all: shown.length,
  }), [shown]);

  function fail(err: unknown, fallback: string) {
    showToast(err instanceof Error ? err.message : fallback, "error");
  }

  async function addVendor(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/procurement/vendors", { method: "POST", auth: true, body: { name: vendorForm.name, email: vendorForm.email.trim() || null } });
      setVendorForm({ name: "", email: "" });
      showToast("Vendor added", "success");
      loadAll();
    } catch (err) { fail(err, "Failed to add vendor"); }
  }

  async function saveVendorEmail() {
    if (!editEmail) return;
    try {
      await apiRequest(`/api/procurement/vendors/${editEmail.id}`, { method: "PATCH", auth: true, body: { email: editEmailValue.trim() || null } });
      setEditEmail(null);
      showToast("Vendor email saved", "success");
      loadAll();
    } catch (err) { fail(err, "Failed to save email"); }
  }

  function setLine(i: number, patch: Partial<Line>) {
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }
  const poTotal = lines.reduce((s, l) => s + (Number(l.qty) || 0) * (Number(l.unit_price) || 0), 0);

  async function createPO(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiRequest("/api/procurement/purchase-orders", {
        method: "POST", auth: true,
        body: { vendor_id: poVendor, items: lines.map((l) => ({ product_id: l.product_id, qty: Number(l.qty), unit_price: Number(l.unit_price) })) },
      });
      setPoVendor(""); setLines([{ product_id: "", qty: "1", unit_price: "" }]);
      showToast("Purchase order raised. It now waits for approval.", "success");
      loadAll();
    } catch (err) { fail(err, "Failed to create purchase order"); }
  }

  async function decide(po: PurchaseOrder, action: "approve" | "reject") {
    try {
      await apiRequest(`/api/procurement/purchase-orders/${po.id}/${action}`, { method: "POST", auth: true });
      showToast(`${po.po_number} ${action === "approve" ? "approved" : "rejected"}`, "success");
      loadAll();
    } catch (err) { fail(err, `Could not ${action}`); }
  }

  async function downloadVendorPdf(scope: "pending" | "approved" | "all") {
    setMenuOpen(false);
    if (!selectedVendor) return;
    try {
      const blob = await apiBlob(`/api/procurement/vendors/${selectedVendor.id}/purchase-orders/pdf?scope=${scope}`);
      saveBlob(blob, `${selectedVendor.name.replace(/\s+/g, "_")}_${scope}_POs.pdf`);
      showToast("PDF downloaded", "success");
    } catch (err) { fail(err, "PDF failed"); }
  }

  async function poPdf(po: PurchaseOrder) {
    const blob = await apiBlob(`/api/procurement/purchase-orders/${po.id}/pdf`);
    saveBlob(blob, `${po.po_number}.pdf`);
  }

  async function printNotice(receipt: Receipt, po: PurchaseOrder) {
    const blob = await apiBlob(`/api/procurement/receipts/${receipt.id}/print-notice`, "POST");
    openBlob(blob, `Defect_Notice_${po.po_number}.pdf`);
  }

  async function viewFile(id: string, filename: string) {
    try { openBlob(await apiBlob(`/api/procurement/receipt-files/${id}`), filename); }
    catch (err) { fail(err, "Could not open file"); }
  }

  return (
    <main className="min-h-screen p-8">
      <PageHeader title="Procurement" description="Raise, approve and send purchase orders, then receive the goods with proof." />
      {error && <p className="text-red-600 dark:text-red-400 text-sm mb-4">{error}</p>}

      {loading ? (
        <SkeletonList rows={3} />
      ) : (
        <>
          <div className="grid md:grid-cols-2 gap-6 mb-8">
            <Card className="p-4">
              <form onSubmit={addVendor} className="space-y-2">
                <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Add Vendor</h2>
                <Input placeholder="Vendor name" required value={vendorForm.name} onChange={(e) => setVendorForm({ ...vendorForm, name: e.target.value })} />
                <Input placeholder="Vendor email (optional)" type="email" value={vendorForm.email} onChange={(e) => setVendorForm({ ...vendorForm, email: e.target.value })} />
                <Button className="w-full">Add Vendor</Button>
              </form>
            </Card>

            <Card className="p-4">
              <form onSubmit={createPO} className="space-y-2">
                <h2 className="font-semibold text-slate-700 dark:text-zinc-200 text-sm">Create Purchase Order</h2>
                <Select required aria-label="Vendor" value={poVendor} onChange={(e) => setPoVendor(e.target.value)}>
                  <option value="">Select vendor...</option>
                  {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </Select>
                {lines.map((l, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2 items-center">
                    <Select required aria-label="Product" className="col-span-6" value={l.product_id}
                      onChange={(e) => {
                        const p = products.find((x) => x.id === e.target.value);
                        setLine(i, { product_id: e.target.value, unit_price: l.unit_price || (p ? String(Number(p.unit_price)) : "") });
                      }}>
                      <option value="">Product...</option>
                      {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </Select>
                    <Input aria-label="Qty" className="col-span-2" type="number" min={1} required value={l.qty} onChange={(e) => setLine(i, { qty: e.target.value })} />
                    <Input aria-label="Unit cost" className="col-span-3" type="number" min={0} step="0.01" required placeholder="Unit cost" value={l.unit_price} onChange={(e) => setLine(i, { unit_price: e.target.value })} />
                    <button type="button" aria-label="Remove line" disabled={lines.length === 1}
                      onClick={() => setLines((ls) => ls.filter((_, idx) => idx !== i))}
                      className="col-span-1 text-slate-400 hover:text-red-600 disabled:opacity-30"><Trash2 size={16} /></button>
                  </div>
                ))}
                <div className="flex justify-between items-center">
                  <button type="button" onClick={() => setLines((ls) => [...ls, { product_id: "", qty: "1", unit_price: "" }])}
                    className="text-xs flex items-center gap-1 text-slate-600 dark:text-zinc-300 hover:underline"><Plus size={14} /> Add another product</button>
                  <span className="text-sm text-slate-600 dark:text-zinc-300">Quoted total: <b>{inr(poTotal)}</b></span>
                </div>
                <Button className="w-full">Create Purchase Order</Button>
              </form>
            </Card>
          </div>

          <section>
            <div className="flex flex-wrap items-end gap-3 mb-3">
              <h2 className="font-semibold text-slate-700 dark:text-zinc-200 mr-auto">Purchase Orders</h2>
              <div className="w-56">
                <Select aria-label="Filter by vendor" value={filterVendor} onChange={(e) => setFilterVendor(e.target.value)}>
                  <option value="">All vendors</option>
                  {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </Select>
              </div>
              {selectedVendor && (
                <>
                  <Button variant="secondary" size="sm" onClick={() => { setEditEmail(selectedVendor); setEditEmailValue(selectedVendor.email || ""); }}>
                    {selectedVendor.email ? `Email: ${selectedVendor.email}` : "Add vendor email"}
                  </Button>
                  <div className="relative">
                    <Button onClick={() => setMenuOpen((o) => !o)} aria-haspopup="menu" aria-expanded={menuOpen} className="flex items-center gap-1">
                      <FileDown size={15} /> Download PDF <ChevronDown size={14} />
                    </Button>
                    {menuOpen && (
                      <div role="menu" className="absolute right-0 mt-1 w-60 z-20 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-lg py-1">
                        {([["pending", "Pending items only"], ["approved", "Approved items only"], ["all", "All items"]] as const).map(([scope, label], i) => (
                          <button key={scope} role="menuitem" onClick={() => downloadVendorPdf(scope)}
                            className="w-full text-left px-3 py-2 text-sm text-slate-700 dark:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 flex justify-between">
                            <span>{i + 1}. {label}</span><span className="text-slate-400">{counts[scope]}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            <div className="space-y-3">
              {shown.map((po) => (
                <Card key={po.id} className="p-4" >
                  <div data-testid={`po-${po.po_number}`}>
                    <div className="flex flex-wrap justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-slate-800 dark:text-white">{po.po_number} · {po.vendor_name}</p>
                        <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
                          Raised by {po.created_by_name || "-"}{po.approved_by_name ? ` · ${po.approval_status === "rejected" ? "Rejected" : "Approved"} by ${po.approved_by_name}` : ""} · {po.order_date}
                        </p>
                      </div>
                      <div className="flex gap-2 items-start">
                        <Badge cls={APPROVAL_STYLE[po.approval_status]}>{APPROVAL_LABEL[po.approval_status]}</Badge>
                        {po.approval_status === "approved" && (
                          <Badge cls={po.status === "defective" ? APPROVAL_STYLE.rejected : "bg-slate-100 text-slate-700 dark:bg-zinc-800 dark:text-zinc-200"}>{DELIVERY_LABEL[po.status]}</Badge>
                        )}
                      </div>
                    </div>

                    <ul className="mt-2 text-sm text-slate-700 dark:text-zinc-200 space-y-0.5">
                      {po.items.map((i) => (
                        <li key={i.id} className="flex justify-between"><span>{i.product_name} × {i.qty} @ {inr(i.unit_price)}</span><span>{inr(i.line_total)}</span></li>
                      ))}
                      <li className="flex justify-between font-semibold border-t border-slate-200 dark:border-zinc-700 pt-1 mt-1"><span>Total</span><span>{inr(po.total)}</span></li>
                    </ul>

                    {po.receipts.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {po.receipts.map((r) => (
                          <div key={r.id} className={`text-xs rounded-lg p-2 ${r.condition === "good" ? "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-900 dark:text-emerald-200" : "bg-red-50 dark:bg-red-950/30 text-red-900 dark:text-red-200"}`}>
                            <p className="font-medium">
                              {r.condition === "good" ? "Received in good condition" : "Received in bad condition (not added to stock)"} · {r.received_date} · by {r.received_by_name || "-"}
                              {r.notes ? ` · ${r.notes}` : ""}
                            </p>
                            <div className="flex flex-wrap gap-2 mt-1">
                              {r.files.map((f) => (
                                <button key={f.id} onClick={() => viewFile(f.id, f.filename)} className="underline flex items-center gap-1">
                                  <Paperclip size={11} /> {f.kind === "pod" ? "POD" : f.kind === "invoice" ? "Invoice" : "Defect"}: {f.filename}
                                </button>
                              ))}
                              {r.condition === "bad" && (
                                <button onClick={() => setEmailTarget({ kind: "defect", po, receipt: r })} className="font-semibold underline">Send defect notice to vendor</button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="flex flex-wrap gap-2 mt-3">
                      {po.approval_status === "pending" && (
                        <>
                          <Button size="sm" onClick={() => decide(po, "approve")}>Approve</Button>
                          <Button size="sm" variant="secondary" onClick={() => decide(po, "reject")}>Reject</Button>
                        </>
                      )}
                      {po.approval_status === "approved" && (
                        <Button size="sm" variant="secondary" className="flex items-center gap-1" onClick={() => setEmailTarget({ kind: "po", po })}>
                          <Mail size={13} /> Send to vendor
                        </Button>
                      )}
                      {po.approval_status === "approved" && po.status !== "received" && po.status !== "cancelled" && (
                        <Button size="sm" className="flex items-center gap-1" onClick={() => setReceiveFor(po)}>
                          <PackageCheck size={13} /> Receive Goods
                        </Button>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
              {shown.length === 0 && <p className="text-sm text-slate-400 dark:text-zinc-500">No purchase orders{selectedVendor ? ` for ${selectedVendor.name}` : ""} yet.</p>}
            </div>
          </section>
        </>
      )}

      {emailTarget?.kind === "po" && (
        <EmailPreviewModal
          title={`Send ${emailTarget.po.po_number} to vendor`}
          previewPath={`/api/procurement/purchase-orders/${emailTarget.po.id}/email-preview`}
          sendPath={`/api/procurement/purchase-orders/${emailTarget.po.id}/send-email`}
          noEmailLabel="Download PO as PDF"
          onNoEmail={async () => { await poPdf(emailTarget.po); showToast("PDF downloaded for hand delivery", "success"); }}
          onClose={() => setEmailTarget(null)}
          onDone={(m, t) => showToast(m, t)}
        />
      )}
      {emailTarget?.kind === "defect" && (
        <EmailPreviewModal
          title={`Defect notice · ${emailTarget.po.po_number}`}
          previewPath={`/api/procurement/receipts/${emailTarget.receipt.id}/defect-preview`}
          sendPath={`/api/procurement/receipts/${emailTarget.receipt.id}/send-defect-email`}
          noEmailLabel="Print notice"
          onNoEmail={async () => { await printNotice(emailTarget.receipt, emailTarget.po); showToast("Notice opened for printing", "success"); }}
          onClose={() => setEmailTarget(null)}
          onDone={(m, t) => showToast(m, t)}
        />
      )}
      {receiveFor && (
        <ReceiveModal
          po={receiveFor}
          onClose={() => setReceiveFor(null)}
          onReceived={(updated, condition) => {
            setReceiveFor(null);
            loadAll();
            if (condition === "good") showToast("Goods received. Stock updated.", "success");
            else {
              showToast("Recorded as defective. Stock not changed.", "info");
              const bad = [...updated.receipts].reverse().find((r) => r.condition === "bad");
              if (bad) setEmailTarget({ kind: "defect", po: updated, receipt: bad });
            }
          }}
        />
      )}
      {editEmail && (
        <Modal title={`Email for ${editEmail.name}`} onClose={() => setEditEmail(null)}>
          <div className="space-y-3">
            <Input type="email" placeholder="orders@vendor.com (leave empty if none)" value={editEmailValue} onChange={(e) => setEditEmailValue(e.target.value)} />
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditEmail(null)}>Cancel</Button>
              <Button onClick={saveVendorEmail}>Save</Button>
            </div>
          </div>
        </Modal>
      )}
    </main>
  );
}
