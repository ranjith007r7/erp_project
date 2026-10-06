"use client";

import { useEffect, useRef, useState } from "react";
import { LayoutGrid, LineChart, ShieldCheck, Sparkles, type LucideIcon } from "lucide-react";
import { BRAND } from "@/lib/brand";
import { usePrefersReducedMotion } from "@/lib/useReducedMotion";
import { BrandMark } from "./BrandMark";

// Every line here describes something the product really does. No customer counts, uptime
// figures or testimonials: marketing numbers that are not true do more damage than a plain page.
const HIGHLIGHTS: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: LayoutGrid,
    title: "Ten connected modules",
    text: "CRM, sales, procurement, inventory, finance, HR, projects, documents and reports, all working from the same records.",
  },
  {
    icon: Sparkles,
    title: "Ask your data in plain English",
    text: "Get answers straight from your own records, with the query shown. The assistant can read your data but never change it.",
  },
  {
    icon: ShieldCheck,
    title: "Access that follows the role",
    text: "Each person sees only what their role allows, and sensitive data such as salaries stays locked unless approved.",
  },
  {
    icon: LineChart,
    title: "Reports that come to you",
    text: "Live charts across every module, plus an optional weekly summary delivered by email.",
  },
];

const ROTATE_EVERY_MS = 5000;

