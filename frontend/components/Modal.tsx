"use client";

/**
 * The one modal shell every prompt/confirm replacement uses. Deliberately
 * unopinionated about content — it just handles the overlay, the box, the
 * title, and Escape-to-close. Callers put whatever form or message they
 * need as children. This is the "consistent design pass" starting point:
 * one modal implementation instead of three ad-hoc ones.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui";

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  // Rendered into <body> so no transformed/animated ancestor can pull the overlay away from the viewport.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 bg-slate-900/40 flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className={`bg-white dark:bg-zinc-900 rounded-xl shadow-lg p-6 w-full max-h-[90vh] overflow-y-auto ${wide ? "max-w-2xl" : "max-w-md"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-slate-800 dark:text-white">{title}</h2>
          <button onClick={onClose} className="text-slate-400 dark:text-zinc-500 hover:text-slate-600 dark:hover:text-zinc-300 text-xl leading-none">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

/**
 * A focused wrapper around Modal for the one-off "type a value" case —
 * covers Convert Lead's two prompts and Reports' "name this view" prompt
 * without every call site rebuilding its own form.
 */
export function PromptModal({
  title,
  label,
  defaultValue = "",
  placeholder,
  onSubmit,
  onClose,
}: {
  title: string;
  label: string;
  defaultValue?: string;
  placeholder?: string;
  onSubmit: (value: string) => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const value = (e.currentTarget.elements.namedItem("value") as HTMLInputElement).value;
          onSubmit(value);
        }}
        className="space-y-3"
      >
        <label className="block text-sm text-slate-600 dark:text-zinc-300">
          {label}
          <input
            name="value"
            autoFocus
            required
            defaultValue={defaultValue}
            placeholder={placeholder}
            className="w-full border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-white rounded-lg px-3 py-2 text-sm mt-1"
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit">Confirm</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Replaces window.confirm() for destructive actions (delete, etc.) */
export function ConfirmModal({
  title,
  message,
  confirmLabel = "Confirm",
  danger = false,
  onConfirm,
  onClose,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-sm text-slate-600 dark:text-zinc-300 mb-4">{message}</p>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant={danger ? "danger" : "primary"} onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</Button>
      </div>
    </Modal>
  );
}
