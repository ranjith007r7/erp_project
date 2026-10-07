"use client";

/**
 * One modal for both vendor-facing documents: the purchase order and the
 * defective-goods notice. The template text comes from the server (common to
 * every vendor); this screen only collects the email address, shows the
 * preview, and sends. A vendor with no email uses "No email ID", which swaps
 * the send action for a printable / downloadable PDF.
 */
import { useEffect, useState } from "react";
import { Modal } from "@/components/Modal";
import { Button, Input } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import type { EmailPreview, SendResult } from "./types";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function EmailPreviewModal({
  title, previewPath, sendPath, noEmailLabel, onNoEmail, onClose, onDone,
}: {
  title: string;
  previewPath: string;
  sendPath: string;
  noEmailLabel: string; // e.g. "Download PDF" / "Print notice"
  onNoEmail: () => Promise<void>;
  onClose: () => void;
  onDone: (message: string, type: "success" | "info" | "error") => void;
}) {
  const [preview, setPreview] = useState<EmailPreview | null>(null);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [noEmail, setNoEmail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<EmailPreview>(previewPath, { auth: true })
      .then((p) => { setPreview(p); setEmail(p.to_email || ""); })
      .catch((e) => setError(e.message));
  }, [previewPath]);

  const valid = EMAIL_RE.test(email.trim());

  async function send() {
    setBusy(true); setError(null);
    try {
      const res = await apiRequest<SendResult>(sendPath, { method: "POST", auth: true, body: { to_email: email.trim(), note: note.trim() || null } });
      onDone(res.message, res.status === "sent" ? "success" : "info");
      onClose();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not send"); }
    setBusy(false);
  }

  async function fallback() {
    setBusy(true); setError(null);
    try { await onNoEmail(); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    setBusy(false);
  }

  return (
    <Modal title={title} onClose={onClose} wide>
      {error && <p className="text-red-600 dark:text-red-400 text-sm mb-3">{error}</p>}
      {!preview ? (
        !error && <p className="text-sm text-slate-500 dark:text-zinc-400">Loading preview…</p>
      ) : (
        <div className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg border border-slate-200 dark:border-zinc-700 p-2">
              <p className="text-xs text-slate-500 dark:text-zinc-400">From (your company)</p>
              <p className="font-medium text-slate-800 dark:text-white" data-testid="mail-from">{preview.from_name}</p>
            </div>
            <div className="rounded-lg border border-slate-200 dark:border-zinc-700 p-2">
              <p className="text-xs text-slate-500 dark:text-zinc-400">To (vendor)</p>
              <p className="font-medium text-slate-800 dark:text-white" data-testid="mail-to">{preview.to_name}</p>
            </div>
          </div>

          {!noEmail ? (
            <div>
              <Input label="Vendor email ID" id="vendor-email" type="email" placeholder="orders@vendor.com"
                value={email} onChange={(e) => setEmail(e.target.value)} />
              <button type="button" onClick={() => setNoEmail(true)}
                className="mt-1 text-xs underline text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-white">
                This vendor has no email ID
              </button>
            </div>
          ) : (
            <div className="rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800/60 text-amber-800 dark:text-amber-200 text-sm p-2">
              No email ID: preview the message below, then use <b>{noEmailLabel}</b> to hand it over in person.{" "}
              <button type="button" onClick={() => setNoEmail(false)} className="underline">Use email instead</button>
            </div>
          )}

          <div>
            <p className="text-xs text-slate-500 dark:text-zinc-400 mb-1">Subject</p>
            <p className="text-sm font-medium text-slate-800 dark:text-white" data-testid="mail-subject">{preview.subject}</p>
          </div>
          <pre data-testid="mail-body" className="whitespace-pre-wrap text-sm rounded-lg bg-slate-50 dark:bg-zinc-800 text-slate-800 dark:text-zinc-100 border border-slate-200 dark:border-zinc-700 p-3 font-sans max-h-72 overflow-y-auto">{preview.body}</pre>
          {preview.attachments.length > 0 && (
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              {noEmail ? "Included in the printout: " : "Attached automatically: "}{preview.attachments.join(", ")}
            </p>
          )}
          {!noEmail && (
            <label className="block text-sm text-slate-600 dark:text-zinc-300">
              Extra note (optional, added above the message)
              <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} rows={2}
                className="mt-1 w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm" />
            </label>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            {noEmail ? (
              <Button onClick={fallback} disabled={busy}>{busy ? "Preparing…" : noEmailLabel}</Button>
            ) : (
              <Button onClick={send} disabled={busy || !valid}>{busy ? "Sending…" : "Send email"}</Button>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
