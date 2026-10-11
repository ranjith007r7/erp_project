"use client";

/**
 * Sidebar module list with the Vercel-style motion:
 *   - ONE hover highlight that glides from item to item (it does not blink on and off per row),
 *     and fades away when the pointer leaves the list. Keyboard focus moves it too.
 *   - ONE active marker that slides from the old module to the new one when you switch, plus a
 *     small accent bar on its left edge.
 * Both are plain absolutely-positioned elements moved with transform, so they stay on the GPU.
 * People who ask their system for reduced motion get the same highlights without the gliding.
 */
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";

export type NavItem = { name: string; href: string; icon: LucideIcon };

type Box = { y: number; h: number };

export function SidebarNav({ items, compact, isActive, placeholders }: {
  items: NavItem[]; compact: boolean; isActive: (href: string) => boolean; placeholders: boolean;
}) {
  const listRef = useRef<HTMLElement>(null);
  const refs = useRef<Record<string, HTMLAnchorElement | null>>({});
  const [hover, setHover] = useState<Box | null>(null);
  const [active, setActive] = useState<Box | null>(null);
  const [hoverSeen, setHoverSeen] = useState(false);   // the first appearance should fade in, not fly in from the top
  const [activeSeen, setActiveSeen] = useState(false);

  const box = (href: string): Box | null => {
    const el = refs.current[href];
    return el ? { y: el.offsetTop, h: el.offsetHeight } : null;
  };

  const activeHref = items.find((n) => isActive(n.href))?.href;

  const measureActive = useCallback(() => {
    const b = activeHref ? box(activeHref) : null;
    setActive(b);
    if (b) requestAnimationFrame(() => setActiveSeen(true));
  }, [activeHref]);   // eslint-disable-line react-hooks/exhaustive-deps

  // re-measure when the route changes, the list changes, or the sidebar is collapsed / expanded / resized
  useLayoutEffect(() => { measureActive(); }, [measureActive, compact, items.length]);
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => measureActive());
    ro.observe(el);
    // items change height when the sidebar collapses to icons: watch them too
    Object.values(refs.current).forEach((a) => a && ro.observe(a));
    return () => ro.disconnect();
  }, [measureActive, items.length, compact]);

  const show = (href: string) => {
    const b = box(href);
    if (!b) return;
    setHover(b);
    if (!hoverSeen) requestAnimationFrame(() => setHoverSeen(true));
  };

  const ease = "transition-[transform,height,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none";

  return (
    <nav
      ref={listRef}
      aria-label="Modules"
      onMouseLeave={() => setHover(null)}
      className="relative flex-1 overflow-y-auto py-3 px-2 space-y-0.5"
    >
      {/* gliding hover highlight */}
      <span
        aria-hidden
        data-testid="nav-hover"
        className={`pointer-events-none absolute left-2 right-2 top-0 !mt-0 rounded-lg bg-slate-100 dark:bg-zinc-800 ${hoverSeen ? ease : "transition-opacity duration-150"}`}
        style={{ transform: `translateY(${hover?.y ?? 0}px)`, height: hover?.h ?? 0, opacity: hover ? 1 : 0 }}
      />
      {/* sliding active marker */}
      <span
        aria-hidden
        data-testid="nav-active"
        className={`pointer-events-none absolute left-2 right-2 top-0 !mt-0 rounded-lg bg-slate-800 dark:bg-zinc-100 shadow-sm ${activeSeen ? ease : ""}`}
        style={{ transform: `translateY(${active?.y ?? 0}px)`, height: active?.h ?? 0, opacity: active ? 1 : 0 }}
      >
        {!compact && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r bg-indigo-400 dark:bg-indigo-500" />}
      </span>

      {placeholders && Array.from({ length: 7 }).map((_, i) => <div key={i} className="h-9 rounded-lg bg-slate-100 dark:bg-zinc-800 animate-pulse" />)}
      {items.map((n) => {
        const Icon = n.icon;
        const act = n.href === activeHref;
        return (
          <Link
            key={n.href}
            href={n.href}
            ref={(el) => { refs.current[n.href] = el; }}
            title={compact ? n.name : undefined}
            aria-current={act ? "page" : undefined}
            onMouseEnter={() => show(n.href)}
            onFocus={() => show(n.href)}
            onBlur={() => setHover(null)}
            className={`group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${compact ? "justify-center px-2" : ""} ${
              act ? "text-white dark:text-zinc-950 font-medium" : "text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            <Icon size={18} className="shrink-0 transition-transform duration-200 ease-out group-hover:scale-110 motion-reduce:transform-none" />
            {!compact && <span className="truncate transition-transform duration-200 ease-out group-hover:translate-x-0.5 motion-reduce:transform-none">{n.name}</span>}
          </Link>
        );
      })}
    </nav>
  );
}
