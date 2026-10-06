"use client";

import { useEffect, useId, useState } from "react";
import { BRAND } from "@/lib/brand";

/**
 * The logo. If NEXT_PUBLIC_LOGO_URL is set, that image is shown on a white chip (so any logo,
 * dark or light, stays readable on both the dark brand panel and a dark-theme page). If it is
 * not set, or fails to load, a monogram of the product name's first letter is drawn in code,
 * so there is never a broken-image icon. For the default name ("Ratoon ERP") the letter is
 * drawn as the same geometric R as the favicon.
 */
export function BrandMark({ size = 40, className = "" }: { size?: number; className?: string }) {
  // The custom logo is only SHOWN once a background probe proves it loads. A plain <img onError>
  // is not enough: this page is pre-rendered, so the browser can fail to load the image before
  // React has attached its handlers, the error event is then lost, and a broken-image icon stays
  // on screen forever. While the probe runs a same-size blank keeps the layout from jumping.
  const [logo, setLogo] = useState<"checking" | "ok" | "failed">(BRAND.logoUrl ? "checking" : "failed");
  useEffect(() => {
    if (!BRAND.logoUrl) return;
    const probe = new window.Image();
    probe.onload = () => setLogo("ok");
    probe.onerror = () => setLogo("failed");
    probe.src = BRAND.logoUrl;
  }, []);

  // Each copy of the logo needs its OWN gradient id. The page draws the logo twice (brand panel
  // and mobile header); with a shared id, the copy inside the panel (hidden on phones with
  // display:none) wins the lookup, a browser cannot resolve a gradient defined inside a hidden
  // element, and the visible logo loses its purple square, leaving a white "R" on nothing.
  const gradientId = `brandmark-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  if (BRAND.logoUrl && logo === "checking") {
    return <span aria-hidden className={`inline-block ${className}`} style={{ height: size, width: size }} />;
  }

  if (BRAND.logoUrl && logo === "ok") {
    return (
      <span
        className={`inline-flex items-center justify-center rounded-xl bg-white p-1.5 shadow-sm ring-1 ring-black/5 ${className}`}
        style={{ height: size, minWidth: size }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- a client-supplied logo of unknown size and type */}
        <img src={BRAND.logoUrl} alt={BRAND.companyName} style={{ height: size - 12, width: "auto" }} />
      </span>
    );
  }

  const letter = BRAND.productName.trim().charAt(0).toUpperCase() || "E";
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label={BRAND.productName}
      className={`shrink-0 ${className}`}
    >
      <defs>
        <linearGradient id={gradientId} x1="6" y1="2" x2="60" y2="62" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="1" stopColor="#7c3aed" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="15" fill={`url(#${gradientId})`} />
      {letter === "R" ? (
        <path
          d="M23 47V17h11.5a9.75 9.75 0 0 1 0 19.5H23M35 36.5L43.5 47"
          fill="none"
          stroke="#ffffff"
          strokeWidth="6.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : (
        <text x="32" y="45" textAnchor="middle" fontSize="34" fontWeight="700" fill="#ffffff" fontFamily="system-ui, sans-serif">
          {letter}
        </text>
      )}
    </svg>
  );
}