export function BrandPanel() {
  const rootRef = useRef<HTMLElement>(null);
  const frame = useRef<number | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  const [active, setActive] = useState(0);
  // Hover and keyboard focus are tracked SEPARATELY and either one pauses the rotation. (They
  // once shared a single on/off switch, so moving focus away un-paused the carousel while the
  // mouse was still resting on it.)
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;

  // Auto-rotate the highlights; stop when the visitor hovers/focuses them or asks for less motion.
  useEffect(() => {
    if (paused || reducedMotion) return;
    const timer = setInterval(() => setActive((i) => (i + 1) % HIGHLIGHTS.length), ROTATE_EVERY_MS);
    return () => clearInterval(timer);
  }, [paused, reducedMotion]);

  // Gentle pointer parallax on the background glows: mouse only (not touch), never with reduced motion.
  function handlePointerMove(e: React.PointerEvent<HTMLElement>) {
    if (reducedMotion || e.pointerType !== "mouse") return;
    const el = rootRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
    const my = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      el.style.setProperty("--mx", mx.toFixed(3));
      el.style.setProperty("--my", my.toFixed(3));
    });
  }

  function resetParallax() {
    const el = rootRef.current;
    if (!el) return;
    el.style.setProperty("--mx", "0");
    el.style.setProperty("--my", "0");
  }

  useEffect(() => () => {
    if (frame.current) cancelAnimationFrame(frame.current);
  }, []);

  const glow = (x: number, y: number) => ({
    transform: `translate3d(calc(var(--mx, 0) * ${x}px), calc(var(--my, 0) * ${y}px), 0)`,
  });

  return (
    <aside
      ref={rootRef}
      aria-label={`About ${BRAND.productName}`}
      onPointerMove={handlePointerMove}
      onPointerLeave={resetParallax}
      className="relative hidden overflow-hidden bg-[#0a0d1f] text-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:justify-between lg:p-12 xl:p-16"
    >
      {/* ---- background: depth gradient, drifting glows, faint grid ---- */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(900px 520px at 12% -8%, rgba(99,102,241,0.32), transparent 62%), radial-gradient(760px 520px at 100% 100%, rgba(139,92,246,0.28), transparent 58%), linear-gradient(165deg, #0a0d1f 0%, #0f1330 55%, #150f2c 100%)",
        }}
      />
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute -left-28 -top-24 transition-transform duration-500 ease-out" style={glow(34, 26)}>
          <div className="h-[30rem] w-[30rem] rounded-full bg-indigo-500/30 blur-3xl motion-safe:animate-float-slow" />
        </div>
        <div className="absolute -bottom-32 -right-24 transition-transform duration-500 ease-out" style={glow(-30, -22)}>
          <div className="h-[28rem] w-[28rem] rounded-full bg-violet-500/25 blur-3xl motion-safe:animate-float-slower" />
        </div>
        <div className="absolute right-[18%] top-[34%] transition-transform duration-500 ease-out" style={glow(20, -30)}>
          <div className="h-56 w-56 rounded-full bg-cyan-400/15 blur-3xl motion-safe:animate-float-slow" />
        </div>
      </div>
      <div
        aria-hidden
        className="absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          maskImage: "radial-gradient(ellipse at 30% 30%, #000 10%, transparent 70%)",
          WebkitMaskImage: "radial-gradient(ellipse at 30% 30%, #000 10%, transparent 70%)",
        }}
      />

      {/* ---- content ---- */}
      <div className="relative flex items-center gap-3 motion-safe:animate-fade-up">
        <BrandMark size={44} />
        <div className="leading-tight">
          <p className="text-lg font-semibold tracking-tight">{BRAND.productName}</p>
          <p className="text-xs text-indigo-200/70">by {BRAND.companyName}</p>
        </div>
      </div>

      <div className="relative max-w-xl">
        <h2
          className="text-4xl font-semibold leading-[1.18] tracking-tight motion-safe:animate-fade-up xl:text-5xl"
          style={{ animationDelay: "80ms" }}
        >
          <span className="bg-gradient-to-br from-white via-white to-indigo-200 bg-clip-text text-transparent">
            {BRAND.tagline}
          </span>
        </h2>
        <p
          className="mt-4 max-w-md text-base leading-relaxed text-indigo-100/70 motion-safe:animate-fade-up"
          style={{ animationDelay: "160ms" }}
        >
          Sales, finance, inventory, people and projects, connected in one secure workspace for your whole team.
        </p>

        {/* rotating highlights: all stacked in one box so the layout never jumps */}
        <div
          className="mt-10 motion-safe:animate-fade-up"
          style={{ animationDelay: "260ms" }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onFocus={() => setFocused(true)}
          onBlur={(e) => {
            // moving focus between the dots is still "inside"; only leaving the group un-pauses
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
          }}
        >
          <div className="relative h-[8.5rem] rounded-2xl border border-white/10 bg-white/[0.06] shadow-2xl shadow-black/20 backdrop-blur-md">
            {HIGHLIGHTS.map(({ icon: Icon, title, text }, i) => {
              const on = i === active;
              return (
                <div
                  key={title}
                  aria-hidden={!on}
                  // Asymmetric on purpose: the slide LEAVING fades out quickly, and the one ARRIVING waits
                  // for it to be mostly gone before fading in. A plain symmetric crossfade leaves both
                  // slides half-visible at once, so their text overlaps for about half a second.
                  className={`absolute inset-0 flex items-start gap-4 p-5 transition-all ease-out motion-reduce:transition-none ${
                    on
                      ? "translate-y-0 opacity-100 duration-500 delay-300"
                      : "pointer-events-none translate-y-3 opacity-0 duration-300"
                  }`}
                >
                  <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500/80 to-violet-500/80 shadow-lg shadow-indigo-900/40">
                    <Icon size={20} aria-hidden />
                  </span>
                  <div>
                    <p className="font-semibold">{title}</p>
                    <p className="mt-1 text-sm leading-relaxed text-indigo-100/70">{text}</p>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 flex items-center gap-2" role="tablist" aria-label="Product highlights">
            {HIGHLIGHTS.map((h, i) => (
              <button
                key={h.title}
                type="button"
                role="tab"
                aria-selected={i === active}
                aria-label={`Show highlight ${i + 1}: ${h.title}`}
                onClick={() => setActive(i)}
                className={`h-1.5 rounded-full transition-all duration-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 ${
                  i === active ? "w-8 bg-white" : "w-3 bg-white/30 hover:bg-white/50"
                }`}
              />
            ))}
          </div>
        </div>
      </div>

      <p className="relative text-xs text-indigo-200/50">
        © {new Date().getFullYear()} {BRAND.companyName}. All rights reserved.
      </p>
    </aside>
  );
}
