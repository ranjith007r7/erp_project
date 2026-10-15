"use client";

/**
 * Signs the person out after IDLE_MINUTES (default 10) of no activity - idle time, not total time:
 * any mouse move, key press, click, scroll or touch restarts the clock. The last-activity time lives in
 * localStorage so several tabs share one clock (working in one tab keeps the others alive), and it is
 * checked again the moment a tab becomes visible, because browsers throttle timers in background tabs
 * (a laptop left open overnight would otherwise stay signed in). A countdown shows for the last minute.
 */
import { useEffect, useRef, useState } from "react";
import { ACTIVITY_KEY } from "@/lib/api";

export const IDLE_MINUTES = Number(process.env.NEXT_PUBLIC_IDLE_MINUTES) > 0 ? Number(process.env.NEXT_PUBLIC_IDLE_MINUTES) : 10;
const IDLE_MS = IDLE_MINUTES * 60_000;
const WARN_MS = Math.min(60_000, IDLE_MS / 2);
const EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "wheel", "click"] as const;

function readLast(): number | null {
  try { const v = Number(localStorage.getItem(ACTIVITY_KEY)); return v > 0 ? v : null; } catch { return null; }
}

export function IdleLogout({ onTimeout }: { onTimeout: () => void }) {
  const [left, setLeft] = useState<number | null>(null);
  const lastWrite = useRef(0);
  const fired = useRef(false);

  useEffect(() => {
    const touch = () => {
      const now = Date.now();
      if (now - lastWrite.current < 1000) return;          // write at most once a second
      lastWrite.current = now;
      try { localStorage.setItem(ACTIVITY_KEY, String(now)); } catch { /* ignore */ }
    };
    const check = () => {
      if (fired.current) return;
      const last = readLast();
      if (last === null) { touch(); return; }              // sessions that started before this feature
      const idle = Date.now() - last;
      if (idle >= IDLE_MS) { fired.current = true; setLeft(null); onTimeout(); return; }
      setLeft(idle >= IDLE_MS - WARN_MS ? Math.ceil((IDLE_MS - idle) / 1000) : null);
    };
    const last = readLast();
    if (last === null || Date.now() - last < IDLE_MS) touch();   // never refresh a clock that already ran out (left open overnight)
    check();
    EVENTS.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", check);
    const t = setInterval(check, 1000);
    return () => {
      EVENTS.forEach((e) => window.removeEventListener(e, touch));
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", check);
      clearInterval(t);
    };
  }, [onTimeout]);

  if (left === null) return null;
  return (
    <div role="alert" data-testid="idle-warning" className="fixed bottom-4 right-4 z-[100] max-w-xs rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm shadow-lg dark:border-amber-500/40 dark:bg-zinc-900 dark:text-amber-200">
      <p className="font-semibold text-amber-900 dark:text-amber-300">Still there?</p>
      <p className="text-amber-800 dark:text-zinc-300">You will be signed out in {left}s because of inactivity. Move the mouse or press a key to stay signed in.</p>
    </div>
  );
}
