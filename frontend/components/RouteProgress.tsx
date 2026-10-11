"use client";

/**
 * A thin accent bar across the top that starts the instant an internal link is clicked and
 * completes when the new page has arrived (what Vercel's dashboard does). Without it a slow
 * first load (free-tier server waking up) looks like nothing happened.
 */
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

export function RouteProgress() {
  const pathname = usePathname();
  const [width, setWidth] = useState(0);       // 0..100
  const [visible, setVisible] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const hide = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = () => { if (timer.current) { clearInterval(timer.current); timer.current = null; } };

  function start() {
    stop();
    if (hide.current) clearTimeout(hide.current);
    setVisible(true);
    setWidth(8);
    // creep towards 90% and wait there until the page really arrives
    timer.current = setInterval(() => setWidth((w) => (w < 90 ? w + (90 - w) * 0.12 : w)), 180);
  }

  // a click on an internal link to another page starts the bar
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a");
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname) return;
      start();
    };
    document.addEventListener("click", onClick);
    return () => { document.removeEventListener("click", onClick); stop(); };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // the new route is in: finish and fade out
  useEffect(() => {
    if (!visible) return;
    stop();
    setWidth(100);
    hide.current = setTimeout(() => { setVisible(false); setWidth(0); }, 260);
    return () => { if (hide.current) clearTimeout(hide.current); };
  }, [pathname]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div aria-hidden data-testid="route-progress" className="fixed top-0 left-0 right-0 z-[60] h-0.5 pointer-events-none" style={{ opacity: visible ? 1 : 0, transition: "opacity 200ms ease" }}>
      <div
        className="h-full bg-gradient-to-r from-indigo-500 via-violet-500 to-sky-400 shadow-[0_0_8px_rgba(99,102,241,0.7)]"
        style={{ width: `${width}%`, transition: width === 0 ? "none" : "width 220ms ease-out" }}
      />
    </div>
  );
}
