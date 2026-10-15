"use client";

/**
 * Spins the browser-tab icon while the app is waiting on the server (API requests or a page change), like
 * most web apps do. Tab icons cannot run CSS or SVG animation reliably, so frames are drawn on a canvas
 * and swapped in every ~90ms; the real icon is put back as soon as everything has finished. It only starts
 * after 350ms of waiting, so quick requests and background polling never make the icon flicker.
 */
import { useEffect } from "react";
import { usePathname } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const QUIET = ["/api/notifications"];                          // polled in the background: never spin for these
let inflight = 0;
const listeners = new Set<() => void>();
const bump = (d: number) => { inflight = Math.max(0, inflight + d); listeners.forEach((l) => l()); };

function patchFetchOnce() {
  const w = window as unknown as { __erpFetchPatched?: boolean };
  if (w.__erpFetchPatched) return;
  w.__erpFetchPatched = true;
  const orig = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!url.startsWith(API_URL) || QUIET.some((q) => url.includes(q))) return orig(input, init);
    bump(1);
    return orig(input, init).finally(() => bump(-1));
  };
}

function frame(step: number): string {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = "#4f46e5";
  g.beginPath(); g.arc(32, 32, 30, 0, Math.PI * 2); g.fill();
  g.lineWidth = 8; g.lineCap = "round";
  g.strokeStyle = "rgba(255,255,255,0.28)";
  g.beginPath(); g.arc(32, 32, 16, 0, Math.PI * 2); g.stroke();
  g.strokeStyle = "#ffffff";
  const a = (step / 12) * Math.PI * 2 - Math.PI / 2;
  g.beginPath(); g.arc(32, 32, 16, a, a + Math.PI * 0.9); g.stroke();
  return c.toDataURL("image/png");
}

export function FaviconLoader() {
  const pathname = usePathname();

  useEffect(() => {
    patchFetchOnce();
    let spinning = false, step = 0;
    let frames: string[] | null = null;
    let anim: ReturnType<typeof setInterval> | null = null;
    let delay: ReturnType<typeof setTimeout> | null = null;
    let saved: { el: HTMLLinkElement; href: string; type: string | null }[] = [];

    const links = () => Array.from(document.querySelectorAll<HTMLLinkElement>("link[rel~='icon']"));
    const start = () => {
      if (spinning) return;
      let els = links();
      if (!els.length) { const el = document.createElement("link"); el.rel = "icon"; document.head.appendChild(el); els = [el]; }
      spinning = true;
      saved = els.map((el) => ({ el, href: el.getAttribute("href") || "", type: el.getAttribute("type") }));
      frames = frames || Array.from({ length: 12 }, (_, i) => frame(i));
      anim = setInterval(() => {
        step = (step + 1) % 12;
        saved.forEach(({ el }) => { el.setAttribute("type", "image/png"); el.setAttribute("href", frames![step]); });
      }, 90);
    };
    const stop = () => {
      if (!spinning) return;
      spinning = false;
      if (anim) clearInterval(anim);
      saved.forEach(({ el, href, type }) => {
        if (href) el.setAttribute("href", href); else el.remove();
        if (type) el.setAttribute("type", type); else el.removeAttribute("type");
      });
      saved = [];
    };
    const sync = () => {
      if (inflight > 0) { if (!delay && !spinning) delay = setTimeout(() => { delay = null; if (inflight > 0) start(); }, 350); }
      else { if (delay) { clearTimeout(delay); delay = null; } stop(); }
    };
    listeners.add(sync);
    return () => { listeners.delete(sync); stop(); if (delay) clearTimeout(delay); };
  }, []);

  // a page change counts as waiting until the new page has rendered
  useEffect(() => {
    bump(1);
    const t = setTimeout(() => bump(-1), 400);
    return () => { clearTimeout(t); };
  }, [pathname]);

  return null;
}
