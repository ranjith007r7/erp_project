"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";

type ToastType = "success" | "error" | "info";
type Toast = { id: string; type: ToastType; message: string };

type ToastContextValue = {
  showToast: (message: string, type?: ToastType) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

const ICONS: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
};

const STYLES: Record<ToastType, string> = {
  success: "bg-emerald-50 border-emerald-300 text-emerald-800",
  error: "bg-red-50 border-red-300 text-red-800",
  info: "bg-slate-50 border-slate-300 text-slate-800",
};

/**
 * Wrap the app (or a page) in <ToastProvider> once, then any child can
 * call useToast().showToast(...) - no prop-drilling a setter down
 * through every component that might need to report something.
 * Auto-dismisses after 4s; also individually dismissible, since some
 * messages (a real error) are worth reading longer than 4 seconds.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = useCallback((message: string, type: ToastType = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  function dismiss(id: string) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
        {toasts.map((t) => {
          const Icon = ICONS[t.type];
          return (
            <div
              key={t.id}
              className={`flex items-start gap-2 border rounded-lg px-3 py-2 shadow-md text-sm animate-toast-in ${STYLES[t.type]}`}
            >
              <Icon size={16} className="mt-0.5 shrink-0" />
              <p className="flex-1">{t.message}</p>
              <button onClick={() => dismiss(t.id)} className="shrink-0 opacity-60 hover:opacity-100">
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // A page rendered outside <ToastProvider> shouldn't crash - fall
    // back to a no-op so the calling code doesn't need its own
    // defensive check everywhere.
    return { showToast: () => {} };
  }
  return ctx;
}
