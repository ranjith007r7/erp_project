"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiRequest, apiUpload, apiBlob, openBlob } from "@/lib/api";
import { PageHeader, Button, Card } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { useCurrentUser } from "@/components/AppShell";
import { SkeletonList } from "@/components/Skeleton";
import { Modal } from "@/components/Modal";
import { ClaimDetail, CLAIM_STYLE, fmtDate } from "@/lib/warranty";

const field = "w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm";
type Notice = { subject: string; body: string; to_name: string; to_email: string | null; attachments: string[] };

export default function ClaimPage() {
  const { id } = useParams<{ id: string }>();
  const { showToast } = useToast();
  const { can } = useCurrentUser();
  const [c, setC] = useState<ClaimDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resolution, setResolution] = useState("replace");
  const [note, setNote] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [toEmail, setToEmail] = useState("");
  const [extra, setExtra] = useState("");

  const load = useCallback(() => { apiRequest<ClaimDetail>(`/api/claims/${id}`, { auth: true }).then(setC).catch((e) => setError(e.message)); }, [id]);
  useEffect(() => { load(); }, [load]);

  async function act(path: string, body: unknown, ok: string) {
    setBusy(true);
    try { setC(await apiRequest<ClaimDetail>(`/api/claims/${id}${path}`, { method: "POST", auth: true, body })); showToast(ok, "success"); }
    catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); }
    setBusy(false);
  }
  async function upload(kind: string, files: FileList | null) {
    if (!files || !files.length) return;
    const fd = new FormData();
    fd.append("kind", kind);
    Array.from(files).forEach((f) => fd.append("files", f));
    setBusy(true);
    try { setC(await apiUpload<ClaimDetail>(`/api/claims/${id}/files`, fd)); }
    catch (e) { showToast(e instanceof Error ? e.message : "Upload failed", "error"); }
    setBusy(false);
  }
  async function remove(fid: string) {
    try { setC(await apiRequest<ClaimDetail>(`/api/claims/${id}/files/${fid}`, { method: "DELETE", auth: true })); }
    catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); }
  }
  async function view(fid: string, name: string) {
    try { openBlob(await apiBlob(`/api/claims/files/${fid}`), name); } catch (e) { showToast(e instanceof Error ? e.message : "Could not open", "error"); }
  }
  async function openNotice() {
    try { const n = await apiRequest<Notice>(`/api/claims/${id}/vendor-notice/preview`, { auth: true }); setNotice(n); setToEmail(n.to_email || ""); }
    catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); }
  }
  async function sendNotice() {
    setBusy(true);
    try {
      const r = await apiRequest<{ status: string; message: string }>(`/api/claims/${id}/vendor-notice/send`, { method: "POST", auth: true, body: { to_email: toEmail, note: extra || undefined } });
      showToast(r.message, r.status === "sent" ? "success" : "info"); setNotice(null); load();
    } catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); }
    setBusy(false);
  }
  async function printNotice() {
    try { openBlob(await apiBlob(`/api/claims/${id}/vendor-notice/print`, "POST"), "vendor-notice.pdf"); setNotice(null); load(); }
    catch (e) { showToast(e instanceof Error ? e.message : "Failed", "error"); }
  }

  if (error) return <main className="p-8"><p className="text-red-600">{error}</p></main>;
  if (!c) return <main className="p-8"><SkeletonList rows={4} /></main>;
  const open = c.status === "open";
  const approved = c.status === "replaced" || c.status === "repaired";

  return (
    <main className="min-h-screen p-4 sm:p-8 max-w-4xl">
      <PageHeader title={`${c.claim_number} · ${c.product_name}`} description={`${c.work_number} · ${c.client_name} · Serial ${c.serial_number || "-"}`} backHref="/claims" backLabel="← Claims"
        actions={<span className={`text-xs px-2 py-1 rounded-full font-semibold ${CLAIM_STYLE[c.status] || ""}`} data-testid="claim-status">{c.status_label}</span>} />

      {c.out_of_warranty && <p className="mb-4 text-sm rounded-lg px-3 py-2 bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300 font-semibold" data-testid="oow">OUT OF WARRANTY: the warranty ended on {fmtDate(c.warranty_end)}. Approving needs a reason.</p>}

      <Card className="p-4 mb-4">
        <div className="grid sm:grid-cols-3 gap-3 text-sm">
          <div><p className="text-xs text-slate-500 dark:text-zinc-400">Warranty card</p><p className="text-slate-800 dark:text-white">{c.card_number || "-"}</p></div>
          <div><p className="text-xs text-slate-500 dark:text-zinc-400">Coverage</p><p className="text-slate-800 dark:text-white">{fmtDate(c.warranty_start)} to {fmtDate(c.warranty_end)}</p></div>
          <div><p className="text-xs text-slate-500 dark:text-zinc-400">Model / manufactured</p><p className="text-slate-800 dark:text-white">{c.model_number || "-"} · {c.manufacture_month ? fmtDate(c.manufacture_month) : "-"}</p></div>
        </div>
        <p className="text-xs text-slate-500 dark:text-zinc-400 mt-3">Issue (raised by {c.created_by_name || "-"})</p>
        <p className="text-sm text-slate-800 dark:text-white whitespace-pre-wrap">{c.issue}</p>
      </Card>

      <Card className="p-4 mb-4" data-testid="documents">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-1">Required documents</h2>
        <p className="text-xs text-slate-500 dark:text-zinc-400 mb-3">All six are mandatory. The claim can go for approval only when every one is uploaded.</p>
        <div className="space-y-3">
          {c.required.map((r, i) => {
            const files = c.files.filter((f) => f.kind === r.kind);
            return (
              <div key={r.kind} className="flex flex-wrap items-center gap-3 border-t border-slate-100 dark:border-zinc-800 pt-3 first:border-0 first:pt-0" data-testid={`doc-${r.kind}`}>
                <span className={`inline-flex w-5 h-5 rounded-full items-center justify-center text-[11px] font-bold ${r.done ? "bg-emerald-500 text-white" : "bg-slate-200 dark:bg-zinc-700 text-slate-600 dark:text-zinc-300"}`}>{r.done ? "✓" : i + 1}</span>
                <div className="min-w-[200px] flex-1">
                  <p className="text-sm text-slate-800 dark:text-white">{r.label}</p>
                  <p className="text-xs text-slate-500 dark:text-zinc-400">{r.image_only ? "Photo (PNG, JPG, WEBP)" : "PDF or image"}</p>
                  {files.map((f) => (
                    <p key={f.id} className="text-xs">
                      <button className="underline text-indigo-600 dark:text-indigo-400 font-normal" onClick={() => view(f.id, f.filename)}>{f.filename}</button>
                      {open && can("claims", "edit") && <button className="ml-2 text-red-600 dark:text-red-400 font-normal" onClick={() => remove(f.id)} aria-label={`Remove ${f.filename}`}>remove</button>}
                    </p>
                  ))}
                </div>
                {open && can("claims", "edit") && (
                  <input type="file" id={`up-${r.kind}`} aria-label={`Upload ${r.label}`} multiple={r.kind === "supporting"} accept={r.image_only ? "image/png,image/jpeg,image/webp" : "application/pdf,image/png,image/jpeg,image/webp"}
                    onChange={(e) => { upload(r.kind, e.target.files); e.target.value = ""; }}
                    className="text-xs text-slate-700 dark:text-zinc-200 file:mr-2 file:rounded-lg file:border-0 file:bg-slate-800 file:text-white dark:file:bg-zinc-200 dark:file:text-zinc-900 file:px-3 file:py-1.5 file:text-xs" />
                )}
              </div>
            );
          })}
        </div>
        {open && can("claims", "edit") && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button disabled={busy || c.missing.length > 0} onClick={() => act("/submit", undefined, "Sent for approval.")} data-testid="submit-claim">Send for approval</Button>
            {c.missing.length > 0 && <span className="text-xs text-slate-500 dark:text-zinc-400">Still needed: {c.missing.join(", ")}</span>}
          </div>
        )}
      </Card>

      {c.status === "pending_approval" && (
        can("claims", "approve") ? (
          <Card className="p-4 mb-4" data-testid="decision">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-3">Decision</h2>
            <div className="grid sm:grid-cols-3 gap-3">
              <label className="block text-sm text-slate-600 dark:text-zinc-300">Resolution if approved
                <select className={`${field} mt-1`} value={resolution} onChange={(e) => setResolution(e.target.value)} data-testid="resolution">
                  <option value="replace">Replace the unit (opens a zero-value work)</option><option value="repair">Repair the unit</option>
                </select></label>
              <label className="block text-sm text-slate-600 dark:text-zinc-300 sm:col-span-2">Note {c.out_of_warranty ? "(required for an out-of-warranty claim, and for a rejection)" : "(required for a rejection)"}
                <input className={`${field} mt-1`} value={note} onChange={(e) => setNote(e.target.value)} data-testid="decision-note" /></label>
            </div>
            <div className="flex gap-2 mt-3">
              <Button disabled={busy} onClick={() => act("/approve", { resolution, note: note || undefined }, "Claim approved.")} data-testid="approve-claim">Approve</Button>
              <Button variant="danger" disabled={busy || note.trim().length < 2} onClick={() => act("/reject", { note }, "Claim rejected.")} data-testid="reject-claim">Reject</Button>
            </div>
          </Card>
        ) : <p className="mb-4 text-sm rounded-lg px-3 py-2 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200">Waiting for approval by a user with claims approval rights.</p>
      )}

      {(approved || c.status === "rejected") && (
        <Card className="p-4 mb-4" data-testid="outcome">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-1">{c.status_label} by {c.decided_by_name || "-"} · {c.decided_at ? fmtDate(c.decided_at.slice(0, 10)) : ""}</h2>
          {c.decision_note && <p className="text-sm text-slate-700 dark:text-zinc-300">{c.decision_note}</p>}
          {c.replacement_work && <p className="text-sm mt-2">Replacement work: <Link className="underline text-indigo-600 dark:text-indigo-400" href={`/workpage/${c.replacement_work.id}`} data-testid="replacement-link">{c.replacement_work.work_number}</Link> (zero value)</p>}
        </Card>
      )}

      {approved && (
        <Card className="p-4 mb-4" data-testid="vendor-card">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-1">Vendor side</h2>
          {c.vendor.traced ? (
            <p className="text-sm text-slate-700 dark:text-zinc-300">
              Supplied by <b>{c.vendor.name}</b>{c.vendor.po_number ? ` (${c.vendor.po_number})` : ""}.{" "}
              {c.vendor.warranty_months ? (c.vendor.in_vendor_warranty ? `Within the vendor's ${c.vendor.warranty_months}-month warranty (until ${fmtDate(c.vendor.warranty_end)}).` : `The vendor's ${c.vendor.warranty_months}-month warranty ended ${fmtDate(c.vendor.warranty_end)}.`) : "No vendor warranty is recorded on this lot."}
            </p>
          ) : <p className="text-sm text-slate-500 dark:text-zinc-400">This unit cannot be traced to a stock lot, so the vendor is unknown; you can still prepare the notice and type the address.</p>}
          {c.vendor.notice_at && <p className="text-xs text-emerald-700 dark:text-emerald-400 mt-1">Notice {c.vendor.notice_channel === "print" ? "printed" : `emailed to ${c.vendor.notice_to}`} on {fmtDate(c.vendor.notice_at.slice(0, 10))}.</p>}
          {can("claims", "edit") && <Button className="mt-3" variant="secondary" onClick={openNotice} data-testid="vendor-notice">{c.vendor.notice_at ? "Open the vendor notice again" : "Raise a defect notice to the vendor"}</Button>}
        </Card>
      )}

      {notice && (
        <Modal title="Vendor warranty notice" onClose={() => setNotice(null)} wide>
          <div className="space-y-3">
            <p className="text-sm text-slate-600 dark:text-zinc-300"><b>Subject:</b> {notice.subject}</p>
            <pre className="text-xs whitespace-pre-wrap rounded-lg bg-slate-50 dark:bg-zinc-800 text-slate-800 dark:text-zinc-200 p-3 max-h-64 overflow-y-auto" data-testid="notice-body">{notice.body}</pre>
            <p className="text-xs text-slate-500 dark:text-zinc-400">Attachments: {notice.attachments.join(", ") || "none"}. The customer's invoice and warranty copy are never sent.</p>
            <input className={field} placeholder="Vendor email" value={toEmail} onChange={(e) => setToEmail(e.target.value)} data-testid="notice-to" />
            <input className={field} placeholder="Add a line above the message (optional)" value={extra} onChange={(e) => setExtra(e.target.value)} />
            <div className="flex justify-between gap-2"><Button variant="secondary" onClick={printNotice}>No email ID: print notice</Button>
              <Button disabled={busy || !toEmail.includes("@")} onClick={sendNotice} data-testid="notice-send">Send email</Button></div>
          </div>
        </Modal>
      )}
    </main>
  );
}
