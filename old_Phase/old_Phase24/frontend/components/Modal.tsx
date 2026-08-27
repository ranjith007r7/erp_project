"use client";

/**
 * The one modal shell every prompt/confirm replacement uses. Deliberately
 * unopinionated about content — it just handles the overlay, the box, the
 * title, and Escape-to-close. Callers put whatever form or message they
 * need as children. This is the "consistent design pass" starting point:
 * one modal implementation instead of three ad-hoc ones.
 */
import { useEffect } from "react";

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-slate-900/40 flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-lg p-6 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl leading-none">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
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
        <label className="block text-sm text-slate-600">
          {label}
          <input
            name="value"
            autoFocus
            required
            defaultValue={defaultValue}
            placeholder={placeholder}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm mt-1"
          />
        </label>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-slate-500 px-3 py-1.5 rounded-lg hover:bg-slate-100"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="text-sm bg-slate-800 text-white px-4 py-1.5 rounded-lg hover:bg-slate-700"
          >
            Confirm
          </button>
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
      <p className="text-sm text-slate-600 mb-4">{message}</p>
      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="text-sm text-slate-500 px-3 py-1.5 rounded-lg hover:bg-slate-100">
          Cancel
        </button>
        <button
          onClick={() => {
            onConfirm();
            onClose();
          }}
          className={`text-sm text-white px-4 py-1.5 rounded-lg ${
            danger ? "bg-red-600 hover:bg-red-700" : "bg-slate-800 hover:bg-slate-700"
          }`}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
